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
