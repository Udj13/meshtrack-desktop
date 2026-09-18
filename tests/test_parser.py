"""Тесты parser.py — JSON-парсинг пакетов LoRa-приёмника."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meshtrack.parser import (
    is_valid_position,
    parse_packet,
    parse_queue_size,
)


SAMPLE_JSON = (
    '{"device_id":42,"lat":54.12345,"lon":45.67890,"alt":1230,'
    '"datetime":"2026-09-10T12:34:56","sos":0,"battery_pct":87,'
    '"battery_mv":4020,"rssi":"-27.00dBm","snr":"5.25dB","ttl":3,"crc":241}'
)


def test_parse_all_fields():
    p = parse_packet(SAMPLE_JSON)
    assert p["id"] == "42"
    assert p["lat"] == 54.12345
    assert p["lon"] == 45.67890
    assert p["altitude"] == 1230.0
    assert p["timestamp"] == "2026-09-10T12:34:56Z"
    assert p["device_ts"] == 1789043696.0
    assert p["sos"] == 0
    assert p["voltage"] == 4020.0
    assert p["batt"] == 87.0
    assert p["rssi"] == -27.0
    assert p["snr"] == 5.25
    assert p["ttl"] == 3
    assert p["crc"] == 241


def test_timestamp_normalized_id():
    p = parse_packet(SAMPLE_JSON)
    assert "datetime" not in p
    assert p["id"] == "42"


def test_partial_packet():
    p = parse_packet('{"device_id":7,"lat":1.23,"lon":4.56}')
    assert p["id"] == "7"
    assert p["lat"] == 1.23
    assert "timestamp" not in p
    assert "device_ts" not in p


def test_not_json_or_missing_fields():
    assert parse_packet("random line") is None
    assert parse_packet("Radio Received packet!") is None
    assert parse_packet("[1,2,3]") is None
    assert parse_packet('{"lat":1,"lon":2}') is None
    assert parse_packet("") is None


def test_parse_status_telemetry_no_position():
    """Status-пакет без лат/лона парсится как телеметрия (заряд, без позиции)."""
    line = (
        '{"type":"status","device_id":2297873940,"device_name":"Tracker 2",'
        '"portnum":67,"battery_pct":68,"battery_mv":3985,'
        '"rssi":"-36.00dBm","snr":"5.00dB","ttl":7,"uptime_s":312}'
    )
    p = parse_packet(line)
    assert p is not None
    assert p["id"] == "2297873940"
    assert p["batt"] == 68.0
    assert p["voltage"] == 3985.0
    assert p["rssi"] == -36.0
    assert p["snr"] == 5.0
    assert p["ttl"] == 7
    assert "lat" not in p
    assert "lon" not in p
    assert "altitude" not in p
    assert "timestamp" not in p


def test_parse_telemetry_requires_device_id():
    assert parse_packet('{"type":"status","portnum":67,"battery_pct":68}') is None
    assert parse_packet('{"battery_pct":68,"battery_mv":3985}') is None


def test_bad_datetime():
    p = parse_packet('{"device_id":1,"lat":1,"lon":2,"datetime":"garbage"}')
    assert p["timestamp"] == "N/A"
    assert "device_ts" not in p


def test_queue_size():
    assert parse_queue_size("Queue size: 42") == 42
    assert parse_queue_size("no queue") is None


def test_valid_position_bounds():
    good = {"id": "1", "lat": 54.4, "lon": 45.4, "altitude": 500}
    bad_lat = {"id": "1", "lat": 200, "lon": 45.4}
    bad_lon = {"id": "1", "lat": 54.4, "lon": -181}
    bad_alt = {"id": "1", "lat": 54.4, "lon": 45.4, "altitude": 50000}
    assert is_valid_position(good)
    assert not is_valid_position(bad_lat)
    assert not is_valid_position(bad_lon)
    assert not is_valid_position(bad_alt)


def test_fake_serial_sample_climb(tmp_path):
    """Интеграция fake_serial → parser (сценарий climb через tools)."""
    tools = Path(__file__).resolve().parent.parent / "tools"
    sys.path.insert(0, str(tools))
    from fake_serial import scenario_climb

    lines = list(scenario_climb(3))
    for line in lines:
        p = parse_packet(line)
        assert p is not None
        assert p["id"]
        assert p["lat"] and p["lon"]
        assert "altitude" in p