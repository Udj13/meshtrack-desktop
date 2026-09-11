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
