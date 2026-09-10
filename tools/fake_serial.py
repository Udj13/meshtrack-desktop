#!/usr/bin/env python3
"""Генератор фиктивных LoRa-пакетов для тестирования без реального приёмника.

Сценарии:
  static   — неподвижная точка (GS≈0, тренд —)
  circle   — круг r=200м, GS ~40 км/ч (проверка стрелки курса)
  climb    — постоянный набор +1.5 м/с (тренд ↗)
  descend  — снижение −2 м/с (тренд ↘)
  sos      — всплеск SOS=1

Вывод — текстовый поток в стиле UART: пары блоков “Radio Received packet!” …
“Postfix: OK”. По умолчанию пишет в stdout; --output FILE — в файл.

Примеры:
  python tools/fake_serial.py --scenario climb --output /tmp/f.txt
  python tools/fake_serial.py --scenario sos --count 3
"""
import argparse
import math
import sys
import time

# Базовая точка (Мордовия, окрестности аэродрома Лямбирь)
BASE_LAT = 54.4000
BASE_LON = 45.4000
CEN_ALT = 500.0      # м — старт высоты

_BLOCK_TMPL = """Radio Received packet!
Device ID: {dev}
Latitude: {lat:.5f}
Longitude: {lon:.5f}
Altitude: {alt}
Date/Time: 2026-09-10 12:{mm:02d}:{ss:02d}
SOS: {sos}
Battery Voltage: {volt}
Battery Level: {batt}%
Postfix: OK
Queue size: {q}
"""


def _fmt_block(i, lat, lon, alt, sos=0, volt=4020, batt=87, q=3):
    return _BLOCK_TMPL.format(
        dev=1, lat=lat, lon=lon, alt=int(alt), mm=(i // 60) % 60, ss=i % 60,
        sos=sos, volt=volt, batt=batt, q=q,
    )


def scenario_static(count):
    for i in range(count):
        yield _fmt_block(i, BASE_LAT, BASE_LON, CEN_ALT)


def scenario_circle(count, radius_m=200, speed_kmh=40, step_s=2):
    """Равномерное движение по окружности. Угол шага рассчитан из GS."""
    w = speed_kmh / 3.6  # м/с
    dang = (w * step_s) / radius_m
    for i in range(count):
        ang = i * dang
        lat = BASE_LAT + (radius_m / 111_320)
        lon = BASE_LON + (radius_m / (111_320 * math.cos(BASE_LAT)))
        lat = BASE_LAT + radius_m / 111_320 * math.cos(ang)
        lon = BASE_LON + radius_m / (111_320 * math.cos(BASE_LAT)) * math.sin(ang)
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
            out.write(blk)
            out.flush()
            if args.interval:
                time.sleep(args.interval)
    finally:
        if args.output:
            out.close()


if __name__ == "__main__":
    main()
