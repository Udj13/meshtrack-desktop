"""Тесты данных о лицензиях и файлов с текстами (без GUI)."""
import pytest

from meshtrack import licenses
from meshtrack.licenses import COMPONENTS, licenses_dir, load_license_text


def test_components_non_empty():
    assert len(COMPONENTS) >= 6


def test_component_fields():
    for comp in COMPONENTS:
        assert comp["name"]
        assert comp["version"]
        assert comp["license"]
        assert comp["copyright"]
        assert comp["url"].startswith("http")
        assert comp["files"]


def test_license_files_exist_and_nonempty():
    for comp in COMPONENTS:
        for filename in comp["files"]:
            path = licenses_dir() / filename
            assert path.is_file(), f"Файл лицензии отсутствует: {filename}"
            assert path.stat().st_size > 100, f"Файл лицензии пуст: {filename}"


def test_load_license_text():
    text = load_license_text("lgpl-3.0.txt")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text


def test_licenses_dir_location():
    assert licenses_dir().name == "licenses"
    assert licenses_dir().parent.name == "assets"


@pytest.mark.parametrize(
    "dist_name,fallback",
    [("PySide6", "6.9.3"), ("pyserial", "3.5"), ("requests", "2.34.2")],
)
def test_installed_version_resolves(dist_name, fallback):
    version = licenses.installed_version(dist_name, fallback)
    assert version.count(".") >= 1


def test_installed_version_fallback():
    assert licenses.installed_version("no-such-package-xyz", "0.0.0") == "0.0.0"