"""Тесты meshtrack/regions.py (headless)."""
import pytest

from meshtrack import regions
from meshtrack.regions import (
    Region,
    bbox_around_point,
    make_region_id,
    normalize_bbox,
    validate_bbox,
)


def test_list_prebuilt_not_empty():
    lst = regions.list_prebuilt()
    assert len(lst) >= 3
    ids = {r.id for r in lst}
    assert "lyambir_airfield" in ids
    assert "napolnaya_tavla" in ids
    assert "mordovia_lyambir" not in ids


def test_get_prebuilt():
    r = regions.get_prebuilt("lyambir_airfield")
    assert r is not None
    assert r.south < r.north
    assert r.west < r.east
    # Радиус ~15 км от аэродрома Лямбирь
    assert r.north - r.south > 0.25
    assert r.east - r.west > 0.4


def test_get_prebuilt_missing():
    assert regions.get_prebuilt("no_such") is None


def test_validate_bbox_ok():
    ok, msg = validate_bbox(54.0, 55.0, 44.0, 46.0)
    assert ok is True
    assert msg == ""


def test_validate_bbox_lat_out_of_range():
    ok, _ = validate_bbox(-95.0, 55.0, 44.0, 46.0)
    assert ok is False


def test_validate_bbox_inverted():
    ok, _ = validate_bbox(55.0, 54.0, 44.0, 46.0)
    assert ok is False
    ok, _ = validate_bbox(54.0, 55.0, 46.0, 44.0)
    assert ok is False


def test_validate_bbox_too_large():
    ok, _ = validate_bbox(50.0, 65.0, 40.0, 41.0)
    assert ok is False


def test_normalize_bbox():
    assert normalize_bbox(55.0, 54.0, 46.0, 44.0) == (54.0, 55.0, 44.0, 46.0)


def test_make_region_id():
    assert make_region_id("Hello World!") == "hello_world"
    assert make_region_id("   ") == "custom"


def test_region_as_dict():
    r = Region("x", "X", 1, 2, 3, 4)
    assert r.as_dict()["id"] == "x"
    assert r.bbox == (1, 2, 3, 4)


def test_bbox_around_point():
    south, north, west, east = bbox_around_point(54.0, 45.0, 15.0)
    assert south < north
    assert west < east
    # 15 км ~ 0.135° широты
    assert round(north - south, 3) == 0.270
    # 15 км ~ 0.23° долготы на 54° с.ш.
    assert east - west > 0.4


def test_region_from_dict():
    r = regions.region_from_dict(
        {"id": "foo", "name": "Foo", "south": 1, "north": 2, "west": 3, "east": 4}
    )
    assert r.id == "foo"
    assert r.name == "Foo"
    assert r.bbox == (1.0, 2.0, 3.0, 4.0)
