"""Тесты meshtrack/map_manager.py (headless)."""
from pathlib import Path

import pytest

from meshtrack.map_manager import (
    CORRUPTED,
    DOWNLOADED,
    MISSING,
    NOT_DOWNLOADED,
    ORPHAN,
    PARTIAL,
    delete_map,
    delete_map_file,
    map_bbox,
    scan_maps,
)
from meshtrack.mapstore import MapStore
from meshtrack.settings import Settings


def _make_mbtiles(path: Path, complete: bool = True, zmin: int = 9, zmax: int = 15) -> MapStore:
    store = MapStore(path)
    store.set_metadata("name", path.stem)
    store.set_metadata("format", "png")
    store.set_metadata("bbox", "54.0,54.1,45.0,45.1")
    store.set_metadata("tile_count_expected", "10")
    if complete:
        store.set_metadata("complete", "1")
    store.set_minmax_zoom(zmin, zmax)
    store.insert(zmin, 1, 1, b"tile-data")
    return store


def _corrupt(path: Path) -> None:
    path.write_bytes(b"this is not a sqlite database")


def test_scan_config_downloaded(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    file = maps_dir / "lyambir.mbtiles"
    _make_mbtiles(file)

    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("lyambir", "Лямбирь", str(file))
    cfg.save()

    entries = scan_maps(cfg, maps_dir)
    entry = next(e for e in entries if e.map_id == "lyambir")
    assert entry.source == "config"
    assert entry.status == DOWNLOADED
    assert entry.exists is True
    assert entry.complete is True
    assert entry.tile_count == 1
    assert entry.tile_count_expected == 10
    assert entry.bbox == (54.0, 54.1, 45.0, 45.1)
    assert entry.zmin == 9
    assert entry.zmax == 15


def test_scan_partial(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    file = maps_dir / "partial.mbtiles"
    _make_mbtiles(file, complete=False)

    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("partial", "Частичная", str(file))

    entry = next(e for e in scan_maps(cfg, maps_dir) if e.map_id == "partial")
    assert entry.status == PARTIAL
    assert entry.complete is False


def test_scan_missing(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("gone", "Нет файла", str(maps_dir / "gone.mbtiles"))

    entry = next(e for e in scan_maps(cfg, maps_dir) if e.map_id == "gone")
    assert entry.status == MISSING
    assert entry.exists is False


def test_scan_corrupted(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    file = maps_dir / "bad.mbtiles"
    _corrupt(file)
    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("bad", "Битая", str(file))

    entry = next(e for e in scan_maps(cfg, maps_dir) if e.map_id == "bad")
    assert entry.status == CORRUPTED
    assert entry.exists is True


def test_scan_orphan(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    file = maps_dir / "stray.mbtiles"
    _make_mbtiles(file)

    cfg = Settings(tmp_path / "config.json")
    entry = next(e for e in scan_maps(cfg, maps_dir) if e.map_id == "stray")
    assert entry.source == "disk"
    assert entry.status == ORPHAN
    assert entry.exists is True


def test_scan_prebuilt_not_downloaded(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    cfg = Settings(tmp_path / "config.json")

    entry = next(
        e for e in scan_maps(cfg, maps_dir) if e.map_id == "lyambir_airfield"
    )
    assert entry.source == "prebuilt"
    assert entry.status == NOT_DOWNLOADED
    assert entry.exists is False


def test_scan_prebuilt_with_file(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    file = maps_dir / "lyambir_airfield.mbtiles"
    _make_mbtiles(file)

    cfg = Settings(tmp_path / "config.json")
    entry = next(
        e for e in scan_maps(cfg, maps_dir) if e.map_id == "lyambir_airfield"
    )
    assert entry.source == "prebuilt"
    assert entry.status == DOWNLOADED


def test_scan_dedup_config_and_disk(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    file = maps_dir / "same.mbtiles"
    _make_mbtiles(file)

    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("same", "Одна и та же", str(file))

    ids = [e.map_id for e in scan_maps(cfg, maps_dir)]
    assert ids.count("same") == 1


def test_map_bbox_from_metadata(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    file = maps_dir / "a.mbtiles"
    _make_mbtiles(file)
    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("a", "A", str(file))
    entry = scan_maps(cfg, maps_dir)[0]
    assert map_bbox(entry) == (54.0, 54.1, 45.0, 45.1)


def test_map_bbox_from_config(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    cfg = Settings(tmp_path / "config.json")
    cfg.add_map(
        "custom",
        "Кастом",
        str(maps_dir / "custom.mbtiles"),
        south=54.0,
        north=54.1,
        west=45.0,
        east=45.1,
    )
    entry = next(e for e in scan_maps(cfg, maps_dir) if e.map_id == "custom")
    assert map_bbox(entry) == (54.0, 54.1, 45.0, 45.1)


def test_delete_map_file_with_sidecars(tmp_path: Path):
    file = tmp_path / "map.mbtiles"
    _make_mbtiles(file)
    wal = Path(f"{file}-wal")
    shm = Path(f"{file}-shm")
    wal.write_bytes(b"w")
    shm.write_bytes(b"s")

    delete_map_file(file)
    assert not file.exists()
    assert not wal.exists()
    assert not shm.exists()


def test_delete_map_not_active(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    a = maps_dir / "a.mbtiles"
    b = maps_dir / "b.mbtiles"
    _make_mbtiles(a)
    _make_mbtiles(b)

    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("a", "A", str(a))
    cfg.add_map("b", "B", str(b))
    cfg.active_map_id = "b"
    cfg.save()

    new_active = delete_map(cfg, "a")
    assert new_active == "b"
    assert not a.exists()
    assert cfg.active_map_id == "b"
    assert cfg.get_map_path("a") is None

    cfg2 = Settings(cfg.path)
    assert cfg2.get_map_path("a") is None


def test_delete_map_active_switches(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    a = maps_dir / "a.mbtiles"
    b = maps_dir / "b.mbtiles"
    _make_mbtiles(a)
    _make_mbtiles(b)

    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("a", "A", str(a))
    cfg.add_map("b", "B", str(b))
    cfg.active_map_id = "a"
    cfg.save()

    new_active = delete_map(cfg, "a")
    assert new_active == "b"
    assert not a.exists()
    assert cfg.active_map_id == "b"


def test_delete_map_active_last_becomes_none(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    a = maps_dir / "a.mbtiles"
    _make_mbtiles(a)

    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("a", "A", str(a))
    cfg.active_map_id = "a"
    cfg.save()

    new_active = delete_map(cfg, "a")
    assert new_active is None
    assert not a.exists()
    assert cfg.active_map_id is None


def test_delete_map_skips_missing_file(tmp_path: Path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    b = maps_dir / "b.mbtiles"
    _make_mbtiles(b)

    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("gone", "Нет файла", str(maps_dir / "gone.mbtiles"))
    cfg.add_map("b", "B", str(b))
    cfg.active_map_id = "gone"
    cfg.save()

    new_active = delete_map(cfg, "gone")
    assert new_active == "b"
    assert cfg.active_map_id == "b"