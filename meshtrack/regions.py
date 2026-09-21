"""Регионы для офлайн-карт.

Содержит встроенные bbox по аэродромам (PROJECT.md §8) и утилиты для
пользовательских bbox.
"""
from __future__ import annotations

import math

from .i18n import tr as _


class Region:
    """Описание региона для скачивания карт."""

    def __init__(
        self,
        region_id: str,
        name: str,
        south: float,
        north: float,
        west: float,
        east: float,
    ):
        self.id = region_id
        self.name = name
        self.south = south
        self.north = north
        self.west = west
        self.east = east

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Возвращает (south, north, west, east)."""
        return (self.south, self.north, self.west, self.east)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "south": self.south,
            "north": self.north,
            "west": self.west,
            "east": self.east,
        }


def bbox_around_point(
    lat: float, lon: float, radius_km: float
) -> tuple[float, float, float, float]:
    """Возвращает bbox (south, north, west, east) вокруг точки с заданным радиусом.

    Радиус применяется приближённо: 1° широты ≈ 111 км, 1° долготы зависит от
    широты (111 км * cos(lat)).
    """
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(lat)))
    return (
        round(lat - dlat, 5),
        round(lat + dlat, 5),
        round(lon - dlon, 5),
        round(lon + dlon, 5),
    )


# Встроенные регионы (PROJECT.md §8).
PREBUILT_REGIONS: dict[str, Region] = {
    "lyambir_airfield": Region(
        "lyambir_airfield",
        "Мордовия — аэродром Лямбирь",
        *bbox_around_point(54.28777, 45.16604, 15.0),
    ),
    "napolnaya_tavla": Region(
        "napolnaya_tavla",
        "Мордовия — Напольная Тавла / Кочкурово / Семилей",
        *bbox_around_point(54.02010, 45.40830, 15.0),
    ),
    "innopolis": Region(
        "innopolis",
        "Татарстан — Иннополис, Свияжск, аэродром «Куралово»",
        *bbox_around_point(55.75208, 48.74461, 20.0),
    ),
    "penza_sosnovka": Region(
        "penza_sosnovka",
        "Пензенская обл. — аэродром Сосновка",
        52.25,
        52.95,
        44.55,
        45.55,
    ),
    "lenoblast_nikolskoe": Region(
        "lenoblast_nikolskoe",
        "Ленинградская обл. — аэродром Никольское",
        59.30,
        59.85,
        29.60,
        30.70,
    ),
}


def list_prebuilt() -> list[Region]:
    """Список встроенных регионов."""
    return list(PREBUILT_REGIONS.values())


def get_prebuilt(region_id: str) -> Region | None:
    """Возвращает встроенный регион по id или None."""
    return PREBUILT_REGIONS.get(region_id)


def make_region_id(name: str) -> str:
    """Генерирует безопасный id региона из пользовательского названия."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.strip().lower())
    return safe.strip("_") or "custom"


def validate_bbox(south: float, north: float, west: float, east: float) -> tuple[bool, str]:
    """Проверяет корректность bbox. Возвращает (ok, error_message)."""
    if not (-90.0 <= south <= 90.0) or not (-90.0 <= north <= 90.0):
        return False, _("Широта должна быть в диапазоне −90..90")
    if not (-180.0 <= west <= 180.0) or not (-180.0 <= east <= 180.0):
        return False, _("Долгота должна быть в диапазоне −180..180")
    if south >= north:
        return False, _("Южная граница должна быть меньше северной")
    if west >= east:
        return False, _("Западная граница должна быть меньше восточной")
    if north - south > 10.0:
        return False, _("Регион слишком велик (>10° по широте)")
    if east - west > 10.0:
        return False, _("Регион слишком велик (>10° по долготе)")
    return True, ""


def normalize_bbox(
    south: float, north: float, west: float, east: float
) -> tuple[float, float, float, float]:
    """Округляет и упорядочивает границы bbox."""
    return (
        min(south, north),
        max(south, north),
        min(west, east),
        max(west, east),
    )


def region_from_dict(data: dict) -> Region:
    """Создаёт Region из dict (например, из config.json)."""
    return Region(
        region_id=data["id"],
        name=data.get("name", data["id"]),
        south=float(data["south"]),
        north=float(data["north"]),
        west=float(data["west"]),
        east=float(data["east"]),
    )
