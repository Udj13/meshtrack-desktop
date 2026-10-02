"""Реестр источников растровых тайлов.

Чистый от Qt модуль: описывает доступные тайл-серверы (шаблон URL, резерв,
формат тайлов) для офлайн-скачивания карт через downloader.download().
Выбор источника — в мастере загрузки карты и диалоге карт; вместо жёстко
зашитого OpenTopoMap пользователь может взять Esri World Topo (с контурами)
или стандартный OSM.

Формат тайлов ('png'/'jpeg') пишется в metadata MBTiles и определяет
валидацию (mapstore.is_valid_tile_blob) и Content-Type при раздаче (mapscheme).
"""

from __future__ import annotations

from dataclasses import dataclass

# URL-шаблон OpenTopoMap (PROJECT.md §8).
OPENTOPOMAP_TEMPLATE = "https://tile.opentopomap.org/{z}/{x}/{y}.png"
# Официальный резервный сервер OpenTopoMap (roadmap на opentopomap.org):
# основной иногда отвечает анти-бот HTML/таймаутами — тайл пробуется и с него.
OPENTOPOMAP_BACKUP_TEMPLATE = "https://backup.opentopomap.org/{z}/{x}/{y}.png"


@dataclass(frozen=True)
class TileSource:
    """Описывает тайл-сервер: шаблоны URL, формат и подпись.

    name: отображаемое имя (msgid для i18n; для 'ru' возвращается как есть,
        для 'en' нужно добавить перевод в catalog_en.json).
    note: подсказка (тоже локализуемая).
    tile_format: 'png' | 'jpeg' — формат тайлов сервера.
    """

    id: str
    name: str
    url_template: str
    tile_format: str
    backup_url_template: str | None = None
    note: str = ""


_SOURCE_NOTE_OPENTOPO = "Рельеф и высоты; основной сервер иногда перегружен"
_SOURCE_NOTE_ESRI = "Контуры и холмшейдинг"
_SOURCE_NOTE_OSM = "Стандартная схема, без рельефа"

TILE_SOURCES: dict[str, TileSource] = {
    "opentopomap": TileSource(
        id="opentopomap",
        name="OpenTopoMap (рельеф)",
        url_template=OPENTOPOMAP_TEMPLATE,
        tile_format="png",
        backup_url_template=OPENTOPOMAP_BACKUP_TEMPLATE,
        note=_SOURCE_NOTE_OPENTOPO,
    ),
    "esri_topo": TileSource(
        id="esri_topo",
        name="Esri World Topo",
        url_template=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Topo_Map/MapServer/tile/{z}/{y}/{x}"
        ),
        tile_format="jpeg",
        note=_SOURCE_NOTE_ESRI,
    ),
    "osm": TileSource(
        id="osm",
        name="OpenStreetMap",
        url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        tile_format="png",
        note=_SOURCE_NOTE_OSM,
    ),
}

DEFAULT_SOURCE_ID = "opentopomap"


def default_source_id() -> str:
    """Идентификатор источника по умолчанию (OpenTopoMap)."""
    return DEFAULT_SOURCE_ID


def get_source(source_id: str | None) -> TileSource:
    """Возвращает TileSource по id; неизвестный/пустой id — источник по умолчанию."""
    return TILE_SOURCES.get(source_id or "", TILE_SOURCES[default_source_id()])


def source_format(source_id: str | None) -> str:
    """Формат тайлов ('png'/'jpeg') источника по id."""
    return get_source(source_id).tile_format
