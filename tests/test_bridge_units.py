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
