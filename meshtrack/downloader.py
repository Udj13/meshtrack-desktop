"""Скачивание растровых тайлов в MBTiles.

Поддерживает:
- многопоточность (4 worker по умолчанию);
- rate-limit ≥ 200 мс на хост;
- resume (пропуск уже скачанных тайлов в MapStore);
- экспоненциальный backoff при 429/5xx;
- progress callback (downloaded, total);
- отмену через threading.Event.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import requests

from .mapstore import MapStore

logger = logging.getLogger(__name__)

# Минимальная задержка между запросами к одному хосту (сек).
RATE_LIMIT_SECONDS = 0.2
DEFAULT_WORKERS = 4


def _tile_xy(lat: float, lon: float, z: int) -> tuple[int, int]:
    """Преобразует lat/lon в tile x,y (XYZ) на zoom z."""
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0
        * n
    )
    return x, y


def tile_range_for_bbox(
    south: float, north: float, west: float, east: float, z: int
) -> tuple[int, int, int, int]:
    """Возвращает (xmin, xmax, ymin, ymax) в XYZ для bbox на zoom z."""
    x1, y1 = _tile_xy(north, west, z)
    x2, y2 = _tile_xy(south, east, z)
    n = 2**z
    xmin = max(0, min(x1, x2))
    xmax = min(n - 1, max(x1, x2))
    ymin = max(0, min(y1, y2))
    ymax = min(n - 1, max(y1, y2))
    return xmin, xmax, ymin, ymax


def estimate_tile_count(
    south: float, north: float, west: float, east: float, zmin: int, zmax: int
) -> int:
    """Оценка количества тайлов в bbox по диапазону зумов."""
    total = 0
    for z in range(zmin, zmax + 1):
        xmin, xmax, ymin, ymax = tile_range_for_bbox(south, north, west, east, z)
        total += (xmax - xmin + 1) * (ymax - ymin + 1)
    return total


class TileDownloader:
    """Потокобезопасный загрузчик тайлов с rate-limit."""

    def __init__(
        self,
        store: MapStore,
        url_template: str,
        rate_limit: float = RATE_LIMIT_SECONDS,
    ):
        self.store = store
        self.url_template = url_template
        self.rate_limit = rate_limit
        self._last_fetch: dict[str, float] = {}
        self._last_lock = threading.Lock()
        self._session = requests.Session()

    def _url(self, z: int, x: int, y: int) -> str:
        return self.url_template.format(z=z, x=x, y=y)

    def _wait_for_rate_limit(self, host: str) -> None:
        with self._last_lock:
            now = time.monotonic()
            last = self._last_fetch.get(host)
            if last is not None:
                elapsed = now - last
                if elapsed < self.rate_limit:
                    time.sleep(self.rate_limit - elapsed)
            self._last_fetch[host] = time.monotonic()

    def _download_one(
        self, z: int, x: int, y: int, cancel_event: threading.Event | None = None
    ) -> tuple[int, int, int, bytes | None]:
        """Скачивает один тайл. Возвращает (z, x, y, data) или None при ошибке."""
        if cancel_event is not None and cancel_event.is_set():
            return z, x, y, None

        # Resume: если тайл уже есть, пропускаем.
        if self.store.has(z, x, y):
            return z, x, y, b""  # пустые bytes = "уже есть"

        url = self._url(z, x, y)
        host = url.split("/", 3)[2] if "//" in url else url

        self._wait_for_rate_limit(host)

        attempts = 0
        max_attempts = 4
        backoff = 1.0
        while attempts < max_attempts:
            if cancel_event is not None and cancel_event.is_set():
                return z, x, y, None
            try:
                resp = self._session.get(url, timeout=30)
                if resp.status_code == 200:
                    return z, x, y, resp.content
                if resp.status_code == 429 or resp.status_code >= 500:
                    logger.warning(
                        "HTTP %d для %s, попытка %d", resp.status_code, url, attempts + 1
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    attempts += 1
                    continue
                logger.warning("HTTP %d для %s", resp.status_code, url)
                return z, x, y, None
            except requests.RequestException as exc:
                logger.warning("Ошибка загрузки %s: %s", url, exc)
                time.sleep(backoff)
                backoff *= 2
                attempts += 1
        logger.error("Не удалось загрузить %s после %d попыток", url, max_attempts)
        return z, x, y, None


def _format_size(bytes_count: int) -> str:
    """Возвращает читаемое представление размера (Б, КБ, МБ, ГБ)."""
    if bytes_count < 1024:
        return f"{bytes_count} Б"
    if bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} КБ"
    if bytes_count < 1024 * 1024 * 1024:
        return f"{bytes_count / (1024 * 1024):.1f} МБ"
    return f"{bytes_count / (1024 * 1024 * 1024):.2f} ГБ"


def _format_time(seconds: float) -> str:
    """Форматирует секунды в '1 мин 30 с' или '45 с'."""
    if seconds < 60:
        return f"{int(seconds)} с"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes} мин {secs} с"


def download(
    store: MapStore,
    bbox: tuple[float, float, float, float],
    url_template: str,
    zmin: int = 9,
    zmax: int = 15,
    workers: int = DEFAULT_WORKERS,
    on_progress: Callable[[int, int, dict], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Скачивает область bbox в MapStore.

    Аргументы:
        store: MapStore для записи тайлов.
        bbox: (south, north, west, east).
        url_template: шаблон URL, например
            'https://tile.opentopomap.org/{z}/{x}/{y}.png'.
        zmin, zmax: диапазон zoom.
        workers: количество потоков.
        on_progress: callback(done, total, stats), где stats — dict с ключами
            bytes_downloaded, bytes_estimated, tiles_per_second,
            bytes_per_second, seconds_remaining.
        cancel_event: threading.Event для отмены.

    Возвращает dict:
        total: общее число тайлов
        downloaded: вновь скачанных
        skipped: уже было в хранилище
        failed: не удалось скачать
        bytes_downloaded: скачано байт
        bytes_estimated: оценка общего объёма байт
        elapsed_seconds: затраченное время
    """
    south, north, west, east = bbox
    tiles: list[tuple[int, int, int]] = []
    for z in range(zmin, zmax + 1):
        xmin, xmax, ymin, ymax = tile_range_for_bbox(south, north, west, east, z)
        for x in range(xmin, xmax + 1):
            for y in range(ymin, ymax + 1):
                tiles.append((z, x, y))

    total = len(tiles)
    downloader = TileDownloader(store, url_template)

    downloaded = 0
    skipped = 0
    failed = 0
    bytes_downloaded = 0
    start_time = time.monotonic()

    def build_stats() -> dict:
        elapsed = time.monotonic() - start_time
        tiles_done = downloaded + skipped
        tps = tiles_done / elapsed if elapsed > 0 else 0.0
        bps = bytes_downloaded / elapsed if elapsed > 0 else 0.0
        avg_tile_size = bytes_downloaded / downloaded if downloaded > 0 else 0
        bytes_estimated = int(total * avg_tile_size) if avg_tile_size > 0 else 0
        seconds_remaining = None
        if tps > 0 and total > tiles_done:
            seconds_remaining = (total - tiles_done) / tps
        return {
            "bytes_downloaded": bytes_downloaded,
            "bytes_estimated": bytes_estimated,
            "tiles_per_second": tps,
            "bytes_per_second": bps,
            "seconds_remaining": seconds_remaining,
            "elapsed_seconds": elapsed,
        }

    def emit_progress():
        if on_progress is not None:
            try:
                on_progress(downloaded + skipped, total, build_stats())
            except Exception:
                logger.exception("Ошибка в on_progress")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_to_tile = {
            executor.submit(downloader._download_one, z, x, y, cancel_event): (z, x, y)
            for z, x, y in tiles
        }
        batch: list[tuple[int, int, int, bytes]] = []
        batch_lock = threading.Lock()

        def flush_batch():
            nonlocal batch
            with batch_lock:
                if not batch:
                    return
                to_write = batch
                batch = []
            try:
                store.insert_many(to_write)
            except Exception:
                logger.exception("Ошибка записи батча тайлов")

        for future in as_completed(future_to_tile):
            z, x, y = future_to_tile[future]
            try:
                _, _, _, data = future.result()
            except Exception as exc:
                logger.exception("Ошибка задачи загрузки %d/%d/%d: %s", z, x, y, exc)
                failed += 1
                continue

            if cancel_event is not None and cancel_event.is_set():
                # Завершаем без учёта оставшихся
                break

            if data is None:
                failed += 1
            elif data == b"":
                skipped += 1
            else:
                with batch_lock:
                    batch.append((z, x, y, data))
                downloaded += 1
                bytes_downloaded += len(data)
                if len(batch) >= 50:
                    flush_batch()

            emit_progress()

        flush_batch()

    elapsed = time.monotonic() - start_time
    store.set_minmax_zoom(zmin, zmax)
    return {
        "total": total,
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "bytes_downloaded": bytes_downloaded,
        "bytes_estimated": build_stats()["bytes_estimated"],
        "elapsed_seconds": elapsed,
    }
