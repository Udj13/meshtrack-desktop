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
from meshtrack.mapstore import PNG_MAGIC, MapStore

FAKE_PNG = bytes(
    [
        0x89,
        0x50,
        0x4E,
        0x47,
        0x0D,
        0x0A,
        0x1A,
        0x0A,
        0x00,
        0x00,
        0x00,
        0x0D,
        0x49,
        0x48,
        0x44,
        0x52,
        0x00,
        0x00,
        0x00,
        0x01,
        0x00,
        0x00,
        0x00,
        0x01,
        0x08,
        0x06,
        0x00,
        0x00,
        0x00,
        0x1F,
        0x15,
        0xC4,
        0x89,
        0x00,
        0x00,
        0x00,
        0x0D,
        0x49,
        0x44,
        0x41,
        0x54,
        0x08,
        0xD7,
        0x63,
        0x60,
        0x60,
        0x60,
        0x60,
        0x00,
        0x00,
        0x00,
        0x03,
        0x00,
        0x01,
        0x00,
        0x05,
        0xFE,
        0xD4,
        0x6A,
        0xE6,
        0x00,
        0x00,
        0x00,
        0x00,
        0x49,
        0x45,
        0x4E,
        0x44,
        0xAE,
        0x42,
        0x60,
        0x82,
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


class HtmlErrorHandler(http.server.BaseHTTPRequestHandler):
    """Всегда отвечает 200 + html-страница ошибки (как rate-limit у WAF)."""

    def do_GET(self):
        body = b"<!DOCTYPE html><html><body>Too Many Requests</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class RetryThenPngHandler(http.server.BaseHTTPRequestHandler):
    """Первый запрос каждого тайла — html, следующие — PNG."""

    hits = {}

    def do_GET(self):
        path = self.path
        n = RetryThenPngHandler.hits.get(path, 0)
        RetryThenPngHandler.hits[path] = n + 1
        if n == 0:
            body = b"<!DOCTYPE html>"
            ctype = "text/html"
        else:
            body = FAKE_PNG
            ctype = "image/png"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def html_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), HtmlErrorHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/{{z}}/{{x}}/{{y}}.png"
    server.shutdown()


@pytest.fixture()
def retry_server():
    RetryThenPngHandler.hits = {}
    server = http.server.HTTPServer(("127.0.0.1", 0), RetryThenPngHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/{{z}}/{{x}}/{{y}}.png"
    server.shutdown()


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
    z, x, y, data, source = dl._download_one(10, 512, 256)
    assert data == FAKE_PNG
    assert data is not None
    assert source == "primary"
    store.insert(z, x, y, data)
    assert store.get(z, x, y) == FAKE_PNG


def test_format_size(use_lang):
    use_lang("ru")
    assert _format_size(512) == "512 Б"
    assert _format_size(1536) == "1.5 КБ"
    assert _format_size(2 * 1024 * 1024) == "2.0 МБ"
    use_lang("en")
    assert _format_size(512) == "512 B"
    assert _format_size(1536) == "1.5 KB"
    assert _format_size(2 * 1024 * 1024) == "2.0 MB"


def test_format_time(use_lang):
    use_lang("ru")
    assert _format_time(45) == "45 с"
    assert _format_time(90) == "1 мин 30 с"
    use_lang("en")
    assert _format_time(45) == "45 s"
    assert _format_time(90) == "1 min 30 s"


def test_download_rejects_html_200(store: MapStore, html_server: str):
    """HTTP 200 с html-телом (ошибка/rate-limit) не должен попадать в MBTiles."""
    bbox = (54.0, 54.01, 45.0, 45.01)
    result = download(store, bbox, html_server, zmin=10, zmax=10, workers=1)
    assert result["downloaded"] == 0
    assert result["failed"] > 0
    assert store.count() == 0


def test_download_failover_to_backup(
    store: MapStore, html_server: str, http_server: str
):
    """Основной источник отвечает HTML — тайл докачивается с резервного."""
    bbox = (54.0, 54.01, 45.0, 45.01)
    result = download(
        store,
        bbox,
        html_server,
        backup_url_template=http_server,
        zmin=10,
        zmax=10,
        workers=1,
        max_attempts=2,
    )
    assert result["failed"] == 0
    assert result["downloaded"] > 0
    assert result["downloaded_primary"] == 0
    assert result["downloaded_backup"] == result["downloaded"]
    assert store.count() == result["downloaded"]
    tiles = store.list_tiles(10)
    assert tiles
    z, x, y = tiles[0]
    assert store.get(z, x, y) == FAKE_PNG


def test_download_failover_no_backup_still_rejects_html(
    store: MapStore, html_server: str
):
    """Без резервного источника HTML-ответы по-прежнему не попадают в карту."""
    bbox = (54.0, 54.01, 45.0, 45.01)
    result = download(
        store,
        bbox,
        html_server,
        zmin=10,
        zmax=10,
        workers=1,
        max_attempts=1,
    )
    assert result["downloaded"] == 0
    assert result["failed"] > 0
    assert store.count() == 0


def test_download_failover_backup_down_marks_failed(store: MapStore, html_server: str):
    """Оба источника отдают HTML — тайл считается упавшим."""
    bbox = (54.0, 54.01, 45.0, 45.01)
    result = download(
        store,
        bbox,
        html_server,
        backup_url_template=html_server,
        zmin=10,
        zmax=10,
        workers=1,
        max_attempts=1,
    )
    assert result["downloaded"] == 0
    assert result["failed"] > 0
    assert store.count() == 0


def test_download_circuit_breaker_skips_primary(store: MapStore, http_server: str):
    """После порога неудач основной источник больше не запрашивается."""
    primary_hits = []

    class CountingHtmlHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            primary_hits.append(self.path)
            body = b"<!DOCTYPE html><html><body>error</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), CountingHtmlHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    primary_url = f"http://127.0.0.1:{port}/{{z}}/{{x}}/{{y}}.png"
    try:
        bbox = (54.0, 54.01, 45.0, 45.01)
        result = download(
            store,
            bbox,
            primary_url,
            backup_url_template=http_server,
            zmin=10,
            zmax=11,
            workers=1,
            max_attempts=4,
            primary_fail_threshold=2,
        )
        assert result["failed"] == 0
        assert result["downloaded"] > 0
        assert result["downloaded_primary"] == 0
        assert result["downloaded_backup"] == result["downloaded"]
        # Основной источник отдал HTML ровно до срабатывания предохранителя
        # (порог = 2), дальше все тайлы брались сразу с резервного.
        assert len(primary_hits) == 2
    finally:
        server.shutdown()


def test_download_circuit_breaker_keeps_retrying_below_threshold(
    store: MapStore, http_server: str
):
    """До порога основной источник не забывается даже после неудач."""
    primary_hits = []
    first_two = []

    class FlakyHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            primary_hits.append(self.path)
            if len(first_two) < 2:
                first_two.append(self.path)
                body = b"<!DOCTYPE html>"
                ctype = "text/html"
            else:
                body = FAKE_PNG
                ctype = "image/png"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), FlakyHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    primary_url = f"http://127.0.0.1:{port}/{{z}}/{{x}}/{{y}}.png"
    try:
        bbox = (54.0, 54.01, 45.0, 45.01)
        result = download(
            store,
            bbox,
            primary_url,
            zmin=10,
            zmax=10,
            workers=1,
        )
        assert result["failed"] == 0
        assert result["downloaded"] > 0
        assert len(primary_hits) > len(first_two)
    finally:
        server.shutdown()


def test_tile_downloader_circuit_breaker_unit(store: MapStore):
    """Вручную: после порога неудач _download_one не трогает основной."""
    primary_calls = []

    class StubResponse:
        def __init__(self, content):
            self.status_code = 200
            self.content = content

    primary_url = "http://broken.example/{z}/{x}/{y}.png"
    backup_url = "http://ok.example/{z}/{x}/{y}.png"

    dl = TileDownloader(store, primary_url, backup_url_template=backup_url)
    dl.primary_fail_threshold = 2
    dl._session.get = lambda url, timeout=30: (
        primary_calls.append(url) or StubResponse(b"<!DOCTYPE html>")
        if url.startswith("http://broken")
        else StubResponse(FAKE_PNG)
    )

    for _ in range(3):
        z, x, y, data, source = dl._download_one(10, 512, 256)
        assert source == "backup"
        assert data == FAKE_PNG

    # Порог 2: основной запрашивался на первых двух неудачах, дальше нет.
    assert len(primary_calls) == 2


def test_download_retries_invalid_200_then_png(store: MapStore, retry_server: str):
    """Первый html-ответ пережидается, со второго — валидный PNG сохраняется."""
    bbox = (54.0, 54.01, 45.0, 45.01)
    result = download(store, bbox, retry_server, zmin=10, zmax=10, workers=1)
    assert result["failed"] == 0
    assert result["downloaded"] > 0
    assert store.count() == result["downloaded"]
    tiles = store.list_tiles(10)
    assert tiles
    z, x, y = tiles[0]
    data = store.get(z, x, y)
    assert data == FAKE_PNG
    assert data is not None
    assert data[:8] == PNG_MAGIC


def test_download_sends_browser_user_agent(store: MapStore):
    """Загрузчик шлёт браузерный User-Agent (анти-бот обходит)."""
    seen = []

    class UaRecordingHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("User-Agent", ""))
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(FAKE_PNG)))
            self.end_headers()
            self.wfile.write(FAKE_PNG)

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), UaRecordingHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/{{z}}/{{x}}/{{y}}.png"
    try:
        bbox = (54.0, 54.01, 45.0, 45.01)
        result = download(store, bbox, url, zmin=10, zmax=10, workers=1)
        assert result["failed"] == 0
        assert result["downloaded"] > 0
        assert seen, "ни одного запроса не было"
        assert all("python-requests" not in ua for ua in seen)
        assert all("Mozilla" in ua for ua in seen)
    finally:
        server.shutdown()


def test_download_404_fails_fast(store: MapStore):
    """404 на источнике не ретраится 4-5 раз: один запрос на тайл."""
    hits = []

    class FourOhFourHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), FourOhFourHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/{{z}}/{{x}}/{{y}}.png"
    try:
        bbox = (54.0, 54.01, 45.0, 45.01)
        result = download(store, bbox, url, zmin=10, zmax=10, workers=1)
        assert result["failed"] == result["total"]
        assert result["total"] > 0
        # Каждый тайл запрошен ровно один раз (без ретраев по 4×).
        assert len(hits) == result["total"]
        assert store.count() == 0
    finally:
        server.shutdown()
