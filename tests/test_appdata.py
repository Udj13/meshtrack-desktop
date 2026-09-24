"""Тесты определения каталога данных приложения (app_data_dir, без GUI)."""

import platform
from pathlib import Path

from meshtrack.app import app_data_dir


def _set_home(monkeypatch, system, home):
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(Path, "home", lambda: Path(home))


def _assert_eq(path, expected):
    # Сравниваем в POSIX-представлении: на macOS/Linux Windows-пути содержат
    # обратные слэши как литералы, и Path('C:\\…') != Path('C:/…').
    def norm(p):
        return Path(p).as_posix().replace("\\", "/")

    assert norm(path) == norm(expected)


def test_linux_uses_xdg_path(monkeypatch):
    _set_home(monkeypatch, "Linux", "/home/pilot")
    _assert_eq(app_data_dir(), "/home/pilot/.local/share/MeshTrack")


def test_macos_uses_library(monkeypatch):
    _set_home(monkeypatch, "Darwin", "/Users/pilot")
    _assert_eq(app_data_dir(), "/Users/pilot/Library/Application Support/MeshTrack")


def test_windows_uses_appdata(monkeypatch):
    _set_home(monkeypatch, "Windows", "C:\\Users\\pilot")
    monkeypatch.setenv("APPDATA", "C:\\Users\\pilot\\AppData\\Roaming")
    _assert_eq(app_data_dir(), "C:/Users/pilot/AppData/Roaming/MeshTrack")


def test_windows_falls_back_to_home(monkeypatch):
    _set_home(monkeypatch, "Windows", "C:\\Users\\pilot")
    monkeypatch.delenv("APPDATA", raising=False)
    _assert_eq(app_data_dir(), "C:/Users/pilot/MeshTrack")


def test_other_platform_uses_xdg(monkeypatch):
    _set_home(monkeypatch, "FreeBSD", "/home/pilot")
    _assert_eq(app_data_dir(), "/home/pilot/.local/share/MeshTrack")
