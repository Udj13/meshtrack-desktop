"""Тесты serial_worker.py на file:// источнике (headless)."""
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from meshtrack.serial_worker import SerialWorker


def _json_line(dev: int, lat: float, lon: float, alt: int, sec: int) -> str:
    return (
        f'{{"device_id":{dev},"lat":{lat:.5f},"lon":{lon:.5f},"alt":{alt},'
        f'"datetime":"2026-09-10T12:00:{sec:02d}","sos":0,"battery_pct":87,'
        f'"battery_mv":4020,"rssi":"-27.00dBm","snr":"5.25dB","ttl":3,"crc":241}}'
    )


@pytest.fixture
def fake_blocks_file(tmp_path: Path) -> str:
    lines = []
    for i in range(3):
        lines.append(_json_line(i + 1, 54.0 + i * 0.001, 45.0 + i * 0.001, 500 + i, i))
        lines.append(f"Queue size: {i + 1}")
    p = tmp_path / "fake.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
    assert positions[0]["device_ts"] is not None
    assert queues == [1, 2, 3]
    assert len(raw) > 0


def test_serial_worker_ignores_table_and_boot_output(tmp_path):
    """Реальный вывод устройства: загрузочный лог + табличка + JSON.

    Позиции приходят только из JSON-строк, остальные строки игнорируются.
    """
    p = tmp_path / "mixed.txt"
    p.write_text(
        "ESP-ROM:esp32s3-20210327\n"
        "Radio Starting to listen ... success!\n"
        "Radio Received packet!\n"
        "Device ID:\t\t1\n"
        "Latitude:\t\t54.211205\n"
        "Postfix:\t\tOK\n"
        "Json output:\n"
        + _json_line(1, 54.211205, 45.158203, 168, 1)
        + "\n"
        + _json_line(2, 54.211220, 45.158337, 201, 2)
        + "\n",
        encoding="utf-8",
    )
    app = QCoreApplication.instance()

    positions = []
    worker = SerialWorker(f"file://{p}")
    worker.position.connect(positions.append)
    worker.finished.connect(app.quit)
    worker.start()
    app.exec()

    assert len(positions) == 2
    assert positions[0]["id"] == "boon1"
    assert positions[1]["id"] == "boon2"
    assert positions[0]["altitude"] == 168.0
    assert positions[1]["altitude"] == 201.0


def test_serial_worker_error_on_missing_port():
    errors = []
    worker = SerialWorker("file:///nonexistent/path.txt")
    worker.error.connect(errors.append)
    worker.finished.connect(QCoreApplication.instance().quit)
    worker.start()
    QCoreApplication.instance().exec()
    assert len(errors) == 1
    assert "Cannot open" in errors[0]