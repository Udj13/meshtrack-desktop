"""Тесты meshtrack/mapscheme.py (headless, только парсинг URL)."""
from meshtrack.mapscheme import TRANSPARENT_PNG, parse_map_url


def test_parse_map_url_ok():
    parsed = parse_map_url("map://lyambir_airfield/10/512/256.png")
    assert parsed == ("lyambir_airfield", 10, 512, 256)


def test_parse_map_url_invalid():
    assert parse_map_url("https://example.com/tile.png") is None
    assert parse_map_url("map://region/10/512.png") is None
    assert parse_map_url("map://region/a/b/c.png") is None


def test_transparent_png_is_valid_png():
    assert TRANSPARENT_PNG[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(TRANSPARENT_PNG) > 0
