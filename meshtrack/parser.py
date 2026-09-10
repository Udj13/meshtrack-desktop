"""Чистый парсер LoRa-пакетов (перенесён из main.py без изменений логики).

Не имеет зависимостей Qt/serial, можно тестировать headless.
"""
import re
from datetime import datetime

# Маркеры начала/конца блока данных (как в main.py)
START_MARKERS = ("Radio Received packet!",)
END_MARKERS = ("Postfix: OK", "Received valid LoRa data packet!")

_PATTERNS = {
    'id': r'Device ID:\s+(\d+)',
    'lat': r'Latitude:\s+([-\d.]+)',
    'lon': r'Longitude:\s+([-\d.]+)',
    'altitude': r'Altitude:\s+(\d+)',
    'datetime': r'Date/Time:\s+([\d-]+\s+[\d:]+)',
    'sos': r'SOS:\s+(\d+)',
    'voltage': r'Battery Voltage:\s+(\d+)',
    'batt': r'Battery Level:\s+(\d+)%',
}


def parse_data(data_block: str) -> dict:
    """Парсит блок и возвращает dict (id → 'boon{id}', timestamp ISO).

    Возвращает {} если ни одно поле не найдено.
    """
    params = {}
    for key, pat in _PATTERNS.items():
        m = re.search(pat, data_block)
        if m:
            params[key] = m.group(1)

    if 'datetime' in params:
        try:
            dt = datetime.strptime(params['datetime'], '%Y-%m-%d %H:%M:%S')
            params['timestamp'] = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            del params['datetime']
        except ValueError:
            params['timestamp'] = 'N/A'

    if 'id' in params:
        params['id'] = f"boon{params['id']}"

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


def is_start_marker(line: str) -> bool:
    return any(m in line for m in START_MARKERS)


def is_end_marker(line: str) -> bool:
    return any(m in line for m in END_MARKERS)
