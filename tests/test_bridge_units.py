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


class TrackShownSpy(QObject):
    received = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self.values = []
        self.received.connect(self._on_received)

    def _on_received(self, tracker_id, shown):
        self.values.append((tracker_id, shown))


class ViewSpy(QObject):
    received = Signal(float, float, int)

    def __init__(self):
        super().__init__()
        self.values = []
        self.received.connect(self._on_received)

    def _on_received(self, lat, lon, zoom):
        self.values.append((lat, lon, zoom))


def test_push_position_emits_signal():
    bridge = WebBridge()
    spy = SignalSpy()
    bridge.positionReceived.connect(spy.received)

    pos = {"id": "1", "lat": "54.4", "lon": "45.4"}
    bridge.pushPosition(pos)

    assert len(spy.values) == 1
    assert spy.values[0]["id"] == "1"


def test_echo():
    bridge = WebBridge()
    assert bridge.echo("hello") == "hello"


def test_set_track_shown_emits_signal():
    bridge = WebBridge()
    spy = TrackShownSpy()
    bridge.trackShown.connect(spy.received)

    bridge.setTrackShown("1", True)
    bridge.setTrackShown("1", False)

    assert spy.values == [("1", True), ("1", False)]


def test_report_view_emits_signal():
    bridge = WebBridge()
    spy = ViewSpy()
    bridge.viewChanged.connect(spy.received)

    bridge.reportView(54.4, 45.5, 13)

    assert spy.values == [(54.4, 45.5, 13)]


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

    result = json.loads(bridge.getTrack("1", 0.0, 3.0))
    assert result["points"] == pts


def test_get_track_without_repo():
    bridge = WebBridge()
    import json

    result = json.loads(bridge.getTrack("1", 0.0, 1.0))
    assert result["points"] == []


def test_clear_history():
    repo = FakeRepo()
    bridge = WebBridge(repo=repo)
    spy = VoidSignalSpy()
    bridge.historyCleared.connect(spy.received)

    bridge.clearHistory()

    assert repo.cleared is True
    assert spy.count == 1


class FakeSettings:
    def __init__(self, maps=None, active=None, language="ru"):
        self._maps = maps or []
        self.active_map_id = active
        self.language = language

    @property
    def has_maps(self):
        return bool(self._maps)

    def default_map_id(self):
        return self._maps[0]["id"] if self._maps else None

    def get_map_path(self, map_id):
        for m in self._maps:
            if m["id"] == map_id:
                return m["path"]
        return None


def test_get_min_max_zoom_without_settings():
    bridge = WebBridge()
    assert bridge.getMinZoom() == 9
    assert bridge.getMaxZoom() == 15


def test_get_min_max_zoom_with_missing_map(tmp_path):
    cfg = FakeSettings(
        maps=[{"id": "x", "path": str(tmp_path / "missing.mbtiles")}], active="x"
    )
    bridge = WebBridge(settings=cfg)
    assert bridge.getMinZoom() == 9
    assert bridge.getMaxZoom() == 15


def test_get_min_max_zoom_from_mbtiles(tmp_path):
    from meshtrack.mapstore import MapStore

    path = tmp_path / "test.mbtiles"
    store = MapStore(path)
    store.set_minmax_zoom(10, 14)
    store.insert(10, 1, 1, b"tile")

    cfg = FakeSettings(maps=[{"id": "test", "path": str(path)}], active="test")
    bridge = WebBridge(settings=cfg)
    assert bridge.getMinZoom() == 10
    assert bridge.getMaxZoom() == 14
