"""Чистый парсер JSON-пакетов LoRa-приёмника.

Устройство печатает по одной JSON-строке на принятый пакет:

    {"device_id":1,"lat":54.211205,"lon":45.158203,"alt":168,
     "datetime":"2026-09-16T12:01:00","sos":0,"battery_pct":100,
     "battery_mv":4150,"rssi":"-27.00dBm","snr":"5.25dB","ttl":3,"crc":241}

Не имеет зависимостей Qt/serial, можно тестировать headless.
"""
import json
import re
from datetime import datetime, timezone


def _to_float(value) -> float | None:
    """Приводит число или строку вида '-27.00dBm' к float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r'[-+]?\d+(?:\.\d+)?', str(value))
    return float(m.group()) if m else None


def _to_int(value) -> int | None:
    """Приводит число или строку к int (None при ошибке)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_packet(line: str) -> dict | None:
    """Парсит JSON-строку пакета в dict формата приложения.

    Позиционный пакет (есть device_id/lat/lon) даёт полный dict;
    телеметрия без координат (есть только device_id, напр. status с
    battery_pct при выключенном GPS) — dict без lat/lon/altitude.
    Возвращает None, если строка не JSON-объект или в ней нет device_id.
    """
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    if "device_id" not in obj:
        return None

    params: dict = {}

    device_id = obj.get("device_id")
    if device_id is not None:
        params["id"] = str(device_id)

    for src, dst in (
        ("lat", "lat"),
        ("lon", "lon"),
        ("alt", "altitude"),
        ("battery_pct", "batt"),
        ("battery_mv", "voltage"),
    ):
        value = _to_float(obj.get(src))
        if value is not None:
            params[dst] = value

    sos = _to_int(obj.get("sos"))
    if sos is not None:
        params["sos"] = sos

    for src in ("ttl", "crc"):
        value = _to_int(obj.get(src))
        if value is not None:
            params[src] = value

    for src in ("rssi", "snr"):
        value = _to_float(obj.get(src))
        if value is not None:
            params[src] = value

    dt_str = obj.get("datetime")
    if dt_str:
        try:
            dt = datetime.strptime(str(dt_str), '%Y-%m-%dT%H:%M:%S')
            params["timestamp"] = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            params["device_ts"] = dt.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            params["timestamp"] = 'N/A'

    return params


def parse_queue_size(line: str) -> int | None:
    """Извлекает размер очереди из строки (None если не совпадает)."""
    m = re.search(r'Queue size:\s+(\d+)', line)
    return int(m.group(1)) if m else None


def is_valid_position(params: dict) -> bool:
    """Базовая проверка диапазонов (lat −90..90, lon −180..180, alt 0..10000)."""
    try:
        lat = float(params.get('lat', ''))
        lon = float(params.get('lon', ''))
    except (TypeError, ValueError):
        return False
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return False
    try:
        alt = float(params.get('altitude', '0'))
        if not (0.0 <= alt <= 10000.0):
            return False
    except (TypeError, ValueError):
        pass  # alt опционален
    return 'id' in params
