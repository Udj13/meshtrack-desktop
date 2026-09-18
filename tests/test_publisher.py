"""Тесты meshtrack/publisher.py (headless, без Qt)."""
import time

from meshtrack.publisher import TRACCAR_URL, TraccarPublisher, build_payload


class FakeResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code


POSITION = {
    "id": "123",
    "lat": "54.12345",
    "lon": "45.6789",
    "altitude": "1230",
    "batt": "87",
    "voltage": "4020",
    "sos": "0",
}


def _wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_build_payload_legacy_fields():
    payload = build_payload({**POSITION, "ts": 1700000000.0})
    assert payload["id"] == "boon123"
    assert payload["lat"] == "54.12345"
    assert payload["lon"] == "45.6789"
    assert payload["altitude"] == "1230"
    assert payload["timestamp"] == "2023-11-14T22:13:20Z"
    assert payload["sos"] == "0"
    assert payload["ttl"] == "3"


def test_build_payload_prefers_parser_timestamp_and_defaults_sos():
    payload = build_payload(
        {
            "id": "1",
            "lat": 54.0,
            "lon": 45.0,
            "timestamp": "2026-09-10T12:34:56Z",
            "sos": None,
        }
    )
    assert payload["timestamp"] == "2026-09-10T12:34:56Z"
    assert payload["sos"] == "0"


def test_disabled_enqueue_is_noop():
    calls = []
    publisher = TraccarPublisher(enable=False, post=lambda *a, **k: calls.append(a))
    publisher.enqueue(POSITION)
    time.sleep(0.05)
    assert calls == []
    assert publisher.pending == 0


def test_enabled_enqueue_sends_payload():
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append((url, data, timeout))
        return FakeResponse(200)

    publisher = TraccarPublisher(enable=True, post=fake_post)
    publisher.enqueue({**POSITION, "ts": 1700000000.0})
    assert publisher.flush(timeout=2.0) is True

    assert len(calls) == 1
    url, data, timeout = calls[0]
    assert url == TRACCAR_URL
    assert data["id"] == "boon123"
    assert data["ttl"] == "3"
    assert timeout > 0


def test_invalid_position_not_enqueued():
    calls = []
    publisher = TraccarPublisher(enable=True, post=lambda *a, **k: calls.append(a))
    publisher.enqueue({"id": "1"})  # нет lat/lon
    publisher.enqueue({"lat": 1.0, "lon": 2.0})  # нет id
    time.sleep(0.05)
    assert calls == []
    assert publisher.pending == 0


def test_failed_send_requeues_and_pauses():
    calls = []

    def failing_post(url, data=None, timeout=None):
        calls.append(data)
        return FakeResponse(500)

    publisher = TraccarPublisher(
        enable=True,
        post=failing_post,
        max_failed=2,
        pause_s=0.5,
        retry_delay_s=0.01,
    )
    publisher.enqueue({**POSITION, "ts": 1700000000.0})

    assert _wait_for(lambda: len(calls) >= 2 and publisher.pending == 1, timeout=2.0)
    # payload возвращён в очередь и заморожен на pause_s

    attempts_before_pause = len(calls)
    time.sleep(0.15)  # меньше pause_s → новых попыток быть не должно
    assert len(calls) == attempts_before_pause

    publisher.stop()


def test_toggle_disable_clears_queue():
    calls = []

    def slow_fail(url, data=None, timeout=None):
        calls.append(data)
        return FakeResponse(500)

    publisher = TraccarPublisher(
        enable=True, post=slow_fail, retry_delay_s=0.05, pause_s=0.05
    )
    publisher.enqueue({**POSITION, "ts": 1700000000.0})
    assert _wait_for(lambda: len(calls) >= 1)
    publisher.enable = False
    assert publisher.flush(timeout=2.0) is True
    time.sleep(0.05)
    assert publisher.pending == 0
    publisher.stop()
