"""Тесты meshtrack/settings.py (headless)."""
import json
from pathlib import Path

import pytest

from meshtrack.settings import DEFAULT_CONFIG, Settings


def test_defaults_when_file_missing(tmp_path: Path):
    cfg = Settings(tmp_path / "nonexistent.json")
    assert cfg.retention_days == 90
    assert cfg.track_color_mode == "palette"


def test_save_and_load(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = Settings(path)
    cfg.retention_days = 30
    cfg.track_color_mode = "vario"
    cfg.save()

    cfg2 = Settings(path)
    assert cfg2.retention_days == 30
    assert cfg2.track_color_mode == "vario"


def test_invalid_color_mode_normalized(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"track_color_mode": "invalid"}), encoding="utf-8")
    cfg = Settings(path)
    assert cfg.track_color_mode == "palette"


def test_invalid_retention_normalized(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"retention_days": "abc"}), encoding="utf-8")
    cfg = Settings(path)
    assert cfg.retention_days == 90


def test_phase5_defaults(tmp_path: Path):
    cfg = Settings(tmp_path / "nonexistent.json")
    assert cfg.traccar_on is False
    assert cfg.port_pref == ""
    assert cfg.baud == 115200
    assert cfg.exports_dir == ""


def test_phase5_roundtrip(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = Settings(path)
    cfg.traccar_on = True
    cfg.port_pref = "/dev/tty.usbserial"
    cfg.baud = 57600
    cfg.exports_dir = "/tmp/exports"
    cfg.save()

    cfg2 = Settings(path)
    assert cfg2.traccar_on is True
    assert cfg2.port_pref == "/dev/tty.usbserial"
    assert cfg2.baud == 57600
    assert cfg2.exports_dir == "/tmp/exports"


def test_phase5_invalid_baud_normalized(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"baud": "abc", "traccar_on": 1, "port_pref": 5}),
                    encoding="utf-8")
    cfg = Settings(path)
    assert cfg.baud == 115200
    assert cfg.traccar_on is True
    assert cfg.port_pref == ""


def test_language_default(tmp_path: Path):
    cfg = Settings(tmp_path / "nonexistent.json")
    assert cfg.language == "ru"


def test_language_roundtrip(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = Settings(path)
    cfg.language = "en"
    cfg.save()

    cfg2 = Settings(path)
    assert cfg2.language == "en"


def test_invalid_language_normalized(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"language": "de"}), encoding="utf-8")
    cfg = Settings(path)
    assert cfg.language == "ru"


def test_new_config_uses_default_language_hint(tmp_path: Path):
    cfg = Settings(tmp_path / "nonexistent.json", default_language="en")
    assert cfg.language == "en"


def test_existing_config_ignores_language_hint(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"language": "ru"}), encoding="utf-8")
    cfg = Settings(path, default_language="en")
    assert cfg.language == "ru"


def test_invalid_default_language_hint_falls_back_to_ru(tmp_path: Path):
    cfg = Settings(tmp_path / "nonexistent.json", default_language="de")
    assert cfg.language == "ru"


def test_maps_roundtrip(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = Settings(path)
    assert cfg.has_maps is False
    assert cfg.default_map_id() is None

    cfg.add_map("mordovia", "Мордовия", "/tmp/mordovia.mbtiles")
    assert cfg.has_maps is True
    assert cfg.default_map_id() == "mordovia"
    assert cfg.get_map_path("mordovia") == "/tmp/mordovia.mbtiles"
    cfg.save()

    cfg2 = Settings(path)
    assert cfg2.default_map_id() == "mordovia"
    assert cfg2.get_map_path("mordovia") == "/tmp/mordovia.mbtiles"


def test_remove_map(tmp_path: Path):
    cfg = Settings(tmp_path / "c.json")
    cfg.add_map("a", "A", "/a.mbtiles")
    cfg.add_map("b", "B", "/b.mbtiles")
    cfg.active_map_id = "b"
    assert cfg.remove_map("a") is True
    assert cfg.default_map_id() == "b"
    assert cfg.remove_map("a") is False


def test_add_map_with_bbox_and_zooms(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = Settings(path)
    cfg.add_map(
        "custom",
        "Кастом",
        "/tmp/custom.mbtiles",
        south=54.0,
        north=54.1,
        west=45.0,
        east=45.1,
        zmin=10,
        zmax=12,
    )
    cfg.save()

    cfg2 = Settings(path)
    m = cfg2.maps[0]
    assert m["south"] == 54.0
    assert m["north"] == 54.1
    assert m["west"] == 45.0
    assert m["east"] == 45.1
    assert m["zmin"] == 10
    assert m["zmax"] == 12


def test_add_map_without_extra_fields(tmp_path: Path):
    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("mordovia", "Мордовия", "/tmp/mordovia.mbtiles")
    m = cfg.maps[0]
    assert set(m) == {"id", "name", "path"}


def test_add_map_updates_extra_fields(tmp_path: Path):
    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("m", "M", "/m.mbtiles", south=54.0, zmin=9)
    cfg.add_map("m", "M", "/m.mbtiles", east=46.0, zmax=13)
    m = cfg.maps[0]
    assert m["south"] == 54.0
    assert m["east"] == 46.0
    assert m["zmin"] == 9
    assert m["zmax"] == 13


def test_first_existing_map_id(tmp_path: Path):
    cfg = Settings(tmp_path / "config.json")
    existing = tmp_path / "existing.mbtiles"
    existing.write_bytes(b"x")
    cfg.add_map("missing", "Нет файла", str(tmp_path / "nope.mbtiles"))
    cfg.add_map("present", "Есть файл", str(existing))
    assert cfg.first_existing_map_id() == "present"


def test_first_existing_map_id_none(tmp_path: Path):
    cfg = Settings(tmp_path / "config.json")
    cfg.add_map("missing", "Нет файла", str(tmp_path / "nope.mbtiles"))
    assert cfg.first_existing_map_id() is None


def test_remove_active_map_switches_to_existing(tmp_path: Path):
    cfg = Settings(tmp_path / "config.json")
    existing = tmp_path / "existing.mbtiles"
    existing.write_bytes(b"x")
    cfg.add_map("a", "A", str(tmp_path / "a.mbtiles"))
    cfg.add_map("b", "B", str(existing))
    cfg.active_map_id = "a"
    cfg.remove_map("a")
    assert cfg.active_map_id == "b"
