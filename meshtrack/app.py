"""Главное окно приложения MeshTrack.

Фаза 1: карта на QtWebEngine + WebChannel + SerialWorker + Repository.
"""
import os
import platform
import sys
import time
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QMainWindow,
    QWidget,
)

from .repository import Repository
from .serial_worker import SerialWorker
from .webbridge import WebBridge


def app_data_dir() -> Path:
    """Путь к папке данных приложения (PROJECT.md §8)."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / "MeshTrack"
    else:
        return Path.home() / "Library" / "Application Support" / "MeshTrack"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MeshTrack")
        self.resize(1200, 800)

        # Данные
        data_dir = app_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.repo = Repository(str(data_dir / "meshtrack.db"))

        # Web view
        self.web = QWebEngineView(self)
        self.setCentralWidget(self.web)

        # WebChannel / bridge
        self.bridge = WebBridge(self)
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        self.web.page().setWebChannel(self.channel)

        # Загрузить index.html
        web_dir = Path(__file__).resolve().parent.parent / "assets" / "web"
        index = web_dir / "index.html"
        self.web.load(QUrl.fromLocalFile(str(index)))

        # Serial
        self._worker: SerialWorker | None = None

        # Статус-бар
        self.status_port = QLabel("Порт: нет")
        self.status_queue = QLabel("Queue: —")
        self.status_active = QLabel("Активных: 0")
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(180)
        self.port_combo.activated.connect(self._on_port_selected)

        self.statusBar().addWidget(self.status_port)
        self.statusBar().addWidget(self.status_queue)
        self.statusBar().addWidget(self.status_active)
        self.statusBar().addWidget(QWidget(), 1)  # spacer
        self.statusBar().addWidget(self.port_combo)

        # Инициализация портов
        self._refresh_ports()

        # Bridge: сохраняем в repo и транслируем в JS
        self.bridge.positionReceived.connect(self._on_position)

    def _refresh_ports(self):
        """Заполняет комбобокс портами; если ровно 1 — подключаемся."""
        self.port_combo.clear()
        try:
            import serial.tools.list_ports
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            ports = []

        self.port_combo.addItem("Выбрать порт…")
        for p in ports:
            self.port_combo.addItem(p)

        if len(ports) == 1:
            self._connect_serial(ports[0])

    def _on_port_selected(self, index: int):
        if index <= 0:
            return
        port = self.port_combo.itemText(index)
        self._connect_serial(port)

    def _connect_serial(self, port: str):
        if self._worker is not None:
            self._worker.stop()
            self._worker = None

        self._worker = SerialWorker(port, baud=115200, parent=self)
        self._worker.position.connect(self._handle_position)
        self._worker.queue_size.connect(self._handle_queue_size)
        self._worker.error.connect(self._handle_serial_error)
        self._worker.start()

        self.status_port.setText(f"Порт: {port}")
        self.status_port.setStyleSheet("color: green;")

    def _handle_position(self, pos: dict):
        # Добавляем ts и сохраняем
        pos = dict(pos)
        pos["ts"] = time.time()
        try:
            self.repo.add_position(
                tracker_id=pos.get("id", "unknown"),
                lat=float(pos.get("lat", 0)),
                lon=float(pos.get("lon", 0)),
                alt=float(pos.get("altitude")) if "altitude" in pos else None,
                batt=float(pos.get("batt")) if "batt" in pos else None,
                voltage=float(pos.get("voltage")) if "voltage" in pos else None,
                sos=int(pos.get("sos", 0)) if "sos" in pos else None,
                ts=pos["ts"],
            )
        except Exception as exc:
            print(f"repo error: {exc}", file=sys.stderr)

        self.bridge.pushPosition(pos)
        self._update_active_status()

    def _on_position(self, pos: dict):
        """Заглушка-слот: positionReceived уже транслирован в JS."""
        pass

    def _handle_queue_size(self, size: int):
        self.status_queue.setText(f"Queue: {size}")

    def _handle_serial_error(self, msg: str):
        self.status_port.setText(f"Порт: ошибка")
        self.status_port.setStyleSheet("color: red;")
        print(msg, file=sys.stderr)

    def _update_active_status(self):
        active = self.repo.active_trackers(max_age_s=300)
        self.status_active.setText(f"Активных: {len(active)}")

    def closeEvent(self, event):
        if self._worker is not None:
            self._worker.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()
