#!/usr/bin/env python3
"""Генератор фиктивных LoRa-пакетов для тестирования без реального приёмника.

Сценарии:
  static   — неподвижная точка (GS≈0, тренд —)
  circle   — круг r=200м, GS ~40 км/ч (проверка стрелки курса)
  climb    — постоянный набор +1.5 м/с (тренд ▲)
  descend  — снижение −2 м/с (тренд ▼)
  sos      — всплеск SOS=1

Вывод — JSON-строки в формате реального устройства (по одной на пакет).
По умолчанию пишет в stdout; --output FILE — в файл.

Примеры:
  python tools/fake_serial.py --scenario climb --output /tmp/f.txt
  python tools/fake_serial.py --scenario sos --count 3
"""
import argparse
import json
import math
import sys
import time

# Базовая точка (Мордовия, окрестности аэродрома Лямбирь)
BASE_LAT = 54.4000
BASE_LON = 45.4000
CEN_ALT = 500.0      # м — старт высоты


def _fmt_block(i, lat, lon, alt, sos=0, volt=4020, batt=87, q=3):
    return json.dumps({
        "device_id": 1,
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "alt": int(alt),
        "datetime": f"2026-09-10T12:{i // 60:02d}:{i % 60:02d}",
        "sos": sos,
        "battery_pct": batt,
        "battery_mv": volt,
        "rssi": "-27.00dBm",
        "snr": "5.25dB",
        "ttl": 3,
        "crc": 241,
    }, ensure_ascii=False)


def scenario_static(count):
    for i in range(count):
        yield _fmt_block(i, BASE_LAT, BASE_LON, CEN_ALT)


def scenario_circle(count, radius_m=200, speed_kmh=40, step_s=2):
    """Равномерное движение по окружности. Угол шага рассчитан из GS."""
    w = speed_kmh / 3.6  # м/с
    dang = (w * step_s) / radius_m
    cos_lat = math.cos(math.radians(BASE_LAT))
    for i in range(count):
        ang = i * dang
        lat = BASE_LAT + radius_m / 111_320 * math.cos(ang)
        lon = BASE_LON + radius_m / (111_320 * cos_lat) * math.sin(ang)
        yield _fmt_block(i, lat, lon, CEN_ALT + 200)


def scenario_climb(count, rate=1.5, step_s=2):
    for i in range(count):
        yield _fmt_block(i, BASE_LAT, BASE_LON, CEN_ALT + rate * i * step_s)


def scenario_descend(count, rate=-2.0, step_s=2):
    for i in range(count):
        yield _fmt_block(i, BASE_LAT + i * 1e-4, BASE_LON + i * 1e-4,
                         CEN_ALT + rate * i * step_s)


def scenario_sos(count):
    for i in range(count):
        sos = 1 if i == max(1, count // 2) else 0
        yield _fmt_block(i, BASE_LAT, BASE_LON, CEN_ALT, sos=sos)


SCENARIOS = {
    "static": scenario_static,
    "circle": scenario_circle,
    "climb": scenario_climb,
    "descend": scenario_descend,
    "sos": scenario_sos,
}


def main():
    ap = argparse.ArgumentParser(description="Fake serial generator")
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--output", type=str, default=None,
                    help="Файл для вывода (по умолчанию stdout)")
    ap.add_argument("--interval", type=float, default=0.0,
                    help="Задержка (с) между блоками при выводе в stdout/file")
    args = ap.parse_args()

    gen = SCENARIOS[args.scenario](args.count)

    out = open(args.output, "w") if args.output else sys.stdout
    try:
        for blk in gen:
            out.write(blk + "\n")
            out.flush()
            if args.interval:
                time.sleep(args.interval)
    finally:
        if args.output:
            out.close()


if __name__ == "__main__":
    main()