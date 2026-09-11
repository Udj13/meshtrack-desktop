"""Тесты meshtrack/mapstore.py (headless, без Qt)."""
from pathlib import Path

import pytest

from meshtrack.mapstore import MapStore


@pytest.fixture
def store(tmp_path: Path) -> MapStore:
    return MapStore(tmp_path / "test.mbtiles")


def test_creates_file(store: MapStore, tmp_path: Path):
    assert (tmp_path / "test.mbtiles").exists()


def test_insert_and_get(store: MapStore):
    data = b"\x89PNG\r\n\x1a\nfake"
    store.insert(10, 512, 256, data)
    assert store.get(10, 512, 256) == data


def test_xyz_tms_conversion(store: MapStore):
    # MBTiles хранит tile_row в TMS. Для z=1, y_xyz=0 -> row=1.
    store.insert(1, 0, 0, b"top")
    store.insert(1, 0, 1, b"bottom")
    assert store.get(1, 0, 0) == b"top"
    assert store.get(1, 0, 1) == b"bottom"


def test_insert_many(store: MapStore):
    tiles = [(5, x, y, bytes([x, y])) for x in range(4) for y in range(4)]
    count = store.insert_many(tiles)
    assert count == 16
    assert store.count() == 16


def test_get_missing_returns_none(store: MapStore):
    assert store.get(0, 0, 0) is None


def test_metadata(store: MapStore):
    store.set_metadata("name", "test")
    store.set_metadata("format", "png")
    assert store.get_metadata("name") == "test"
    assert store.get_metadata("format") == "png"
    assert store.get_metadata("missing") is None


def test_verify_ok(store: MapStore):
    store.insert(10, 1, 1, b"tile")
    report = store.verify()
    assert report["ok"] is True
    assert report["tile_count"] == 1
    assert report["errors"] == []


def test_verify_invalid_file(tmp_path: Path):
    bad = tmp_path / "bad.mbtiles"
    bad.write_bytes(b"not sqlite")
    store = MapStore(bad)
    report = store.verify()
    assert report["ok"] is False
    assert report["errors"]


def test_list_tiles_xyz(store: MapStore):
    store.insert(2, 1, 2, b"a")
    store.insert(2, 3, 1, b"b")
    tiles = store.list_tiles(2)
    assert (2, 1, 2) in tiles
    assert (2, 3, 1) in tiles


def test_minmax_zoom_from_metadata(store: MapStore):
    store.set_minmax_zoom(10, 14)
    assert store.get_minmax_zoom() == (10, 14)


def test_minmax_zoom_fallback_to_tiles(store: MapStore):
    store.insert(10, 1, 1, b"a")
    store.insert(12, 1, 1, b"b")
    assert store.get_minmax_zoom() == (10, 12)


def test_minmax_zoom_default_when_empty(store: MapStore):
    assert store.get_minmax_zoom(default_zmin=5, default_zmax=20) == (5, 20)
