"""Главное окно приложения MeshTrack.

Фаза 1: карта на QtWebEngine + WebChannel + SerialWorker + Repository.
"""
import logging
import os
import platform
import sys
import time
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .logutil import QtLogHandler, setup_logging
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


def format_age(ts: float | None) -> str:
    """Форматирует 'время назад' для таблицы трекеров."""
    if ts is None:
        return "—"
    dt = max(0, int(time.time() - ts))
    if dt < 60:
        return f"{dt} с"
    return f"{dt // 60} мин"


class TrackerPanel(QWidget):
    """Правая панель: список активных трекеров."""

    COLUMNS = ["ID", "Высота", "Заряд", "Напр.", "Обновлён"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._trackers: dict[str, dict] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.title = QLabel("Трекеры")
        self.title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.title)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

    def update_tracker(self, pos: dict):
        """Обновляет или добавляет строку трекера по позиции."""
        tracker_id = pos.get("id")
        if not tracker_id:
            return
        self._trackers[tracker_id] = pos
        self._refresh()

    def _refresh(self):
        # Сортировка по свежести (ts DESC), при равенстве — по ID
        ordered = sorted(
            self._trackers.items(),
            key=lambda item: (item[1].get("ts") or 0, item[0]),
            reverse=True,
        )
        self.table.setRowCount(len(ordered))
        for row, (tracker_id, pos) in enumerate(ordered):
            alt = pos.get("altitude")
            batt = pos.get("batt")
            voltage = pos.get("voltage")
            ts = pos.get("ts")

            def _float(val):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None

            alt_f = _float(alt)
            batt_f = _float(batt)
            voltage_f = _float(voltage)

            items = [
                QTableWidgetItem(str(tracker_id)),
                QTableWidgetItem(f"{alt_f:.0f} м" if alt_f is not None else "—"),
                QTableWidgetItem(f"{batt_f:.0f}%" if batt_f is not None else "—"),
                QTableWidgetItem(f"{(voltage_f / 1000):.2f} В" if voltage_f is not None else "—"),
                QTableWidgetItem(format_age(ts)),
            ]
            for col, item in enumerate(items):
                self.table.setItem(row, col, item)


class MainWindow(QMainWindow):
    def __init__(self, debug: bool = False):
        super().__init__()
        self.setWindowTitle("MeshTrack")
        self.resize(1400, 850)

        # Данные
        data_dir = app_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)

        # Логирование
        log_level = logging.DEBUG if debug else logging.INFO
        self.logger = setup_logging(data_dir / "meshtrack.log", level=log_level)
        self.qt_log_handler = QtLogHandler(self)
        self.logger.addHandler(self.qt_log_handler)

        self.repo = Repository(str(data_dir / "meshtrack.db"))
        self.logger.info("База данных: %s", data_dir / "meshtrack.db")

        # Центральная область: карта + панель трекеров
        central = QWidget()
        self.setCentralWidget(central)
        hbox = QVBoxLayout(central)
        hbox.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Horizontal)
        hbox.addWidget(self.splitter)

        # Web view
        self.web = QWebEngineView()
        self.splitter.addWidget(self.web)

        # Панель трекеров
        self.tracker_panel = TrackerPanel()
        self.tracker_panel.setMinimumWidth(280)
        self.tracker_panel.setMaximumWidth(450)
        self.splitter.addWidget(self.tracker_panel)
        self.splitter.setSizes([1100, 300])

        # Логирование загрузки
        page = self.web.page()
        page.loadFinished.connect(self._on_web_load_finished)

        # WebChannel / bridge
        self.bridge = WebBridge(self)
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        page.setWebChannel(self.channel)

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

        # Dock-виджет с логом
        self.log_dock = QDockWidget("Лог", self)
        self.log_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(500)
        self.log_dock.setWidget(self.log_edit)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
        self.qt_log_handler.logRecord.connect(self.log_edit.appendPlainText)

        # Инициализация портов
        self._refresh_ports()

    def _on_web_load_finished(self, ok: bool):
        self.logger.info("WebView loadFinished ok=%s", ok)

    def _refresh_ports(self):
        """Заполняет комбобокс портами; если ровно 1 — подключаемся."""
        self.port_combo.clear()
        try:
            import serial.tools.list_ports
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            self.logger.exception("Не удалось получить список портов")
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

        self.logger.info("Подключение к порту %s", port)
        self._worker = SerialWorker(port, baud=115200, parent=self)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.position.connect(self._handle_position)
        self._worker.queue_size.connect(self._handle_queue_size)
        self._worker.error.connect(self._handle_serial_error)
        self._worker.raw_line.connect(self._handle_raw_line)
        self._worker.start()

        self.status_port.setText(f"Порт: {port}")
        self.status_port.setStyleSheet("color: green;")

    def _on_worker_finished(self):
        self.logger.info("SerialWorker завершён")
        self.status_port.setText("Порт: отключён")
        self.status_port.setStyleSheet("color: gray;")

    def _handle_position(self, pos: dict):
        # Добавляем ts и сохраняем
        pos = dict(pos)
        pos["ts"] = time.time()
        self.logger.info(
            "Позиция от %s: lat=%s lon=%s alt=%s batt=%s%%",
            pos.get("id"),
            pos.get("lat"),
            pos.get("lon"),
            pos.get("altitude", "—"),
            pos.get("batt", "—"),
        )
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
        except Exception:
            self.logger.exception("Ошибка сохранения позиции в БД")

        self.tracker_panel.update_tracker(pos)
        self.bridge.pushPosition(pos)
        self._update_active_status()

    def _handle_queue_size(self, size: int):
        self.status_queue.setText(f"Queue: {size}")

    def _handle_serial_error(self, msg: str):
        self.status_port.setText("Порт: ошибка")
        self.status_port.setStyleSheet("color: red;")
        self.logger.error("Serial error: %s", msg)

    def _handle_raw_line(self, line: str):
        self.logger.debug("RAW: %s", line)

    def _update_active_status(self):
        active = self.repo.active_trackers(max_age_s=300)
        self.status_active.setText(f"Активных: {len(active)}")

    def closeEvent(self, event):
        self.logger.info("Закрытие приложения")
        if self._worker is not None:
            self._worker.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    win.raise_()
    win.activateWindow()
    return app.exec()
