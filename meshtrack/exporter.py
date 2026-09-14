"""Экспорт истории треков в GPX/CSV.

Чистые функции без Qt: принимают `dict[tracker_id, list[point]]` и путь,
поэтому легко тестируются headless. Используются диалогом настроек
(«Экспорт GPX/CSV» — все трекеры за выбранный период фильтра).
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from xml.sax.saxutils import escape, quoteattr

CSV_HEADER = [
    "tracker_id",
    "ts",
    "time_utc",
    "lat",
    "lon",
    "alt",
    "batt",
    "voltage",
    "sos",
]

GPX_NS = "http://www.topografix.com/GPX/1/1"


def iso_utc(ts) -> str:
    """Unix-время → 'YYYY-MM-DDTHH:MM:SSZ' ('' при некорректном значении)."""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (TypeError, ValueError, OSError):
        return ""


def collect_tracks(
    repo,
    ts_from: float | None = None,
    ts_to: float | None = None,
) -> dict[str, list[dict]]:
    """Собирает треки всех трекеров за период (пустые пропускаются)."""
    tracks: dict[str, list[dict]] = {}
    for tracker_id in repo.all_trackers():
        points = repo.points(tracker_id, ts_from=ts_from, ts_to=ts_to)
        if points:
            tracks[tracker_id] = points
    return tracks


def export_gpx(path: str, tracks: dict[str, list[dict]], creator: str = "MeshTrack") -> int:
    """Пишет GPX 1.1: по одному `<trk>` на трекер. Возвращает число trkpt."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<gpx version="1.1" creator={quoteattr(creator)} xmlns="{GPX_NS}">',
    ]
    count = 0
    for tracker_id, points in tracks.items():
        lines.append("\t<trk>")
        lines.append(f"\t\t<name>{escape(str(tracker_id))}</name>")
        lines.append("\t\t<trkseg>")
        for point in points:
            lat = point.get("lat")
            lon = point.get("lon")
            if lat is None or lon is None:
                continue
            lines.append(f'\t\t\t<trkpt lat="{lat}" lon="{lon}">')
            alt = point.get("alt")
            if alt is not None:
                lines.append(f"\t\t\t\t<ele>{alt}</ele>")
            time_str = iso_utc(point.get("ts"))
            if time_str:
                lines.append(f"\t\t\t\t<time>{time_str}</time>")
            lines.append("\t\t\t</trkpt>")
            count += 1
        lines.append("\t\t</trkseg>")
        lines.append("\t</trk>")
    lines.append("</gpx>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return count


def export_csv(path: str, tracks: dict[str, list[dict]]) -> int:
    """Пишет все трекеры в один CSV. Возвращает число строк данных."""
    rows = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for tracker_id, points in tracks.items():
            for point in points:
                writer.writerow(
                    [
                        tracker_id,
                        point.get("ts"),
                        iso_utc(point.get("ts")),
                        point.get("lat"),
                        point.get("lon"),
                        point.get("alt"),
                        point.get("batt"),
                        point.get("voltage"),
                        point.get("sos"),
                    ]
                )
                rows += 1
    return rows
