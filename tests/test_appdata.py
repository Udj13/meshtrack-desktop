"""Тесты определения каталога данных приложения (app_data_dir, без GUI)."""

import platform
from pathlib import Path

from meshtrack.app import app_data_dir


def _set_home(monkeypatch, system, home):
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(Path, "home", lambda: Path(home))


def test_linux_uses_xdg_path(monkeypatch):
    _set_home(monkeypatch, "Linux", "/home/pilot")
    assert app_data_dir() == Path("/home/pilot/.local/share/MeshTrack")


def test_macos_uses_library(monkeypatch):
    _set_home(monkeypatch, "Darwin", "/Users/pilot")
    assert app_data_dir() == Path("/Users/pilot/Library/Application Support/MeshTrack")


def test_windows_uses_appdata(monkeypatch):
    _set_home(monkeypatch, "Windows", "C:\\Users\\pilot")
    monkeypatch.setenv("APPDATA", "C:\\Users\\pilot\\AppData\\Roaming")
    assert app_data_dir() == Path("C:/Users/pilot/AppData/Roaming/MeshTrack")


def test_windows_falls_back_to_home(monkeypatch):
    _set_home(monkeypatch, "Windows", "C:\\Users\\pilot")
    monkeypatch.delenv("APPDATA", raising=False)
    assert app_data_dir() == Path("C:/Users/pilot/MeshTrack")


def test_other_platform_uses_xdg(monkeypatch):
    _set_home(monkeypatch, "FreeBSD", "/home/pilot")
    assert app_data_dir() == Path("/home/pilot/.local/share/MeshTrack")
