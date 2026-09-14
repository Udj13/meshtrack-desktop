"""Тесты parser.py — проверяют перенос логики из main.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meshtrack.parser import (
    is_end_marker,
    is_start_marker,
    is_valid_position,
    parse_data,
    parse_queue_size,
)


SAMPLE_BLOCK = """Device ID: 42
Latitude: 54.12345
Longitude: 45.67890
Altitude: 1230
Date/Time: 2026-09-10 12:34:56
SOS: 0
Battery Voltage: 4020
Battery Level: 87%
"""


def test_parse_all_fields():
    p = parse_data(SAMPLE_BLOCK)
    assert p["id"] == "boon42"
    assert p["lat"] == "54.12345"
    assert p["lon"] == "45.67890"
    assert p["altitude"] == "1230"
    assert p["timestamp"] == "2026-09-10T12:34:56Z"
    assert p["device_ts"] == 1789043696.0
    assert p["sos"] == "0"
    assert p["voltage"] == "4020"
    assert p["batt"] == "87"


def test_timestamp_normalized_id():
    p = parse_data(SAMPLE_BLOCK)
    assert "datetime" not in p
    assert p["id"].startswith("boon")


def test_partial_block():
    p = parse_data("Device ID: 7\nLatitude: 1.23\n")
    assert p["id"] == "boon7"
    assert p["lat"] == "1.23"
    assert "timestamp" not in p
    assert "device_ts" not in p


def test_empty_block():
    assert parse_data("") == {}
    assert not is_valid_position({})


def test_marker_checks():
    assert is_start_marker("Radio Received packet!")
    assert not is_start_marker("random line")
    assert is_end_marker("Postfix: OK")
    assert is_end_marker("Received valid LoRa data packet!")
    assert not is_end_marker("random")


def test_queue_size():
    assert parse_queue_size("Queue size: 42") == 42
    assert parse_queue_size("no queue") is None


def test_valid_position_bounds():
    good = {"id": "boon1", "lat": "54.4", "lon": "45.4", "altitude": "500"}
    bad_lat = {"id": "boon1", "lat": "200", "lon": "45.4"}
    bad_lon = {"id": "boon1", "lat": "54.4", "lon": "-181"}
    bad_alt = {"id": "boon1", "lat": "54.4", "lon": "45.4", "altitude": "50000"}
    assert is_valid_position(good)
    assert not is_valid_position(bad_lat)
    assert not is_valid_position(bad_lon)
    assert not is_valid_position(bad_alt)


def test_fake_serial_sample_climb(tmp_path):
    """Интеграция fake_serial → parser (сценарий climb через tools)."""
    tools = Path(__file__).resolve().parent.parent / "tools"
    sys.path.insert(0, str(tools))
    from fake_serial import scenario_climb

    blocks = "".join(scenario_climb(3))
    p = parse_data(blocks)
    # поля присутствуют (относятся к последнему найденному вхождению в блоке)
    assert p["id"].startswith("boon")
    assert p["lat"] and p["lon"]
    assert "altitude" in p
