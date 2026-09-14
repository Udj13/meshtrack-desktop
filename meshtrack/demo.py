"""Демо-режим: моковые телеметрические данные без приёмника.

Подключается только при запуске `python -m meshtrack --demo` или при
переменной окружения `MESHTRACK_DEMO=1`; в обычном запуске не используется.
Отключение — запуск без флага/переменной.

`DemoWorker` повторяет интерфейс `SerialWorker` (сигналы position/raw_line/
error/queue_size, метод stop(), атрибут port), поэтому подключается к
MainWindow через те же обработчики.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from PySide6.QtCore import QThread, Signal

from .regions import get_prebuilt

# Базовая точка — окрестности аэродрома Лямбирь (как regions.lyambir_airfield)
BASE_LAT = 54.28777
BASE_LON = 45.16604

# Интервал между пакетами (сек).
TICK_S = 2.0

# Шаг точек при заполнении истории (сек).
SEED_STEP_S = 15.0

TRACKER_IDS = ("boon101", "boon102", "boon103", "boon104")

_BLOCK_TMPL = """Radio Received packet!
Device ID: {dev}
Latitude: {lat:.5f}
Longitude: {lon:.5f}
Altitude: {alt}
Date/Time: {dt}
SOS: {sos}
Battery Voltage: {volt}
Battery Level: {batt}%
Postfix: OK
Queue size: {q}
"""


def local_midnight(ts: float | None = None) -> float:
    """Локальная полночь для момента ts (unix)."""
    t = time.localtime(ts if ts is not None else time.time())
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def demo_base_point(settings) -> tuple[float, float]:
    """Центр активной встроенной карты, иначе — окрестности Лямбиря."""
    map_id = None
    if settings is not None:
        map_id = settings.active_map_id or settings.default_map_id()
    region = get_prebuilt(map_id) if map_id else None
    if region is not None:
        return (
            (region.south + region.north) / 2.0,
            (region.west + region.east) / 2.0,
        )
    return BASE_LAT, BASE_LON


def _offset(lat0: float, lon0: float, north_m: float, east_m: float) -> tuple[float, float]:
    cos_lat = math.cos(math.radians(lat0))
    return (
        lat0 + north_m / 111_320.0,
        lon0 + east_m / (111_320.0 * cos_lat),
    )


def _circle(
    lat0: float, lon0: float, radius_m: float, speed_kmh: float, t: float, t_ref: float
) -> tuple[float, float]:
    """Точка на окружности радиуса radius_m с путевой скоростью speed_kmh."""
    omega = (speed_kmh / 3.6) / radius_m
    ang = omega * (t - t_ref)
    cos_lat = math.cos(math.radians(lat0))
    return (
        lat0 + radius_m / 111_320.0 * math.cos(ang),
        lon0 + radius_m / (111_320.0 * cos_lat) * math.sin(ang),
    )


def _battery(t: float, t_ref: float, start: float = 92.0, drain_per_hour: float = 3.0) -> float:
    return max(15.0, min(100.0, start - (t - t_ref) / 3600.0 * drain_per_hour))


def position_at(
    tracker_id: str,
    t: float,
    t_ref: float,
    base_lat: float = BASE_LAT,
    base_lon: float = BASE_LON,
) -> dict:
    """Позиция трекера на момент t (unix) в формате парсера."""
    if tracker_id == "boon101":
        # «Термик»: круг 250 м на 45 км/ч, высота 650±350 м (период 8 мин)
        lat, lon = _circle(base_lat, base_lon, 250.0, 45.0, t, t_ref)
        alt = 650.0 + 350.0 * math.sin(2 * math.pi * (t - t_ref) / 480.0)
    elif tracker_id == "boon102":
        # «Маршрут»: круг 3 км в 3 км севернее, 70 км/ч, высота 1200±400 м
        clat, clon = _offset(base_lat, base_lon, 3000.0, 0.0)
        lat, lon = _circle(clat, clon, 3000.0, 70.0, t, t_ref)
        alt = 1200.0 + 400.0 * math.sin(2 * math.pi * (t - t_ref) / 900.0)
    elif tracker_id == "boon103":
        # «Набор»: спираль 120 м, набор +1.5 м/с (400…2200 м)
        slat, slon = _offset(base_lat, base_lon, -500.0, 500.0)
        lat, lon = _circle(slat, slon, 120.0, 35.0, t, t_ref)
        alt = 400.0 + ((t - t_ref) * 1.5) % 1800.0
    elif tracker_id == "boon104":
        # «На земле»: медленное движение по площадке (12 км/ч), периодический SOS
        lat, lon = _circle(base_lat, base_lon, 150.0, 12.0, t, t_ref)
        alt = 140.0
    else:
        raise KeyError(tracker_id)

    batt = _battery(t, t_ref)
    sos = 1 if tracker_id == "boon104" and (t - t_ref) % 180 < 20 else 0
    return {
        "id": tracker_id,
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "altitude": int(round(alt)),
        "timestamp": datetime.fromtimestamp(t, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "device_ts": float(int(t)),
        "sos": sos,
        "voltage": int(round(3550.0 + batt * 5.0)),
        "batt": int(round(batt)),
    }


def format_block(pos: dict, queue_size: int = 3) -> str:
    """Формирует legacy-текст пакета (для сигнала raw_line и лога)."""
    dt = datetime.fromtimestamp(pos["device_ts"], timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    return _BLOCK_TMPL.format(
        dev=pos["id"].removeprefix("boon"),
        lat=pos["lat"],
        lon=pos["lon"],
        alt=pos["altitude"],
        dt=dt,
        sos=pos["sos"],
        volt=pos["voltage"],
        batt=pos["batt"],
        q=queue_size,
    )


def seed_demo_history(
    repo,
    base_lat: float = BASE_LAT,
    base_lon: float = BASE_LON,
    now: float | None = None,
    tracker_ids: tuple[str, ...] = TRACKER_IDS,
) -> int:
    """Заполняет историю демо-полётами за вчера и сегодня.

    Идемпотентно: точки вставляются с ts из сценария, повторный вызов
    перезаписывает те же секунды (INSERT OR REPLACE). Возвращает число
    записанных точек; 0 — если свежая история уже есть.
    """
    now = float(now if now is not None else time.time())
    day0 = local_midnight(now)

    # Пропускаем, если в текущем дне уже есть свежие точки (например,
    # приложение перезапустили, а демо-история уже заполнена).
    try:
        recent = repo.points(
            tracker_ids[0], ts_from=max(day0, now - 300.0), ts_to=now
        )
    except Exception:
        recent = []
    if len(recent) >= 10:
        return 0

    flights = [
        (day0 - 86400 + 12 * 3600, day0 - 86400 + 13.5 * 3600),  # вчера
        (max(day0, now - 3 * 3600), now - 120),  # сегодня
    ]
    added = 0
    for start, end in flights:
        t = start
        while t < end:
            for tracker_id in tracker_ids:
                pos = position_at(tracker_id, t, day0, base_lat, base_lon)
                repo.add_position(
                    tracker_id=pos["id"],
                    lat=pos["lat"],
                    lon=pos["lon"],
                    alt=pos["altitude"],
                    batt=pos["batt"],
                    voltage=pos["voltage"],
                    sos=pos["sos"],
                    ts=pos["device_ts"],
                    recv_ts=pos["device_ts"],
                )
                added += 1
            t += SEED_STEP_S
    return added


class DemoWorker(QThread):
    """Эмулирует SerialWorker: генерирует поток моковых позиций."""

    position = Signal(dict)
    raw_line = Signal(str)
    error = Signal(str)
    queue_size = Signal(int)

    def __init__(
        self,
        base_lat: float = BASE_LAT,
        base_lon: float = BASE_LON,
        interval: float = TICK_S,
        parent=None,
    ):
        super().__init__(parent)
        self.port = "demo://"
        self.baud = 0
        self.base_lat = base_lat
        self.base_lon = base_lon
        self.interval = max(0.2, float(interval))
        self._running = False

    def run(self):
        self._running = True
        t_ref = local_midnight()
        tick = 0
        while self._running:
            now = time.time()
            queue_size = 2 + tick % 5
            for tracker_id in TRACKER_IDS:
                pos = position_at(
                    tracker_id, now, t_ref, self.base_lat, self.base_lon
                )
                for line in format_block(pos, queue_size).splitlines():
                    self.raw_line.emit(line)
                self.position.emit(pos)
            tick += 1
            if tick % 10 == 0:
                self.queue_size.emit(queue_size)

            slept = 0.0
            while self._running and slept < self.interval:
                time.sleep(0.05)
                slept += 0.05

    def stop(self):
        """Останавливает поток (аналог SerialWorker.stop)."""
        self._running = False
        self.wait(2000)
