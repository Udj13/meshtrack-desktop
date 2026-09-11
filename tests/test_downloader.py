"""Тесты meshtrack/downloader.py с локальным HTTP-сервером (headless)."""
import http.server
import threading
from pathlib import Path

import pytest

from meshtrack.downloader import (
    TileDownloader,
    _format_size,
    _format_time,
    download,
    estimate_tile_count,
    tile_range_for_bbox,
)
from meshtrack.mapstore import MapStore

FAKE_PNG = bytes(
    [
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4,
        0x89, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x44, 0x41,
        0x54, 0x08, 0xD7, 0x63, 0x60, 0x60, 0x60, 0x60,
        0x00, 0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x05,
        0xFE, 0xD4, 0x6A, 0xE6, 0x00, 0x00, 0x00, 0x00,
        0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
    ]
)


class TileHandler(http.server.BaseHTTPRequestHandler):
    """Возвращает FAKE_PNG для любого GET-запроса."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(FAKE_PNG)))
        self.end_headers()
        self.wfile.write(FAKE_PNG)

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def http_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), TileHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/{{z}}/{{x}}/{{y}}.png"
    server.shutdown()


@pytest.fixture
def store(tmp_path: Path) -> MapStore:
    return MapStore(tmp_path / "dl.mbtiles")


def test_tile_range_for_bbox():
    xmin, xmax, ymin, ymax = tile_range_for_bbox(54.0, 54.1, 45.0, 45.1, 10)
    assert xmin <= xmax
    assert ymin <= ymax
    assert xmin >= 0
    assert xmax < 2**10


def test_estimate_tile_count():
    n = estimate_tile_count(54.0, 54.1, 45.0, 45.1, 10, 11)
    assert n > 0


def test_download_writes_tiles(store: MapStore, http_server: str):
    bbox = (54.0, 54.01, 45.0, 45.01)
    result = download(store, bbox, http_server, zmin=10, zmax=11, workers=2)
    assert result["downloaded"] > 0
    assert result["failed"] == 0
    assert store.count() == result["downloaded"]
    assert result["bytes_downloaded"] == result["downloaded"] * len(FAKE_PNG)
    assert result["elapsed_seconds"] >= 0


def test_download_progress_callback(store: MapStore, http_server: str):
    calls = []

    def on_progress(done: int, total: int, stats: dict):
        calls.append((done, total, stats))

    bbox = (54.0, 54.01, 45.0, 45.01)
    result = download(
        store, bbox, http_server, zmin=10, zmax=10, workers=2, on_progress=on_progress
    )
    assert len(calls) > 0
    last_done, last_total, last_stats = calls[-1]
    assert last_done == last_total == result["total"]
    assert "bytes_downloaded" in last_stats
    assert "bytes_estimated" in last_stats
    assert "tiles_per_second" in last_stats
    assert "seconds_remaining" in last_stats


def test_download_resume_skips_existing(store: MapStore, http_server: str):
    bbox = (54.0, 54.01, 45.0, 45.01)
    first = download(store, bbox, http_server, zmin=10, zmax=10, workers=2)
    assert first["downloaded"] > 0

    second = download(store, bbox, http_server, zmin=10, zmax=10, workers=2)
    assert second["skipped"] == first["downloaded"]
    assert second["downloaded"] == 0


def test_download_cancel(store: MapStore, http_server: str):
    bbox = (54.0, 54.5, 45.0, 45.5)
    cancel_event = threading.Event()
    cancel_event.set()
    result = download(
        store, bbox, http_server, zmin=9, zmax=11, workers=2, cancel_event=cancel_event
    )
    # При отмене сразу большинство тайлов не скачивается.
    assert result["downloaded"] == 0


def test_tile_downloader_rate_limit(store: MapStore, http_server: str):
    dl = TileDownloader(store, http_server, rate_limit=0.05)
    z, x, y, data = dl._download_one(10, 512, 256)
    assert data == FAKE_PNG
    store.insert(z, x, y, data)
    assert store.get(z, x, y) == FAKE_PNG


def test_format_size():
    assert _format_size(512) == "512 Б"
    assert _format_size(1536) == "1.5 КБ"
    assert _format_size(2 * 1024 * 1024) == "2.0 МБ"


def test_format_time():
    assert _format_time(45) == "45 с"
    assert _format_time(90) == "1 мин 30 с"
