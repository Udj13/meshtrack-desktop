"""Данные о сторонних компонентах и их лицензиях (для диалога «Лицензии»).

Полные тексты лицензий лежат в assets/licenses/ и входят в поставку.
"""
import platform
from importlib import metadata
from pathlib import Path


def installed_version(dist_name: str, fallback: str) -> str:
    """Версия установленного пакета; fallback — для собранного приложения."""
    try:
        return metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        return fallback


COMPONENTS = [
    {
        "name": "PySide6 / Qt 6 (вкл. QtWebEngine)",
        "version": installed_version("PySide6", "6.9.3"),
        "license": "LGPL-3.0 (либо GPL-2.0/GPL-3.0)",
        "copyright": "The Qt Company Ltd. и участники проекта Qt",
        "url": "https://www.qt.io",
        "files": ["lgpl-3.0.txt"],
    },
    {
        "name": "requests",
        "version": installed_version("requests", "2.34.2"),
        "license": "Apache-2.0",
        "copyright": "© Kenneth Reitz и участники; © Python Software Foundation",
        "url": "https://requests.readthedocs.io",
        "files": ["apache-2.0.txt"],
    },
    {
        "name": "pyserial",
        "version": installed_version("pyserial", "3.5"),
        "license": "BSD-3-Clause",
        "copyright": "© 2001-2020 Chris Liechti",
        "url": "https://github.com/pyserial/pyserial",
        "files": ["bsd-3-clause.txt"],
    },
    {
        "name": "Leaflet",
        "version": "1.9.4",
        "license": "BSD-2-Clause",
        "copyright": "© 2010-2023 Volodymyr Agafonkin; © 2010-2011 CloudMade",
        "url": "https://leafletjs.com",
        "files": ["bsd-2-clause.txt"],
    },
    {
        "name": "Python",
        "version": platform.python_version(),
        "license": "PSF-2.0",
        "copyright": "© Python Software Foundation",
        "url": "https://www.python.org",
        "files": ["psf-2.0.txt"],
    },
    {
        "name": "PyInstaller (только сборка)",
        "version": installed_version("PyInstaller", "6.22.2"),
        "license": "GPL-2.0-or-later + исключение для загрузчика",
        "copyright": "© Hartmut Goebel и участники проекта PyInstaller",
        "url": "https://pyinstaller.org",
        "files": ["gpl-2.0.txt"],
        "note": (
            "PyInstaller используется только на этапе сборки дистрибутива; "
            "в приложение его код не входит. К лицензии GPL-2.0 применяется "
            "специальное исключение для загрузчика (bootloader exception), "
            "разрешающее распространение собранных приложений."
        ),
    },
    {
        "name": "Данные карт: OpenStreetMap / OpenTopoMap",
        "version": "—",
        "license": "ODbL-1.0 / CC-BY-SA-3.0",
        "copyright": "© участники OpenStreetMap; © OpenTopoMap (CC-BY-SA)",
        "url": "https://www.openstreetmap.org/copyright",
        "files": ["odbl-1.0.txt", "cc-by-sa-3.0.txt"],
        "note": (
            "Данные OpenStreetMap распространяются по лицензии ODbL-1.0, "
            "растровые тайлы OpenTopoMap — по CC-BY-SA-3.0. Атрибуция также "
            "отображается на карте в правом нижнем углу."
        ),
    },
]


def licenses_dir() -> Path:
    """Каталог с полными текстами лицензий (assets/licenses)."""
    return Path(__file__).resolve().parent.parent / "assets" / "licenses"


def load_license_text(filename: str) -> str:
    """Содержимое файла лицензии."""
    return (licenses_dir() / filename).read_text(encoding="utf-8")