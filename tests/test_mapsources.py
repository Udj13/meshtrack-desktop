"""Тесты meshtrack/mapsources.py (реестр источников тайлов)."""

from meshtrack.mapsources import (
    OPENTOPOMAP_BACKUP_TEMPLATE,
    TILE_SOURCES,
    default_source_id,
    get_source,
    source_format,
)


def test_default_source_is_opentopomap():
    assert default_source_id() == "opentopomap"
    assert get_source(None).id == "opentopomap"
    assert get_source("").id == "opentopomap"


def test_unknown_source_falls_back_to_default():
    assert get_source("nope").id == "opentopomap"


def test_opentopomap_has_backup():
    src = get_source("opentopomap")
    assert src.tile_format == "png"
    assert src.backup_url_template == OPENTOPOMAP_BACKUP_TEMPLATE


def test_esri_is_jpeg_without_backup():
    src = get_source("esri_topo")
    assert src.tile_format == "jpeg"
    assert src.backup_url_template is None
    assert "{z}/{y}/{x}" in src.url_template


def test_osm_is_png():
    assert get_source("osm").tile_format == "png"
    assert get_source("osm").backup_url_template is None


def test_source_format_helper():
    assert source_format("esri_topo") == "jpeg"
    assert source_format(None) == "png"
    assert source_format("osm") == "png"


def test_all_sources_have_unique_ids():
    ids = [s.id for s in TILE_SOURCES.values()]
    assert len(ids) == len(set(ids)) == len(TILE_SOURCES)
