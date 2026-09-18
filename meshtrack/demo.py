"""Демо-режим: моковые телеметрические данные без приёмника.

Подключается только при запуске `python -m meshtrack --demo` или при
переменной окружения `MESHTRACK_DEMO=1`; в обычном запуске не используется.
Отключение — запуск без флага/переменной.

`DemoWorker` повторяет интерфейс `SerialWorker` (сигналы position/telemetry/
raw_line/error/queue_size, метод stop(), атрибут port), поэтому подключается
к MainWindow через те же обработчики.

Моковые треки — реалистичные замкнутые маршруты (перегоны между точками +
короткие термики-круги набора), с плавно меняющейся высотой.
"""

from __future__ import annotations

import json
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

TRACKER_IDS = ("101", "102", "103", "104")

# Человекочитаемые имена для демо: планеры и параплан (как в реальном клубе).
TRACKER_NAMES = {
    "101": "АСК-21",
    "102": "Дискус",
    "103": "Бланик",
    "104": "Параплан",
}

# Демо-маршруты относительно базовой точки. Нога — ("go", north_м, east_м,
# высота_м, скорость_км/ч) — прямолинейный перегон между точками маршрута;
# термик — ("term", north_м, east_м, радиус_м, набор_м, кругов, скорость_км/ч) —
# короткие круги набора на термальной точке. Маршрут замкнут (последняя нога
# возвращает к старту), `start_alt` — высота старта/посадки.
TRACKS: dict[str, dict] = {
    "101": {
        "name": "АСК-21",
        "start_alt": 140.0,
        # «Коробочка» над аэродромом: взлёт, набор, по ветру, траверс, финальный.
        "plan": [
            ("go", 0, 1500, 320, 110),
            ("go", 2200, 1500, 340, 110),
            ("go", 2200, 0, 340, 100),
            ("go", 2200, -1100, 300, 95),
            ("go", 700, -1100, 210, 90),
            ("go", 0, 0, 140, 85),
        ],
    },
    "102": {
        "name": "Дискус",
        "start_alt": 200.0,
        # Треугольный маршрут: длинные перегоны и два термика набора (~1.2 м/с).
        "plan": [
            ("go", 1200, 2800, 560, 90),
            ("term", 1200, 3600, 180, 220, 2.5, 55),
            ("go", 4400, 2600, 620, 78),
            ("term", 5000, 2000, 200, 240, 2.5, 55),
            ("go", 2500, -800, 480, 85),
            ("term", 2000, -600, 150, 120, 1.5, 50),
            ("go", 0, 0, 200, 75),
        ],
    },
    "103": {
        "name": "Бланик",
        "start_alt": 160.0,
        # Дальний маршрут туда-обратно с термиками у разворотных точек.
        "plan": [
            ("go", 1500, 4200, 500, 95),
            ("term", 1900, 4400, 200, 260, 2.5, 55),
            ("go", 900, 6800, 560, 85),
            ("term", 700, 7600, 180, 300, 2.5, 55),
            ("go", -600, 4200, 500, 88),
            ("go", -200, 1600, 340, 82),
            ("go", 0, 0, 170, 78),
        ],
    },
    "104": {
        "name": "Параплан",
        "start_alt": 210.0,
        # Медленный маршрут «гребёнка» с подъёмами/снижениями по линии.
        "plan": [
            ("go", 400, 2600, 340, 40),
            ("go", 1400, 3300, 420, 38),
            ("go", 1800, 2200, 300, 42),
            ("go", 2900, 2400, 450, 40),
            ("go", 3300, 1300, 320, 44),
            ("go", 4200, 1400, 400, 42),
            ("go", 0, 0, 210, 38),
        ],
    },
}

# Фазы «турбулентности» (шума высоты) — разнести синусоиды по трекерам.
_WAVE_PHASE = {"101": 0.0, "102": 1.1, "103": 2.3, "104": 3.7}


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


def _offset(
    lat0: float, lon0: float, north_m: float, east_m: float
) -> tuple[float, float]:
    cos_lat = math.cos(math.radians(lat0))
    return (
        lat0 + north_m / 111_320.0,
        lon0 + east_m / (111_320.0 * cos_lat),
    )


def _route_position(
    track: dict,
    t: float,
    t_ref: float,
    base_lat: float,
    base_lon: float,
) -> tuple[float, float, float]:
    """Позиция на замкнутом маршруте track в момент t.

    Маршрут раскладывается на ноги с длительностью (дистанция/скорость для
    перегонов, время кругов для термиков); позиция — интерполяция по фазе
    ``(t - t_ref) % суммарная_длительность``. Возвращает (lat, lon, alt).
    """
    plan = track["plan"]
    legs: list[tuple[float, tuple, float, float, float]] = []
    total_dur = 0.0
    north0 = east0 = 0.0
    alt0 = track["start_alt"]
    dh = 0.0
    for seg in plan:
        if seg[0] == "go":
            _, n, e, alt, speed = seg
            dur = math.hypot(n - north0, e - east0) / (speed / 3.6)
        else:
            _, cn, ce, r, dh, rounds, speed = seg
            dur = rounds * 2.0 * math.pi * r / (speed / 3.6)
        legs.append((dur, seg, north0, east0, alt0))
        total_dur += dur
        if seg[0] == "go":
            _, n, e, alt, _ = seg
            north0, east0, alt0 = n, e, alt
        else:
            alt0 += dh

    u = (t - t_ref) % total_dur
    if u >= total_dur - 1e-9:
        u = 0.0
    acc = 0.0
    for dur, seg, n0, e0, a0 in legs:
        if u < acc + dur:
            frac = (u - acc) / dur if dur > 0.0 else 0.0
            if seg[0] == "go":
                _, n, e, alt_to, _ = seg
                north = n0 + (n - n0) * frac
                east = e0 + (e - e0) * frac
                alt = a0 + (alt_to - a0) * frac
            else:
                _, cn, ce, r, dh, rounds, _ = seg
                ang = 2.0 * math.pi * rounds * frac
                north = cn + r * math.cos(ang)
                east = ce + r * math.sin(ang)
                alt = a0 + dh * frac
            lat, lon = _offset(base_lat, base_lon, north, east)
            return lat, lon, alt
        acc += dur
    raise AssertionError("не найдена нога маршрута")


def _battery(
    t: float, t_ref: float, start: float = 92.0, drain_per_hour: float = 3.0
) -> float:
    return max(15.0, min(100.0, start - (t - t_ref) / 3600.0 * drain_per_hour))


def position_at(
    tracker_id: str,
    t: float,
    t_ref: float,
    base_lat: float = BASE_LAT,
    base_lon: float = BASE_LON,
) -> dict:
    """Позиция трекера на момент t (unix) в формате парсера."""
    track = TRACKS[tracker_id]
    lat, lon, alt = _route_position(track, t, t_ref, base_lat, base_lon)
    # «Турбулентность»: небольшой периодический шум высоты (живой варио/тренд).
    alt += 15.0 * math.sin((t + _WAVE_PHASE[tracker_id]) * (2.0 * math.pi / 37.0))

    batt = _battery(t, t_ref)
    sos = 1 if tracker_id == "104" and (t - t_ref) % 180 < 20 else 0
    return {
        "id": tracker_id,
        "name": TRACKER_NAMES[tracker_id],
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


def format_json(pos: dict) -> str:
    """Формирует JSON-строку пакета в формате реального устройства."""
    dt = datetime.fromtimestamp(pos["device_ts"], timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    return json.dumps(
        {
            "device_id": int(pos["id"]),
            "lat": pos["lat"],
            "lon": pos["lon"],
            "alt": pos["altitude"],
            "datetime": dt,
            "sos": pos["sos"],
            "battery_pct": pos["batt"],
            "battery_mv": pos["voltage"],
            "rssi": "-27.00dBm",
            "snr": "5.25dB",
            "ttl": 3,
            "crc": 241,
        },
        ensure_ascii=False,
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
        recent = repo.points(tracker_ids[0], ts_from=max(day0, now - 300.0), ts_to=now)
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
    telemetry = Signal(dict)
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
                pos = position_at(tracker_id, now, t_ref, self.base_lat, self.base_lon)
                for line in format_json(pos).splitlines():
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
