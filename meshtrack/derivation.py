"""Вычисление производных метрик из истории точек трекера.

Чистые функции: на вход — список точек ``(ts, lat, lon, alt)``,
на выход — GS (км/ч), курс (°), варио (м/с) и тренд (↗/↘/—).
"""
from __future__ import annotations

import math
from typing import Iterable

EARTH_RADIUS_M = 6371000.0
EMA_ALPHA = 0.5
TREND_UP = "↗"
TREND_DOWN = "↘"
TREND_FLAT = "—"


def _to_rad(deg: float) -> float:
    return deg * math.pi / 180.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние между двумя точками в метрах (haversine)."""
    dlat = _to_rad(lat2 - lat1)
    dlon = _to_rad(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(_to_rad(lat1)) * math.cos(_to_rad(lat2)) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Направление от точки 1 к точке 2, градусы от севера по часовой стрелке."""
    lat1r = _to_rad(lat1)
    lat2r = _to_rad(lat2)
    dlon = _to_rad(lon2 - lon1)
    y = math.sin(dlon) * math.cos(lat2r)
    x = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(
        dlon
    )
    brng = math.atan2(y, x) * 180.0 / math.pi
    return (brng + 360.0) % 360.0


def _ema(values: Iterable[float], alpha: float = EMA_ALPHA) -> float | None:
    """Экспоненциальное сглаживание, последнее значение имеет больший вес."""
    it = iter(values)
    try:
        ema = next(it)
    except StopIteration:
        return None
    for v in it:
        ema = alpha * v + (1.0 - alpha) * ema
    return ema


def derive(points: list[tuple[float, float, float, float | None]]) -> dict:
    """Вычисляет метрики по окну точек (≤ 60 с, минимум 2 точки).

    Args:
        points: список ``(ts, lat, lon, alt)``, отсортированный по ``ts``
            (возрастание). Высота может быть ``None``.

    Returns:
        dict с ключами ``gs_kmh``, ``course_deg``, ``vario_ms``, ``trend``.
        Недоступные метрики заполняются ``None``; ``trend`` всегда строка.
    """
    if len(points) < 2:
        return {
            "gs_kmh": None,
            "course_deg": None,
            "vario_ms": None,
            "trend": TREND_FLAT,
        }

    # Окно: последние 60 секунд от самой свежей точки
    newest_ts = points[-1][0]
    window = [p for p in points if newest_ts - p[0] <= 60.0]
    if len(window) < 2:
        return {
            "gs_kmh": None,
            "course_deg": None,
            "vario_ms": None,
            "trend": TREND_FLAT,
        }

    # Сегменты внутри окна
    speeds: list[float] = []
    bearings_sin: list[float] = []
    bearings_cos: list[float] = []
    for i in range(1, len(window)):
        ts1, lat1, lon1, _ = window[i - 1]
        ts2, lat2, lon2, _ = window[i]
        dt = ts2 - ts1
        if dt <= 0:
            continue
        dist = haversine_m(lat1, lon1, lat2, lon2)
        speeds.append((dist / dt) * 3.6)  # м/с → км/ч
        brng = bearing_deg(lat1, lon1, lat2, lon2)
        brng_rad = _to_rad(brng)
        bearings_sin.append(math.sin(brng_rad))
        bearings_cos.append(math.cos(brng_rad))

    gs_kmh = _ema(speeds) if speeds else None

    course_deg = None
    if bearings_sin and bearings_cos:
        avg_sin = _ema(bearings_sin) or 0.0
        avg_cos = _ema(bearings_cos) or 0.0
        course_deg = (math.atan2(avg_sin, avg_cos) * 180.0 / math.pi + 360.0) % 360.0

    # Варио — по всему окну
    vario_ms = None
    alts = [p[3] for p in window if p[3] is not None]
    if len(alts) >= 2:
        ts_first = window[0][0]
        ts_last = window[-1][0]
        dt_window = ts_last - ts_first
        if dt_window > 0:
            vario_ms = (alts[-1] - alts[0]) / dt_window

    if vario_ms is None:
        trend = TREND_FLAT
    elif vario_ms > 0.5:
        trend = TREND_UP
    elif vario_ms < -0.5:
        trend = TREND_DOWN
    else:
        trend = TREND_FLAT

    return {
        "gs_kmh": round(gs_kmh, 1) if gs_kmh is not None else None,
        "course_deg": round(course_deg, 1) if course_deg is not None else None,
        "vario_ms": round(vario_ms, 1) if vario_ms is not None else None,
        "trend": trend,
    }
