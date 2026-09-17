"""Главное окно приложения MeshTrack.

Фаза 1: карта на QtWebEngine + WebChannel + SerialWorker + Repository.
Фаза 5: диалог настроек (Traccar, serial, retention), экспорт GPX/CSV.
"""

import logging
import os
import platform
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QDateTime, QTime, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .demo import DemoWorker, demo_base_point, seed_demo_history
from .derivation import derive
from .exporter import collect_tracks, export_csv, export_gpx
from .first_run_wizard import run_download_map_wizard
from .licenses_dialog import LicensesDialog
from .logutil import QtLogHandler, setup_logging
from .map_dialog import MapManagerDialog
from .mapscheme import install_map_handler
from .publisher import TraccarPublisher
from .repository import Repository
from .serial_worker import SerialWorker
from .settings import Settings
from .webbridge import WebBridge

# Палитра трекеров (PROJECT.md §5)
PALETTE = [
    "#e6194b",
    "#3cb44b",
    "#ffe119",
    "#4363d8",
    "#f58231",
    "#911eb4",
    "#46f0f0",
    "#f032e6",
    "#bfef45",
    "#3cb44b",
    "#808000",
    "#9a6324",
]

BAUD_CHOICES = ["9600", "19200", "38400", "57600", "115200", "230400"]

# Возраст, после которого точка считается устаревшей (PROJECT.md §5)
STALE_AGE_S = 20 * 60


def is_stale(ts: float, now: float | None = None) -> bool:
    """True, если данным больше STALE_AGE_S секунд."""
    if ts is None:
        return True
    now = time.time() if now is None else now
    return (now - ts) > STALE_AGE_S


def color_for_id(tracker_id: str) -> str:
    """Детерминированный цвет трекера по его id (совместим с JS)."""
    h = 0
    for ch in tracker_id:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return PALETTE[h % len(PALETTE)]


def build_restored_positions(
    repo: Repository,
    track_history_seconds: int = 600,
    now: float | None = None,
) -> list[dict]:
    """Восстанавливает последние позиции трекеров из истории для старта.

    Берёт все известные tracker_id, для каждого — последнюю позицию (`latest`)
    и короткий хвост истории для расчёта производных метрик (GS/курс/варио).
    Трекеры без позиций пропускаются. Возвращает список pos-dict в формате
    `_handle_position` (без name/color — их добавляет вызывающий код); поле
    `stale` отражает давность пакета.
    """
    now = time.time() if now is None else now
    restored: list[dict] = []
    for tracker_id in repo.all_trackers():
        last = repo.latest(tracker_id)
        if last is None:
            continue
        cache = repo.last_points(tracker_id, seconds=track_history_seconds)
        pos = {
            "id": tracker_id,
            "lat": float(last["lat"]),
            "lon": float(last["lon"]),
            "altitude": last["alt"],
            "batt": last["batt"],
            "voltage": last["voltage"],
            "sos": int(last["sos"] or 0),
            "ts": last["ts"],
            "recv_ts": last["recv_ts"],
        }
        pos.update(derive(cache))
        pos["stale"] = is_stale(pos["ts"], now)
        restored.append(pos)
    restored.sort(key=lambda p: p.get("ts") or 0, reverse=True)
    return restored


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


class ClickableLabel(QLabel):
    """QLabel, испускающий clicked при клике левой кнопкой мыши."""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TrackerPanel(QWidget):
    """Правая панель: список активных трекеров."""

    trackerClicked = Signal(str)
    trackerDoubleClicked = Signal(str)

    COLUMNS = [
        "",
        "ID",
        "Скорость",
        "Курс",
        "Варио",
        "Высота",
        "Заряд",
        "Напр.",
        "Обновлён",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._trackers: dict[str, dict] = {}
        self._row_ids: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.title = QLabel("Трекеры")
        self.title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.title)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 24)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
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
        self._row_ids = [tid for tid, _ in ordered]
        self.table.setRowCount(len(ordered))
        for row, (tracker_id, pos) in enumerate(ordered):
            color = pos.get("color") or color_for_id(tracker_id)
            alt = pos.get("altitude")
            batt = pos.get("batt")
            voltage = pos.get("voltage")
            ts = pos.get("ts")
            gs = pos.get("gs_kmh")
            course = pos.get("course_deg")
            vario = pos.get("vario_ms")
            trend = pos.get("trend") or "—"

            def _float(val):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None

            alt_f = _float(alt)
            batt_f = _float(batt)
            voltage_f = _float(voltage)
            gs_f = _float(gs)
            course_f = _float(course)
            vario_f = _float(vario)

            stale = pos.get("stale")
            if stale is None:
                stale = is_stale(ts)

            label = str(pos.get("name") or tracker_id)

            chip = QTableWidgetItem()
            chip.setBackground(QColor(color))
            chip.setFlags(chip.flags() & ~Qt.ItemIsSelectable)
            chip.setToolTip(f"Цвет трекера {label}")

            age_text = format_age(ts)
            if stale:
                age_text += " (!)"
            age_item = QTableWidgetItem(age_text)
            if stale:
                age_item.setForeground(QColor("#808080"))

            name_item = QTableWidgetItem(label)
            if pos.get("name"):
                name_item.setToolTip(f"ID: {tracker_id}")

            items = [
                chip,
                name_item,
                QTableWidgetItem(f"{gs_f:.1f}" if gs_f is not None else "—"),
                QTableWidgetItem(f"{course_f:.0f}°" if course_f is not None else "—"),
                QTableWidgetItem(
                    f"{vario_f:+.1f} {trend}" if vario_f is not None else "—"
                ),
                QTableWidgetItem(f"{alt_f:.0f} м" if alt_f is not None else "—"),
                QTableWidgetItem(f"{batt_f:.0f}%" if batt_f is not None else "—"),
                QTableWidgetItem(
                    f"{(voltage_f / 1000):.2f} В" if voltage_f is not None else "—"
                ),
                age_item,
            ]
            for col, item in enumerate(items):
                self.table.setItem(row, col, item)

    def _on_cell_clicked(self, row: int, _column: int):
        if 0 <= row < len(self._row_ids):
            self.trackerClicked.emit(self._row_ids[row])

    def _on_cell_double_clicked(self, row: int, _column: int):
        if 0 <= row < len(self._row_ids):
            self.trackerDoubleClicked.emit(self._row_ids[row])


class SettingsDialog(QDialog):
    """Диалог настроек: Traccar, serial-порт/baud, retention, экспорт.

    Кнопки экспорта вызывают `export_cb("gpx"|"csv")` — обработчик живёт в
    MainWindow (там есть repo и текущий фильтр истории).
    """

    def __init__(self, settings: Settings, export_cb, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        # --- Traccar ---
        traccar_box = QGroupBox("Traccar (опция)")
        traccar_layout = QVBoxLayout(traccar_box)
        self.traccar_check = QCheckBox("Отправлять позиции на free-gps.ru:5055")
        self.traccar_check.setChecked(settings.traccar_on)
        traccar_layout.addWidget(self.traccar_check)
        traccar_hint = QLabel("По умолчанию выключено; при включении нужен интернет.")
        traccar_hint.setEnabled(False)
        traccar_layout.addWidget(traccar_hint)
        layout.addWidget(traccar_box)

        # --- Serial ---
        serial_box = QGroupBox("Приёмник (serial)")
        serial_form = QFormLayout(serial_box)

        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        ports = self._detect_ports()
        current_port = settings.port_pref
        if current_port and current_port not in ports:
            self.port_combo.addItem(current_port)
        self.port_combo.addItems(ports)
        if current_port:
            self.port_combo.setCurrentText(current_port)

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(BAUD_CHOICES)
        self.baud_combo.setCurrentText(str(settings.baud))

        serial_form.addRow("Порт:", self.port_combo)
        serial_form.addRow("Baud:", self.baud_combo)
        layout.addWidget(serial_box)

        # --- Данные ---
        data_box = QGroupBox("Данные")
        data_form = QFormLayout(data_box)

        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 3650)
        self.retention_spin.setSuffix(" дн.")
        self.retention_spin.setValue(max(1, settings.retention_days))
        data_form.addRow("Хранить историю:", self.retention_spin)

        export_row = QHBoxLayout()
        gpx_btn = QPushButton("Экспорт GPX…")
        csv_btn = QPushButton("Экспорт CSV…")
        gpx_btn.setToolTip("Все трекеры за период текущего фильтра истории")
        csv_btn.setToolTip("Все трекеры за период текущего фильтра истории")
        gpx_btn.clicked.connect(lambda: export_cb("gpx"))
        csv_btn.clicked.connect(lambda: export_cb("csv"))
        export_row.addWidget(gpx_btn)
        export_row.addWidget(csv_btn)
        export_row.addStretch(1)
        data_form.addRow("Экспорт треков:", export_row)
        layout.addWidget(data_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _detect_ports() -> list[str]:
        try:
            import serial.tools.list_ports

            return [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            return []

    def values(self) -> dict:
        """Возвращает введённые значения для применения в MainWindow."""
        baud = 115200
        try:
            baud_value = int(self.baud_combo.currentText().strip())
            if baud_value > 0:
                baud = baud_value
        except ValueError:
            pass
        return {
            "traccar_on": self.traccar_check.isChecked(),
            "port_pref": self.port_combo.currentText().strip(),
            "baud": baud,
            "retention_days": self.retention_spin.value(),
        }


class MainWindow(QMainWindow):
    def __init__(self, debug: bool = False, demo: bool = False):
        super().__init__()
        self.setWindowTitle("MeshTrack Desktop")
        self.resize(1400, 850)

        self._demo = bool(demo)
        self._demo_worker: DemoWorker | None = None
        self._demo_seeded = False

        # Данные
        self.data_dir = app_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Настройки
        self.settings = Settings(self.data_dir / "config.json")
        try:
            self.settings.save()
        except Exception:
            pass  # логирование ещё не настроено

        # Логирование
        log_level = logging.DEBUG if debug else logging.INFO
        self.logger = setup_logging(self.data_dir / "meshtrack.log", level=log_level)
        self.qt_log_handler = QtLogHandler(self)
        self.logger.addHandler(self.qt_log_handler)

        # В демо-режиме используется отдельная БД, чтобы не засорять историю.
        db_name = "meshtrack-demo.db" if self._demo else "meshtrack.db"
        self.repo = Repository(str(self.data_dir / db_name))
        self.logger.info("База данных: %s", self.data_dir / db_name)
        if self._demo:
            self.logger.warning(
                "ДЕМО-РЕЖИМ: тестовые данные (%s); отключается запуском без "
                "--demo / MESHTRACK_DEMO=1",
                db_name,
            )

        # Traccar (опция, по умолчанию выключена — enqueue будет no-op).
        # В демо-режиме принудительно выключен, чтобы моковые точки не уходили
        # на free-gps.ru.
        self.publisher = TraccarPublisher(
            enable=self.settings.traccar_on and not self._demo, logger=self.logger
        )

        # Очистка истории по retention_days
        try:
            purged = self.repo.purge_old(self.settings.retention_days)
            if purged:
                self.logger.info(
                    "Удалено %d старых позиций (retention=%d дней)",
                    purged,
                    self.settings.retention_days,
                )
        except Exception:
            self.logger.exception("Ошибка очистки старой истории")

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

        # Кастомная схема map:// для офлайн-тайлов
        self._map_handler = install_map_handler(
            self.web.page().profile(), self.settings, parent=self
        )

        # Панель трекеров
        self.tracker_panel = TrackerPanel()
        self.tracker_panel.setMinimumWidth(300)
        self.tracker_panel.setMaximumWidth(480)
        self.tracker_panel.trackerClicked.connect(self._on_tracker_clicked)
        self.tracker_panel.trackerDoubleClicked.connect(self._on_tracker_double_clicked)
        self.splitter.addWidget(self.tracker_panel)
        self.splitter.setSizes([1100, 320])

        # Кэш последних точек в RAM: 10 минут истории для трека,
        # derivation внутри себя использует окно 60 с
        self._track_history_seconds = 600
        self._points_cache: dict[
            str, list[tuple[float, float, float, float | None]]
        ] = {}

        # Последние позиции трекеров — нужны для периодической перерисовки
        # маркеров, когда данные устаревают (без нового пакета)
        self._last_positions: dict[str, dict] = {}
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(30_000)
        self._stale_timer.timeout.connect(self._refresh_stale_states)
        self._stale_timer.start()

        # Фильтры треков и видимые треки (видимость управляется в JS)
        self._track_ts_from: float = 0.0
        self._track_ts_to: float = 0.0
        self._toolbar = None
        self._filter_combo = None
        self._color_combo = None

        # Логирование загрузки
        page = self.web.page()
        page.loadFinished.connect(self._on_web_load_finished)
        self._web_loaded = False

        # WebChannel / bridge
        self.bridge = WebBridge(repo=self.repo, settings=self.settings, parent=self)
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        page.setWebChannel(self.channel)

        # Восстанавливаем последние позиции из истории: левый список и маркеры
        # на карте появляются сразу, не дожидаясь живых пакетов.
        self._restore_trackers_from_history()

        # Загрузить index.html
        web_dir = Path(__file__).resolve().parent.parent / "assets" / "web"
        index = web_dir / "index.html"
        self.web.load(QUrl.fromLocalFile(str(index)))

        # Serial
        self._worker: SerialWorker | None = None
        self._last_data_ts: float | None = None
        self._first_data_logged: bool = False
        self._first_position_logged: bool = False
        self._data_silence_warned: bool = False
        self._data_timer = QTimer(self)
        self._data_timer.setInterval(5000)
        self._data_timer.timeout.connect(self._check_data_silence)

        # Статус-бар
        self.status_port = QLabel("Порт: нет")
        self.status_queue = QLabel("Queue: —")
        self.status_active = QLabel("Активных: 0")
        self.status_map = ClickableLabel("Карта: —")
        self.status_map.setCursor(Qt.PointingHandCursor)
        self.status_map.setToolTip("Управление картами")
        self.status_map.clicked.connect(self._open_map_manager)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(180)
        self.port_combo.activated.connect(self._on_port_selected)

        self.statusBar().addWidget(self.status_port)
        self.statusBar().addWidget(self.status_queue)
        self.statusBar().addWidget(self.status_active)
        self.statusBar().addWidget(self.status_map)
        self.statusBar().addWidget(QWidget(), 1)  # spacer
        self.statusBar().addWidget(self.port_combo)

        self._update_map_status()

        # Toolbar: фильтры истории и цвет треков
        self._setup_toolbar()

        # Меню
        self._setup_menu()

        # Dock-виджет с логом
        self.log_dock = QDockWidget("Лог", self)
        self.log_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(500)
        self.log_dock.setWidget(self.log_edit)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
        self.qt_log_handler.logRecord.connect(self.log_edit.appendPlainText)

        # Инициализация портов / демо-потока
        self._refresh_ports()
        if self._demo:
            self._start_demo()

    def _on_web_load_finished(self, ok: bool):
        self.logger.info("WebView loadFinished ok=%s", ok)
        if ok:
            self._web_loaded = True
            # Передать начальные фильтр и цветовой режим в JS
            self._push_filter_to_js()
            self._push_color_mode_to_js()

    def _setup_toolbar(self):
        toolbar = QToolBar("История и треки")
        self.addToolBar(toolbar)
        self._toolbar = toolbar

        toolbar.addWidget(QLabel("История:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["Сегодня", "Вчера", "Период…"])
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_combo)

        toolbar.addWidget(QLabel("Цвет трека:"))
        self._color_combo = QComboBox()
        self._color_combo.addItem("Палитра", "palette")
        self._color_combo.addItem("Высота", "altitude")
        self._color_combo.addItem("Варио", "vario")
        index = self._color_combo.findData(self.settings.track_color_mode)
        self._color_combo.blockSignals(True)
        self._color_combo.setCurrentIndex(index if index >= 0 else 0)
        self._color_combo.blockSignals(False)
        self._color_combo.currentIndexChanged.connect(self._on_color_mode_changed)
        toolbar.addWidget(self._color_combo)

        clear_btn = QPushButton("Очистить историю")
        clear_btn.setToolTip("Удалить все сохранённые позиции")
        clear_btn.clicked.connect(self._on_clear_history)
        toolbar.addWidget(clear_btn)

        # Начальное значение фильтра — сегодня
        self._apply_filter_range(0)

    def _setup_menu(self):
        """Главное меню приложения."""
        menu_bar = self.menuBar()

        map_menu = menu_bar.addMenu("Карта")
        download_action = map_menu.addAction("Загрузить новую карту…")
        download_action.setStatusTip("Скачать дополнительный регион для офлайн-карт")
        download_action.triggered.connect(self._on_download_map)
        manage_action = map_menu.addAction("Управление картами…")
        manage_action.setStatusTip("Список карт, статусы, удаление, докачка")
        manage_action.triggered.connect(self._open_map_manager)

        data_menu = menu_bar.addMenu("Данные")
        settings_action = QAction("Настройки…", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._open_settings)
        data_menu.addAction(settings_action)
        data_menu.addSeparator()
        gpx_action = data_menu.addAction("Экспорт GPX…")
        gpx_action.triggered.connect(lambda: self._export_tracks("gpx"))
        csv_action = data_menu.addAction("Экспорт CSV…")
        csv_action.triggered.connect(lambda: self._export_tracks("csv"))
        data_menu.addSeparator()

        # Быстрое включение/выключение моковых данных без перезапуска.
        self._demo_action = QAction("Демо-режим (тестовые данные)", self)
        self._demo_action.setCheckable(True)
        self._demo_action.setStatusTip(
            "Моковые позиции вместо serial-приёмника; отключается снятием галки"
        )
        self._demo_action.setChecked(self._demo)
        self._demo_action.toggled.connect(self._on_demo_toggled)
        data_menu.addAction(self._demo_action)

        help_menu = menu_bar.addMenu("Помощь")
        about_action = help_menu.addAction("О программе")
        about_action.setStatusTip("Информация о MeshTrack Desktop")
        about_action.triggered.connect(self._show_about)
        licenses_action = help_menu.addAction("Лицензии компонентов")
        licenses_action.setStatusTip("Сторонние компоненты, версии и тексты лицензий")
        licenses_action.triggered.connect(self._show_licenses)

    def _show_about(self):
        """Диалог «О программе»."""
        from . import __version__

        text = (
            "<h3>MeshTrack Desktop</h3>"
            f"Версия {__version__}<br><br>"
            "Бесплатная программа для локального отображения данных, "
            "поступающих с приёмника LoRa-трекеров MeshTrack или Aglora.<br><br>"
            "Автор: Евгений Шлягин<br>"
            'Почта: <a href="mailto:shlyagin@gmail.com">shlyagin@gmail.com</a>'
        )
        QMessageBox.about(self, "О программе", text)

    def _show_licenses(self):
        """Диалог со списком сторонних компонентов и текстами лицензий."""
        LicensesDialog(self).exec()

    def _open_settings(self):
        """Диалог настроек: Traccar, serial, retention, экспорт."""
        dlg = SettingsDialog(
            self.settings,
            lambda fmt: self._export_tracks(fmt, parent=dlg),
            self,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        values = dlg.values()
        old_port = self.settings.port_pref
        old_baud = self.settings.baud
        retention_changed = values["retention_days"] != self.settings.retention_days

        self.settings.traccar_on = values["traccar_on"]
        self.settings.port_pref = values["port_pref"]
        self.settings.baud = values["baud"]
        self.settings.retention_days = values["retention_days"]
        try:
            self.settings.save()
        except Exception:
            self.logger.exception("Ошибка сохранения настроек")

        self.publisher.enable = self.settings.traccar_on and not self._demo
        self.logger.info(
            "Настройки: Traccar=%s, порт=%s, baud=%d, retention=%d дн.",
            "вкл" if self.settings.traccar_on else "выкл",
            self.settings.port_pref or "—",
            self.settings.baud,
            self.settings.retention_days,
        )

        if retention_changed:
            try:
                purged = self.repo.purge_old(self.settings.retention_days)
                if purged:
                    self.logger.info("Удалено старых позиций: %d", purged)
            except Exception:
                self.logger.exception("Ошибка очистки старой истории")

        port_changed = self.settings.port_pref != old_port
        baud_changed = self.settings.baud != old_baud
        if self._worker is not None and (port_changed or baud_changed):
            if self.settings.port_pref:
                self.logger.info("Переподключение к %s", self.settings.port_pref)
                self._connect_serial(self.settings.port_pref)

    def _export_tracks(self, fmt: str, parent=None):
        """Экспорт всех трекеров за текущий фильтр истории в GPX/CSV."""
        parent = parent or self
        # Пересчитываем диапазон: «Сегодня»/«Вчера» должны включать свежие точки.
        # Пушим в JS, чтобы видимая карта соответствовала экспортируемому периоду.
        self._track_ts_from, self._track_ts_to = self._current_filter_range()
        if self._web_loaded:
            self._push_filter_to_js()
        ts_from = self._track_ts_from or None
        ts_to = self._track_ts_to or None
        try:
            tracks = collect_tracks(self.repo, ts_from=ts_from, ts_to=ts_to)
        except Exception:
            self.logger.exception("Ошибка выборки треков для экспорта")
            QMessageBox.critical(parent, "Экспорт", "Не удалось прочитать историю.")
            return

        total = sum(len(points) for points in tracks.values())
        range_str = "{} — {}".format(
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts_from))
            if ts_from
            else "…",
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts_to)) if ts_to else "…",
        )
        if total == 0:
            self.logger.info(
                "Экспорт %s: нет данных за период %s", fmt.upper(), range_str
            )
            QMessageBox.information(
                parent, "Экспорт", "За выбранный период нет данных."
            )
            return
        self.logger.info(
            "Экспорт %s: период %s, трекеров %d, точек %d",
            fmt.upper(),
            range_str,
            len(tracks),
            total,
        )

        ext = fmt if fmt in ("gpx", "csv") else "gpx"
        start_dir = self.settings.exports_dir or str(self.data_dir)
        default_name = time.strftime("meshtrack_%Y%m%d_%H%M.") + ext
        file_filter = "GPX (*.gpx)" if ext == "gpx" else "CSV (*.csv)"
        path, _ = QFileDialog.getSaveFileName(
            parent, "Экспорт треков", str(Path(start_dir) / default_name), file_filter
        )
        if not path:
            return
        if not path.lower().endswith("." + ext):
            path += "." + ext

        try:
            if ext == "gpx":
                count = export_gpx(path, tracks)
            else:
                count = export_csv(path, tracks)
        except Exception:
            self.logger.exception("Ошибка экспорта %s", path)
            QMessageBox.critical(parent, "Экспорт", "Не удалось сохранить файл.")
            return

        self.settings.exports_dir = str(Path(path).parent)
        try:
            self.settings.save()
        except Exception:
            self.logger.exception("Ошибка сохранения настроек")
        self.logger.info("Экспортировано %s: %s (%d точек)", ext.upper(), path, count)

    def _on_download_map(self):
        """Открывает wizard для докачки карты."""
        ok = run_download_map_wizard(self.settings, self.data_dir / "maps", parent=self)
        if not ok:
            return
        map_id = self.settings.active_map_id
        if map_id:
            try:
                self.settings.save()
                self.logger.info("Активная карта: %s", map_id)
                self._update_map_status()
                self.bridge.setActiveMapId(map_id)
            except Exception:
                self.logger.exception("Ошибка сохранения настроек карты")

    def _open_map_manager(self):
        """Открывает диалог управления картами."""
        dlg = MapManagerDialog(
            self.settings, self.data_dir / "maps", bridge=self.bridge, parent=self
        )
        dlg.exec()
        try:
            self.settings.save()
        except Exception:
            self.logger.exception("Ошибка сохранения настроек")
        self._update_map_status()
        map_id = self.settings.active_map_id
        try:
            self.bridge.setActiveMapId(map_id or "")
        except Exception:
            self.logger.exception("Ошибка смены активной карты")

    def _on_filter_changed(self, index: int):
        self._apply_filter_range(index)

    def _current_filter_range(self, index: int | None = None) -> tuple[float, float]:
        """Актуальный диапазон фильтра.

        Для «Сегодня»/«Вчера» правый край пересчитывается как now — иначе
        позиции, принятые после запуска/смены фильтра, не попадают в выборку.
        """
        if index is None:
            index = self._filter_combo.currentIndex() if self._filter_combo else 0
        now = QDateTime.currentDateTime()
        if index == 1:  # Вчера
            today = QDateTime(now.date(), QTime(0, 0, 0))
            return today.addDays(-1).toSecsSinceEpoch(), today.toSecsSinceEpoch()
        if index == 2:  # Период… (задан в диалоге)
            return self._track_ts_from, self._track_ts_to
        start = QDateTime(now.date(), QTime(0, 0, 0))
        return start.toSecsSinceEpoch(), now.toSecsSinceEpoch()

    def _apply_filter_range(self, index: int):
        if index == 2:  # Период
            self._select_period_dialog()
            return
        self._track_ts_from, self._track_ts_to = self._current_filter_range(index)
        if self._web_loaded:
            self._push_filter_to_js()

    def _select_period_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Выберите период")
        layout = QVBoxLayout(dlg)

        now = QDateTime.currentDateTime()
        from_edit = QDateTimeEdit(now.addDays(-1))
        from_edit.setCalendarPopup(True)
        from_edit.setDisplayFormat("dd.MM.yyyy hh:mm")
        to_edit = QDateTimeEdit(now)
        to_edit.setCalendarPopup(True)
        to_edit.setDisplayFormat("dd.MM.yyyy hh:mm")

        form = QHBoxLayout()
        form.addWidget(QLabel("С:"))
        form.addWidget(from_edit)
        form.addWidget(QLabel("По:"))
        form.addWidget(to_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() == QDialog.Accepted:
            self._track_ts_from = from_edit.dateTime().toSecsSinceEpoch()
            self._track_ts_to = to_edit.dateTime().toSecsSinceEpoch()
            self._push_filter_to_js()
        else:
            # Вернуть выбор на предыдущий активный фильтр
            self._filter_combo.blockSignals(True)
            self._filter_combo.setCurrentIndex(0)
            self._filter_combo.blockSignals(False)
            self._apply_filter_range(0)

    def _push_filter_to_js(self):
        self.web.page().runJavaScript(
            f"setTrackFilter({self._track_ts_from}, {self._track_ts_to})"
        )

    def _push_color_mode_to_js(self):
        mode = self._color_combo.currentData()
        if mode:
            self.web.page().runJavaScript(f'setTrackColorMode("{mode}")')

    def _on_color_mode_changed(self, index: int):
        mode = self._color_combo.itemData(index)
        if mode:
            self.settings.track_color_mode = mode
            try:
                self.settings.save()
            except Exception:
                self.logger.exception("Ошибка сохранения настроек")
            if self._web_loaded:
                self._push_color_mode_to_js()

    def _refresh_visible_tracks(self):
        self.web.page().runJavaScript("refreshVisibleTracks()")

    def _on_clear_history(self):
        reply = QMessageBox.question(
            self,
            "Очистить историю",
            "Удалить все сохранённые позиции трекеров?\nТекущие маркеры останутся на карте до закрытия.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                deleted = self.repo.clear_all_positions()
                self._points_cache.clear()
                self.logger.info("История очищена, удалено позиций: %d", deleted)
                self.bridge.clearHistory()
            except Exception:
                self.logger.exception("Ошибка очистки истории")

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

        if self._demo:
            return  # в демо-режиме serial не подключаем

        # Автоподключение: сохранённый port_pref, иначе единственный порт
        pref = self.settings.port_pref
        if pref and pref in ports:
            index = self.port_combo.findText(pref)
            if index > 0:
                self.port_combo.setCurrentIndex(index)
            self._connect_serial(pref)
        elif len(ports) == 1:
            self._connect_serial(ports[0])

    def _on_port_selected(self, index: int):
        if index <= 0:
            return
        port = self.port_combo.itemText(index)
        self.settings.port_pref = port
        try:
            self.settings.save()
        except Exception:
            self.logger.exception("Ошибка сохранения настроек")
        self._connect_serial(port)

    def _attach_worker(self, worker):
        """Подключает сигналы потока данных (SerialWorker или DemoWorker)."""
        worker.finished.connect(self._on_worker_finished)
        worker.position.connect(self._handle_position)
        worker.queue_size.connect(self._handle_queue_size)
        worker.error.connect(self._handle_serial_error)
        worker.raw_line.connect(self._handle_raw_line)
        worker.start()

    def _connect_serial(self, port: str):
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        self._stop_demo()
        if self._demo_action.isChecked():
            self._demo_action.blockSignals(True)
            self._demo_action.setChecked(False)
            self._demo_action.blockSignals(False)

        baud = self.settings.baud
        self.logger.info("Подключение к порту %s (baud=%d)", port, baud)
        self._last_data_ts = time.time()
        self._first_data_logged = False
        self._first_position_logged = False
        self._data_silence_warned = False
        self._data_timer.start()

        self._worker = SerialWorker(port, baud=baud, parent=self)
        self._attach_worker(self._worker)

        self.status_port.setText(f"Порт: {port}")
        self.status_port.setStyleSheet("color: green;")

    def _on_demo_toggled(self, enabled: bool):
        if enabled:
            self._start_demo()
        else:
            self._stop_demo()

    def _start_demo(self):
        """Запускает генератор моковых позиций вместо serial-порта."""
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        self._stop_demo()

        base_lat, base_lon = demo_base_point(self.settings)
        if not self._demo:
            self.logger.warning(
                "Демо-режим включён вручную: тестовые точки пишутся в %s",
                Path(self.repo.db_path).name,
            )
        if not self._demo_seeded:
            # Заполнение истории — в фоне, чтобы не тормозить запуск окна.
            self._demo_seeded = True
            threading.Thread(
                target=self._seed_demo_history,
                args=(base_lat, base_lon),
                daemon=True,
            ).start()

        self._last_data_ts = time.time()
        self._first_data_logged = False
        self._first_position_logged = False
        self._data_silence_warned = False
        self._data_timer.start()

        self._demo_worker = DemoWorker(
            base_lat=base_lat, base_lon=base_lon, parent=self
        )
        self._attach_worker(self._demo_worker)

        self.status_port.setText("Порт: ДЕМО")
        self.status_port.setStyleSheet("color: #b8860b;")
        self.logger.info(
            "Демо-режим включён: генерируются тестовые позиции (центр %.5f, %.5f)",
            base_lat,
            base_lon,
        )

    def _seed_demo_history(self, base_lat: float, base_lon: float):
        """Фоновое заполнение демо-истории (вызывается из потока)."""
        try:
            added = seed_demo_history(self.repo, base_lat=base_lat, base_lon=base_lon)
            if added:
                self.logger.info("Демо-история: добавлено %d точек", added)
        except Exception:
            self.logger.exception("Ошибка заполнения демо-истории")

    def _stop_demo(self):
        """Останавливает демо-поток (если запущен)."""
        if self._demo_worker is None:
            return
        self._demo_worker.stop()
        self._demo_worker = None
        self._data_timer.stop()
        self.status_port.setText("Порт: нет")
        self.status_port.setStyleSheet("color: gray;")
        self.logger.info("Демо-режим выключен")

    def _on_worker_finished(self):
        self.logger.info("Поток данных завершён")
        self._data_timer.stop()
        self.status_port.setText("Порт: отключён")
        self.status_port.setStyleSheet("color: gray;")

    def _handle_position(self, pos: dict):
        # ts — время с устройства; recv_ts — время приёма на ПК
        pos = dict(pos)
        recv_ts = time.time()
        device_ts = pos.get("device_ts")
        pos["ts"] = device_ts if device_ts is not None else recv_ts
        pos["recv_ts"] = recv_ts
        tracker_id = pos.get("id", "unknown")

        lat = float(pos.get("lat", 0))
        lon = float(pos.get("lon", 0))
        alt = float(pos.get("altitude")) if "altitude" in pos else None
        batt = float(pos.get("batt")) if "batt" in pos else None
        voltage = float(pos.get("voltage")) if "voltage" in pos else None
        sos = int(pos.get("sos", 0)) if "sos" in pos else None

        device_ts_str = pos.get("timestamp") or "N/A"
        recv_ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(recv_ts))
        self.logger.info(
            "Позиция от %s: lat=%s lon=%s alt=%s batt=%s%% "
            "(время устройства: %s, принято: %s)",
            tracker_id,
            lat,
            lon,
            alt if alt is not None else "—",
            batt if batt is not None else "—",
            device_ts_str,
            recv_ts_str,
        )
        try:
            self.repo.add_position(
                tracker_id=tracker_id,
                lat=lat,
                lon=lon,
                alt=alt,
                batt=batt,
                voltage=voltage,
                sos=sos,
                ts=pos["ts"],
                recv_ts=recv_ts,
            )
        except Exception:
            self.logger.exception("Ошибка сохранения позиции в БД")

        # Обновляем RAM-кэш точек (10 минут для будущего трека)
        cache = self._points_cache.setdefault(tracker_id, [])
        cache.append((pos["ts"], lat, lon, alt))
        cutoff = pos["ts"] - self._track_history_seconds
        cache = [p for p in cache if p[0] >= cutoff]
        cache.sort(key=lambda p: p[0])
        self._points_cache[tracker_id] = cache

        metrics = derive(self._points_cache[tracker_id])
        pos.update(metrics)
        pos["color"] = color_for_id(tracker_id)
        pos["stale"] = False
        self._last_positions[tracker_id] = pos

        if not self._first_position_logged:
            self.logger.info("Получена первая позиция от %s", tracker_id)
            self._first_position_logged = True

        self.tracker_panel.update_tracker(pos)
        self.bridge.pushPosition(pos)
        self.publisher.enqueue(pos)
        self._update_active_status()

    def _refresh_stale_states(self):
        """Раз в 30 с проверяет, не устарели ли сохранённые позиции."""
        now = time.time()
        for tracker_id, pos in self._last_positions.items():
            if pos.get("stale") or not is_stale(pos.get("ts"), now):
                continue
            pos["stale"] = True
            self.logger.info("Трекер %s устарел", tracker_id)
            self.tracker_panel.update_tracker(pos)
            self.bridge.pushPosition(pos)

    def _handle_queue_size(self, size: int):
        self.status_queue.setText(f"Queue: {size}")

    def _handle_serial_error(self, msg: str):
        self.status_port.setText("Порт: ошибка")
        self.status_port.setStyleSheet("color: red;")
        self.logger.error("Serial error: %s", msg)

    def _active_worker(self):
        """Активный поток данных: serial или демо."""
        return self._worker or self._demo_worker

    def _handle_raw_line(self, line: str):
        self.logger.debug("RAW: %s", line)
        self._last_data_ts = time.time()
        self._data_silence_warned = False
        if not self._first_data_logged:
            worker = self._active_worker()
            self.logger.info(
                "Данные с устройства на порту %s поступают",
                worker.port if worker is not None else "?",
            )
            self._first_data_logged = True

    def _check_data_silence(self):
        worker = self._active_worker()
        if worker is None or not worker.isRunning():
            return
        if self._last_data_ts is None:
            return
        elapsed = time.time() - self._last_data_ts
        if elapsed > 60.0 and not self._data_silence_warned:
            self.logger.warning(
                "С порта %s не поступают данные %.0f с",
                worker.port,
                elapsed,
            )
            self._data_silence_warned = True

    def _update_active_status(self):
        active = self.repo.active_trackers(max_age_s=300)
        self.status_active.setText(f"Активных: {len(active)}")

    def _restore_trackers_from_history(self):
        """Заполняет левый список и bridge последними позициями из БД.

        Вызывается при старте; маркеры на карте появятся, когда JS заберёт
        список через getRestoredPositions() после подключения QWebChannel.
        """
        try:
            restored = build_restored_positions(
                self.repo, track_history_seconds=self._track_history_seconds
            )
        except Exception:
            self.logger.exception("Ошибка восстановления трекеров из истории")
            return
        self.bridge.restored_positions = restored
        for pos in restored:
            pos["color"] = color_for_id(pos["id"])
            self._last_positions[pos["id"]] = pos
            # Сидируем RAM-кэш точками истории, чтобы метрики (GS/курс/варио)
            # не обнулялись при первом живом пакете после старта.
            self._points_cache.setdefault(
                pos["id"],
                self.repo.last_points(pos["id"], seconds=self._track_history_seconds),
            )
            self.tracker_panel.update_tracker(pos)

    def _update_map_status(self):
        map_id = self.settings.active_map_id
        if not map_id:
            self.status_map.setText("Карта: нет")
            return
        path = self.settings.get_map_path(map_id)
        if not path or not Path(path).exists():
            self.status_map.setText(f"Карта: {map_id} (файл не найден)")
            return
        self.status_map.setText(f"Карта: {map_id}")

    def _on_tracker_clicked(self, tracker_id: str):
        # Клик по трекеру: центрируем карту и показываем трек (история).
        self.web.page().runJavaScript(
            f'centerTracker("{tracker_id}"); showTrack("{tracker_id}");'
        )

    def _on_tracker_double_clicked(self, tracker_id: str):
        # Двойной клик скрывает трек (повторный клик снова покажет).
        self.web.page().runJavaScript(f'hideTrack("{tracker_id}")')

    def closeEvent(self, event):
        self.logger.info("Закрытие приложения")
        self._stale_timer.stop()
        if self._worker is not None:
            self._worker.stop()
        if self._demo_worker is not None:
            self._demo_worker.stop()
        self.publisher.flush(timeout=1.0)
        self.publisher.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    win.raise_()
    win.activateWindow()
    return app.exec()
