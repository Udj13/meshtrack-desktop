"""Кастомная URL-схема map:// для раздачи тайлов из MBTiles в Leaflet.

Регистрируется через QWebEngineUrlScheme перед созданием QApplication.
MapSchemeHandler обрабатывает запросы вида:
    map://{map_id}/{z}/{x}/{y}.png
При отсутствии тайла возвращает 1×1 прозрачный PNG.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QTimer
from PySide6.QtWebEngineCore import (
    QWebEngineUrlRequestJob,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)

from .mapstore import MapStore, is_valid_tile_blob
from .settings import Settings

logger = logging.getLogger(__name__)

# 1×1 прозрачный PNG (RFC 2083 minimal).
TRANSPARENT_PNG = bytes(
    [
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4,
        0x89, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x44, 0x41,
        0x54, 0x08, 0xD7, 0x63, 0x60, 0x60, 0x60, 0x60,
        0x00, 0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x05,
        0xFE, 0xD4, 0x6A, 0xE6, 0x00, 0x00, 0x00, 0x00,
        0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
    ]
)

# map://map_id/z/x/y.png
_URL_RE = re.compile(r"^map://([-\w]+)/(\d+)/(\d+)/(\d+)\.png$")


def parse_map_url(url: str) -> tuple[str, int, int, int] | None:
    """Парсит URL map://id/z/x/y.png. Возвращает (id, z, x, y) или None."""
    match = _URL_RE.match(url)
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3)), int(match.group(4))


class MapSchemeHandler(QWebEngineUrlSchemeHandler):
    """Обработчик схемы map://.

    settings: объект Settings для поиска пути к MBTiles по map_id.
    """

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._active_devices: set[QBuffer] = set()
        # Карты, по которым уже предупредили о промахах тайлов (INFO один раз).
        self._miss_warned: set[str] = set()

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        url = job.requestUrl().toString()
        parsed = parse_map_url(url)
        if parsed is None:
            logger.warning("Invalid map URL: %s", url)
            self._reply(job, TRANSPARENT_PNG, b"image/png")
            return

        map_id, z, x, y = parsed

        path = self._settings.get_map_path(map_id)
        if not path:
            logger.warning("No map path for id=%s", map_id)
            self._reply(job, TRANSPARENT_PNG, b"image/png")
            return

        if not Path(path).exists():
            logger.error("Map file not found: %s", path)
            self._reply(job, TRANSPARENT_PNG, b"image/png")
            return

        try:
            store = MapStore(path)
            data = store.get(z, x, y)
        except Exception as exc:
            logger.exception("MapStore error for %s: %s", path, exc)
            data = None

        if data is None:
            logger.debug("Tile miss: %s z=%d x=%d y=%d", map_id, z, x, y)
            if map_id not in self._miss_warned:
                self._miss_warned.add(map_id)
                logger.info(
                    "Тайлы не найдены в области: map://%s/%d/%d/%d.png — "
                    "область просмотра вне bbox/зума загруженной карты "
                    "«%s» (файл %s); перекачайте карту под нужный регион",
                    map_id, z, x, y, map_id, path,
                )
            self._reply(job, TRANSPARENT_PNG, b"image/png")
        elif not is_valid_tile_blob(data):
            # В старой/битой карте может лежать html вместо PNG — в рендер
            # не отдаём: декодер Chromium такое не переваривает → серые тайлы.
            logger.warning(
                "Tile не PNG (повреждён): %s z=%d x=%d y=%d (%d байт) — перекачайте карту",
                map_id, z, x, y, len(data),
            )
            self._reply(job, TRANSPARENT_PNG, b"image/png")
        else:
            logger.debug("Tile hit: %s z=%d x=%d y=%d (%d bytes)", map_id, z, x, y, len(data))
            self._reply(job, data, b"image/png")

    def _reply(
        self, job: QWebEngineUrlRequestJob, data: bytes, content_type: bytes
    ) -> None:
        buf = QByteArray(data)
        device = QBuffer(self)
        device.setData(buf)
        device.open(QBuffer.OpenModeFlag.ReadOnly)
        # QWebEngineUrlRequestJob заберёт владение device; сохраняем ссылку,
        # чтобы Python не удалил обёртку до завершения запроса.
        self._active_devices.add(device)
        job.reply(content_type, device)
        # Удаляем ссылку после небольшой задержки.
        QTimer.singleShot(5000, lambda: self._active_devices.discard(device))


# Схема регистрируется один раз до создания QApplication.
_SCHEME_REGISTERED = False


def register_map_scheme() -> None:
    """Регистрирует схему map:// в QtWebEngine."""
    global _SCHEME_REGISTERED
    if _SCHEME_REGISTERED:
        return
    scheme = QWebEngineUrlScheme(b"map")
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setDefaultPort(0)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
        | QWebEngineUrlScheme.Flag.CorsEnabled
        | QWebEngineUrlScheme.Flag.FetchApiAllowed
    )
    QWebEngineUrlScheme.registerScheme(scheme)
    _SCHEME_REGISTERED = True


def install_map_handler(
    profile, settings: Settings, parent=None
) -> MapSchemeHandler:
    """Устанавливает обработчик схемы map:// на profile."""
    handler = MapSchemeHandler(settings, parent=parent)
    profile.installUrlSchemeHandler(b"map", handler)
    return handler
