"""Headless-логика управления офлайн-картами.

Чистый от Qt слой: сканирование карт, статусы, удаление.
Используется UI-диалогом (map_dialog.py) и приложением (app.py).
"""

from __future__ import annotations

import gc
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .mapstore import MapStore
from .regions import PREBUILT_REGIONS
from .settings import Settings

logger = logging.getLogger(__name__)

# Статусы карты:
# downloaded      — файл есть, complete=1
# partial         — файл есть, complete нет
# missing         — запись в конфиге есть, файла нет
# orphan          — файл на диске есть, записи в конфиге нет
# not_downloaded  — встроенный регион без файла
# corrupted       — файл есть, но не читается как MBTiles
DOWNLOADED = "downloaded"
PARTIAL = "partial"
MISSING = "missing"
ORPHAN = "orphan"
NOT_DOWNLOADED = "not_downloaded"
CORRUPTED = "corrupted"

# Источник записи:
# config    — есть в settings.maps
# disk      — найден на диске, в конфиге нет
# prebuilt  — встроенный регион
SOURCE_CONFIG = "config"
SOURCE_DISK = "disk"
SOURCE_PREBUILT = "prebuilt"


@dataclass
class MapEntry:
    map_id: str
    name: str
    path: str
    source: str
    status: str
    exists: bool = False
    size_bytes: int = 0
    tile_count: int = 0
    zmin: int | None = None
    zmax: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    tile_count_expected: int | None = None
    complete: bool = False
    extra: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"MapEntry({self.map_id!r}, status={self.status!r}, source={self.source!r})"
        )


def _parse_bbox(s: str | None) -> tuple[float, float, float, float] | None:
    if not s:
        return None
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        return None
    try:
        return tuple(float(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _read_metadata(path: Path) -> dict | None:
    """Читает метаданные MBTiles. Возвращает dict или None при ошибке."""
    try:
        store = MapStore(path)
        if store._invalid:
            return None
        meta = store.verify()
        if not meta["ok"]:
            return None
        m = meta["metadata"]
        zmin, zmax = store.get_minmax_zoom()
        bbox = _parse_bbox(m.get("bbox"))
        expected = m.get("tile_count_expected")
        try:
            expected_int = int(expected) if expected is not None else None
        except ValueError:
            expected_int = None
        return {
            "tile_count": meta["tile_count"],
            "zmin": zmin,
            "zmax": zmax,
            "bbox": bbox,
            "tile_count_expected": expected_int,
            "complete": m.get("complete") == "1",
        }
    except Exception:
        logger.exception("Не удалось прочитать метаданные %s", path)
        return None


def scan_maps(settings: Settings, maps_dir: str | Path) -> list[MapEntry]:
    """Собирает список карт из конфига, диска и встроенных регионов."""
    maps_dir = Path(maps_dir)
    entries: list[MapEntry] = []
    seen_ids: set[str] = set()

    config_maps = settings.maps

    # 1. Записи из конфига.
    for m in config_maps:
        map_id = m["id"]
        seen_ids.add(map_id)
        path = Path(m["path"])
        entries.append(
            _entry_from_config_or_disk(
                map_id=map_id,
                name=m.get("name", map_id),
                path=path,
                source=SOURCE_CONFIG,
                extra=m,
            )
        )

    # 2. Файлы на диске (включая sidecars не учитываем — только .mbtiles).
    if maps_dir.is_dir():
        for path in sorted(maps_dir.glob("*.mbtiles")):
            map_id = path.stem
            if map_id in seen_ids:
                continue
            seen_ids.add(map_id)
            prebuilt = PREBUILT_REGIONS.get(map_id)
            entries.append(
                _entry_from_config_or_disk(
                    map_id=map_id,
                    name=prebuilt.name if prebuilt else map_id,
                    path=path,
                    source=SOURCE_PREBUILT if prebuilt else SOURCE_DISK,
                    extra=(
                        {
                            "south": prebuilt.south,
                            "north": prebuilt.north,
                            "west": prebuilt.west,
                            "east": prebuilt.east,
                        }
                        if prebuilt
                        else {}
                    ),
                )
            )

    # 3. Встроенные регионы.
    for region_id, region in PREBUILT_REGIONS.items():
        if region_id in seen_ids:
            continue
        path = maps_dir / f"{region_id}.mbtiles"
        entries.append(
            _entry_from_config_or_disk(
                map_id=region_id,
                name=region.name,
                path=path,
                source=SOURCE_PREBUILT,
                extra={
                    "south": region.south,
                    "north": region.north,
                    "west": region.west,
                    "east": region.east,
                },
            )
        )

    return entries


def _entry_from_config_or_disk(
    map_id: str, name: str, path: Path, source: str, extra: dict
) -> MapEntry:
    exists = path.is_file()
    if not exists:
        if source == SOURCE_PREBUILT:
            status = NOT_DOWNLOADED
        else:
            status = MISSING
        return MapEntry(
            map_id=map_id,
            name=name,
            path=str(path),
            source=source,
            status=status,
            exists=False,
            extra=extra,
        )

    size_bytes = path.stat().st_size
    meta = _read_metadata(path)
    if meta is None:
        return MapEntry(
            map_id=map_id,
            name=name,
            path=str(path),
            source=source,
            status=CORRUPTED,
            exists=True,
            size_bytes=size_bytes,
            extra=extra,
        )

    if meta["complete"]:
        status = DOWNLOADED
    else:
        status = PARTIAL

    if source == SOURCE_DISK:
        status = ORPHAN

    return MapEntry(
        map_id=map_id,
        name=name,
        path=str(path),
        source=source,
        status=status,
        exists=True,
        size_bytes=size_bytes,
        tile_count=meta["tile_count"],
        zmin=meta["zmin"],
        zmax=meta["zmax"],
        bbox=meta["bbox"],
        tile_count_expected=meta["tile_count_expected"],
        complete=meta["complete"],
        extra=extra,
    )


def point_in_bbox(lat: float, lon: float, bbox) -> bool:
    """True, если точка (lat, lon) попадает в bbox (south, north, west, east).

    Границы включительны. bbox должен быть (south, north, west, east) с
    south <= north и west <= east; антимеридиан не обрабатывается (регионы
    MeshTrack далеко от ±180).
    """
    south, north, west, east = bbox
    return south <= lat <= north and west <= lon <= east


def map_summary(settings: Settings, maps_dir: str | Path) -> list[str]:
    """Однострочная сводка всех карт для лога на старте.

    Возвращает строки вида «id (name): status, file=<path>, tiles=N, z=N-N,
    bbox=(...)» для каждой карты + строку про активную карту. Не-существующие
    файлы помечаются как missing; встроенные регионы без файла — not_downloaded.
    Строк про активную карту нет, если активная не выбрана.
    """
    entries = scan_maps(settings, maps_dir)
    if not entries:
        return []

    lines: list[str] = []
    active_entry = None
    for entry in entries:
        if entry.map_id == settings.active_map_id:
            active_entry = entry
        parts = [f"{entry.map_id} ({entry.name})", f"status={entry.status}"]
        parts.append(f"file={entry.path}")
        if entry.exists:
            parts.append(f"tiles={entry.tile_count}")
            if entry.zmin is not None and entry.zmax is not None:
                parts.append(f"z={entry.zmin}-{entry.zmax}")
            bbox = map_bbox(entry)
            if bbox is not None:
                parts.append(f"bbox=({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]})")
        lines.append(", ".join(parts))

    if active_entry is not None:
        bbox = map_bbox(active_entry)
        active = f"Активная карта: {active_entry.map_id}"
        if bbox is not None:
            active += f", bbox=({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]})"
        lines.insert(0, active)
    return lines


def map_bbox(entry: MapEntry) -> tuple[float, float, float, float] | None:
    """bbox карты: из метаданных файла или из доп. полей (конфиг/регион)."""
    if entry.bbox is not None:
        return entry.bbox
    for key in ("south", "north", "west", "east"):
        if key not in entry.extra:
            return None
    try:
        return (
            float(entry.extra["south"]),
            float(entry.extra["north"]),
            float(entry.extra["west"]),
            float(entry.extra["east"]),
        )
    except (TypeError, ValueError):
        return None


def _release_wal_locks(path: Path) -> None:
    """WAL-checkpoint снимает файловые лока Windows на .mbtiles/-shm/-wal.

    SQLite в WAL-режиме оставляет открытыми handles на основной файл и
    sidecar-файлы даже после закрытия соединений; на Windows это блокирует
    unlink (WinError 32). TRUNCATE-checkpoint корректно финализирует WAL;
    удаление Python-обёртки sqlite3.Connection + gc обязательны, иначе
    handle остаётся закреплённым за объектом.
    """
    if not path.is_file():
        return
    try:
        conn = sqlite3.connect(path)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
        del conn
        gc.collect()
        time.sleep(0.1)
    except sqlite3.Error:
        pass
    except Exception:
        logger.exception("WAL-checkpoint не удался для %s", path)


def delete_map_file(path: str | Path) -> None:
    """Удаляет .mbtiles и sidecars (-wal, -shm) с ретраем для Windows."""
    path = Path(path)
    _release_wal_locks(path)
    targets = [path, Path(f"{path}-wal"), Path(f"{path}-shm")]
    for target in targets:
        for attempt in range(3):
            try:
                target.unlink()
                break
            except FileNotFoundError:
                break
            except OSError:
                if attempt == 2:
                    logger.warning("Не удалось удалить %s", target)
                else:
                    time.sleep(0.1)


def delete_map(settings: Settings, map_id: str) -> str | None:
    """Удаляет карту: файл, sidecars, запись из конфига.

    Если удаляемая карта была активной, выбирает новую активную среди
    оставшихся карт с существующим файлом. Возвращает новый active_map_id
    или None.
    """
    new_active = settings.active_map_id
    if settings.active_map_id == map_id:
        new_active = _first_other_existing_map_id(settings, map_id)
        settings.active_map_id = new_active

    path = settings.get_map_path(map_id)
    if path:
        delete_map_file(path)

    settings.remove_map(map_id)
    settings.save()
    return new_active


def _first_other_existing_map_id(settings: Settings, exclude: str) -> str | None:
    for m in settings.maps:
        if m.get("id") == exclude:
            continue
        path = m.get("path")
        if path and Path(path).is_file():
            return m.get("id")
    return None
