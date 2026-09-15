"""CLI для скачивания области в MBTiles.

Примеры:
    python tools/download_region.py --region lyambir_airfield --out ~/maps/lyambir.mbtiles
    python tools/download_region.py --bbox 54.0,54.1,45.0,45.1 --zmin 10 --zmax 12 --out test.mbtiles
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Добавляем корень проекта в PYTHONPATH для запуска `python tools/download_region.py`.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from meshtrack.downloader import _format_size, _format_time, download, estimate_tile_count
from meshtrack.mapstore import MapStore
from meshtrack.regions import get_prebuilt

OPENTOPOMAP_TEMPLATE = "https://tile.opentopomap.org/{z}/{x}/{y}.png"


def parse_bbox(s: str) -> tuple[float, float, float, float]:
    parts = [float(x.strip()) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox должен быть в формате south,north,west,east")
    return tuple(parts)


def main():
    ap = argparse.ArgumentParser(description="Скачать область тайлов в MBTiles")
    ap.add_argument("--region", help="id встроенного региона")
    ap.add_argument("--bbox", help="south,north,west,east")
    ap.add_argument("--zmin", type=int, default=9)
    ap.add_argument("--zmax", type=int, default=15)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", required=True, help="путь к .mbtiles")
    args = ap.parse_args()

    if args.region:
        region = get_prebuilt(args.region)
        if region is None:
            print(f"Неизвестный регион: {args.region}", file=sys.stderr)
            sys.exit(1)
        bbox = region.bbox
        map_id = region.id
    elif args.bbox:
        bbox = parse_bbox(args.bbox)
        map_id = "custom"
    else:
        print("Укажите --region или --bbox", file=sys.stderr)
        sys.exit(1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    store = MapStore(out)
    store.set_metadata("name", map_id)
    store.set_metadata("format", "png")
    store.set_metadata("version", "1.1")
    south, north, west, east = bbox
    store.set_metadata("bbox", f"{south},{north},{west},{east}")
    store.set_metadata(
        "tile_count_expected",
        str(estimate_tile_count(south, north, west, east, args.zmin, args.zmax)),
    )

    def on_progress(done: int, total: int, stats: dict):
        pct = done * 100 // total if total else 0
        size = _format_size(stats.get("bytes_downloaded", 0))
        estimated = _format_size(stats.get("bytes_estimated", 0))
        remaining = stats.get("seconds_remaining")
        time_str = _format_time(remaining) if remaining is not None else "подсчёт…"
        print(
            f"\r{done}/{total} ({pct}%) | {size}/~{estimated} | осталось ~{time_str}",
            end="",
            flush=True,
        )

    print(f"Скачивание {map_id} -> {out}")
    result = download(
        store,
        bbox,
        OPENTOPOMAP_TEMPLATE,
        zmin=args.zmin,
        zmax=args.zmax,
        workers=args.workers,
        on_progress=on_progress,
    )
    if result.get("failed", 0) == 0:
        store.set_metadata("complete", "1")
    print()
    size = _format_size(result.get("bytes_downloaded", 0))
    elapsed = result.get("elapsed_seconds", 0)
    print(
        f"Готово: скачано {result['downloaded']} ({size}), "
        f"пропущено {result['skipped']}, ошибок {result['failed']}, "
        f"за {_format_time(elapsed)}"
    )


if __name__ == "__main__":
    main()
