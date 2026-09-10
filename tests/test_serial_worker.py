"""Тесты serial_worker.py на file:// источнике (headless)."""
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from meshtrack.serial_worker import SerialWorker


@pytest.fixture
def fake_blocks_file(tmp_path: Path) -> str:
    blocks = ""
    for i in range(3):
        blocks += f"""Radio Received packet!
Device ID: {i + 1}
Latitude: {54.0 + i * 0.001:.5f}
Longitude: {45.0 + i * 0.001:.5f}
Altitude: {500 + i}
Date/Time: 2026-09-10 12:00:0{i}
SOS: 0
Battery Voltage: 4020
Battery Level: 87%
Postfix: OK
Queue size: {i + 1}
"""
    p = tmp_path / "fake.txt"
    p.write_text(blocks, encoding="utf-8")
    return f"file://{p}"


def test_serial_worker_reads_file(fake_blocks_file):
    app = QCoreApplication.instance()
    assert app is not None

    positions = []
    queues = []
    raw = []

    worker = SerialWorker(fake_blocks_file)
    worker.position.connect(positions.append)
    worker.queue_size.connect(queues.append)
    worker.raw_line.connect(raw.append)
    worker.finished.connect(app.quit)
    worker.start()

    app.exec()

    assert len(positions) == 3
    assert positions[0]["id"] == "boon1"
    assert positions[1]["id"] == "boon2"
    assert positions[2]["id"] == "boon3"
    assert queues == [1, 2, 3]
    assert len(raw) > 0


def test_serial_worker_error_on_missing_port():
    errors = []
    worker = SerialWorker("file:///nonexistent/path.txt")
    worker.error.connect(errors.append)
    worker.finished.connect(QCoreApplication.instance().quit)
    worker.start()
    QCoreApplication.instance().exec()
    assert len(errors) == 1
    assert "Cannot open" in errors[0]
