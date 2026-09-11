"""Unit-тесты webbridge.py без GUI (QCoreApplication достаточно)."""
import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

from meshtrack.webbridge import WebBridge


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    yield app


class SignalSpy(QObject):
    received = Signal(dict)

    def __init__(self):
        super().__init__()
        self.values = []
        self.received.connect(self._on_received)

    def _on_received(self, value):
        self.values.append(value)


class VoidSignalSpy(QObject):
    received = Signal()

    def __init__(self):
        super().__init__()
        self.count = 0
        self.received.connect(self._on_received)

    def _on_received(self):
        self.count += 1


def test_push_position_emits_signal():
    bridge = WebBridge()
    spy = SignalSpy()
    bridge.positionReceived.connect(spy.received)

    pos = {"id": "boon1", "lat": "54.4", "lon": "45.4"}
    bridge.pushPosition(pos)

    assert len(spy.values) == 1
    assert spy.values[0]["id"] == "boon1"


def test_echo():
    bridge = WebBridge()
    assert bridge.echo("hello") == "hello"


class FakeRepo:
    def __init__(self, points=None):
        self._points = points or []
        self.cleared = False

    def points(self, tracker_id, ts_from=None, ts_to=None, limit=2000):
        return self._points

    def clear_all_positions(self):
        self.cleared = True
        return 42


def test_get_track_returns_json():
    pts = [
        {"ts": 1.0, "lat": 54.0, "lon": 45.0, "alt": 100},
        {"ts": 2.0, "lat": 54.1, "lon": 45.1, "alt": 110},
    ]
    bridge = WebBridge(repo=FakeRepo(pts))
    import json

    result = json.loads(bridge.getTrack("boon1", 0.0, 3.0))
    assert result["points"] == pts


def test_get_track_without_repo():
    bridge = WebBridge()
    import json

    result = json.loads(bridge.getTrack("boon1", 0.0, 1.0))
    assert result["points"] == []


def test_clear_history():
    repo = FakeRepo()
    bridge = WebBridge(repo=repo)
    spy = VoidSignalSpy()
    bridge.historyCleared.connect(spy.received)

    bridge.clearHistory()

    assert repo.cleared is True
    assert spy.count == 1
