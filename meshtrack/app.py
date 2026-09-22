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
from functools import partial
from pathlib import Path

from PySide6.QtCore import QDateTime, QRectF, QSize, QTime, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
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
    QInputDialog,
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .demo import DemoWorker, demo_base_point, seed_demo_history
from .derivation import derive
from .exporter import collect_tracks, export_csv, export_gpx
from .first_run_wizard import run_download_map_wizard
from .i18n import init_translator, pl
from .i18n import tr as _
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


def _pencil_icon(size: int = 18) -> QIcon:
    """Иконка карандаша (рисуется программно, без ресурсных файлов)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.translate(size / 2.0, size / 2.0)
    painter.rotate(45)
    w = 5.0
    painter.setPen(Qt.NoPen)
    # Ластик
    painter.setBrush(QColor("#e26d9c"))
    painter.drawRoundedRect(QRectF(-w / 2, -5.4, w, 1.5), 1.0, 1.0)
    # Обойма
    painter.setBrush(QColor("#b8b8b8"))
    painter.drawRoundedRect(QRectF(-w / 2, -4.0, w, 1.0), 0.5, 0.5)
    # Корпус
    painter.setBrush(QColor("#3cb44b"))
    painter.drawRoundedRect(QRectF(-w / 2, -3.0, w, 6.0), 0.8, 0.8)
    # Деревянный наконечник (грифель)
    tip = QPainterPath()
    tip.moveTo(-w / 2, -2.8)
    tip.lineTo(w / 2, -2.8)
    tip.lineTo(0.0, 5.1)
    tip.closeSubpath()
    painter.setBrush(QColor("#d9a066"))
    painter.drawPath(tip)
    # Грифель — точка на кончике
    painter.setBrush(QColor("#3a3a3a"))
    painter.drawEllipse(QRectF(-0.9, 4.2, 1.8, 2.0))
    painter.end()
    return QIcon(pm)


def _track_on_icon(size: int = 16) -> QIcon:
    """Иконка «трек включён»: ломаная-маршрут на прозрачном фоне.

    Белая линия с тёмным контуром — читается и на светлых, и на тёмных
    цветах палитры трекеров.
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    route = QPainterPath()
    route.moveTo(2.0, 13.0)
    route.lineTo(6.0, 8.5)
    route.lineTo(9.5, 11.5)
    route.lineTo(13.0, 4.5)
    painter.setPen(
        QPen(QColor(0, 0, 0, 110), 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    )
    painter.drawPath(route)
    painter.setPen(
        QPen(QColor(255, 255, 255), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    )
    painter.drawPath(route)
    painter.end()
    return QIcon(pm)


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
    names = repo.tracker_names()
    restored: list[dict] = []
    for tracker_id in repo.all_trackers():
        last = repo.latest(tracker_id)
        if last is None:
            continue
        cache = repo.last_points(tracker_id, seconds=track_history_seconds)
        pos = {
            "id": tracker_id,
            "name": names.get(tracker_id),
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
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "MeshTrack"
    return Path.home() / ".local" / "share" / "MeshTrack"


def format_age(ts: float | None) -> str:
    """Форматирует 'время назад' для таблицы трекеров.

    < 1 мин  -> "N с"
    < 2 ч    -> "N мин" / "X ч Y мин"
    < 2 дн   -> "X дн Y ч" / "X ч"
    >= 2 дн  -> "N дн"

    Уже ~2 ч и больше — без минут; 2 дня и больше — без часов.
    Единицы берутся из каталога перевода (локализуемо).
    """
    if ts is None:
        return "—"
    dt = max(0, int(time.time() - ts))

    days, rem = divmod(dt, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60

    if dt < 60:
        return f"{dt} {pl('с', dt)}"
    if dt < 7200:  # < 2 ч — показываем минуты
        if hours:
            return f"{hours} {pl('час', hours)} {minutes} {pl('минута', minutes)}"
        return f"{minutes} {pl('минута', minutes)}"
    if dt < 172800:  # < 2 дн — без минут
        if not days:
            return f"{hours} {pl('час', hours)}"
        hs = f" {hours} {pl('час', hours)}" if hours else ""
        return f"{days} {pl('день', days)}{hs}"
    return f"{days} {pl('день', days)}"


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
    renameTracker = Signal(str)
    deleteTracker = Signal(str)

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
        "",
    ]

    def _title(self) -> str:
        return _("Трекеры")

    def retranslate(self):
        """Обновляет заголовок и шапку таблицы после смены языка."""
        self.title.setText(self._title())
        self.table.setHorizontalHeaderLabels([_(c) for c in self.COLUMNS])
        self._refresh()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._trackers: dict[str, dict] = {}
        self._row_ids: list[str] = []
        # Состояние «трек показан» (зеркалится из JS) для индикатора в плашке.
        self._track_visible: dict[str, bool] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.title = QLabel(self._title())
        self.title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.title)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([_(c) for c in self.COLUMNS])
        header = self.table.horizontalHeader()
        # Колонки можно перетаскивать мышью; «Обновлён» занимает оставшееся
        # место, последняя (кнопка «✕» удаление) — фиксированной ширины.
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(len(self.COLUMNS) - 2, QHeaderView.Stretch)
        header.setSectionResizeMode(len(self.COLUMNS) - 1, QHeaderView.Fixed)
        default_widths = [24, 80, 60, 52, 58, 64, 56, 60, 100, 36]
        for col, width in enumerate(default_widths):
            self.table.setColumnWidth(col, width)
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
            chip.setToolTip(_("Цвет трекера {label}").format(label=label))
            if self._track_visible.get(tracker_id):
                # Трек включён — на плашке рисунок «маршрут».
                chip.setIcon(_track_on_icon())
                chip.setTextAlignment(Qt.AlignCenter)

            age_text = format_age(ts)
            if stale:
                age_text += " (!)"
            age_item = QTableWidgetItem(age_text)
            if stale:
                age_item.setForeground(QColor("#808080"))

            name_tip = f"ID: {tracker_id}" if pos.get("name") else None

            items = [
                chip,
                None,  # колонка ID — ячейка-виджет с именем и карандашом ниже
                QTableWidgetItem(f"{gs_f:.1f}" if gs_f is not None else "—"),
                QTableWidgetItem(f"{course_f:.0f}°" if course_f is not None else "—"),
                QTableWidgetItem(
                    f"{vario_f:+.1f} {trend}" if vario_f is not None else "—"
                ),
                QTableWidgetItem(f"{alt_f:.0f} {_('м')}" if alt_f is not None else "—"),
                QTableWidgetItem(f"{batt_f:.0f}%" if batt_f is not None else "—"),
                QTableWidgetItem(
                    f"{(voltage_f / 1000):.2f} {_('В')}"
                    if voltage_f is not None
                    else "—"
                ),
                age_item,
            ]
            for col, item in enumerate(items):
                if item is not None:
                    self.table.setItem(row, col, item)

            # Ячейка ID: псевдоним/имя слева, кнопка-карандаш (псевдоним) справа.
            id_widget = QWidget()
            id_lay = QHBoxLayout(id_widget)
            id_lay.setContentsMargins(2, 0, 2, 0)
            id_lay.setSpacing(3)
            name_lbl = QLabel(label)
            if name_tip:
                name_lbl.setToolTip(name_tip)
            rename_btn = QToolButton()
            rename_btn.setIcon(_pencil_icon())
            rename_btn.setIconSize(QSize(14, 14))
            rename_btn.setFixedSize(18, 18)
            rename_btn.setAutoRaise(True)
            rename_btn.setCursor(Qt.PointingHandCursor)
            rename_btn.setToolTip(
                _("Задать/изменить псевдоним трекера {label}").format(label=label)
            )
            rename_btn.clicked.connect(partial(self._on_rename_clicked, tracker_id))
            id_lay.addWidget(name_lbl)
            id_lay.addStretch(1)
            id_lay.addWidget(rename_btn)
            self.table.setCellWidget(row, 1, id_widget)

            del_btn = QPushButton("✕")
            del_btn.setFixedSize(28, 22)
            del_btn.setFlat(True)
            del_btn.setToolTip(
                _("Удалить все данные трекера {label}").format(label=label)
            )
            del_btn.clicked.connect(partial(self._on_delete_clicked, tracker_id))
            self.table.setCellWidget(row, len(self.COLUMNS) - 1, del_btn)

    def remove_tracker(self, tracker_id: str):
        """Удаляет трекер из списка."""
        if tracker_id in self._trackers:
            del self._trackers[tracker_id]
        self._track_visible.pop(tracker_id, None)
        self._refresh()

    def set_track_visible(self, tracker_id: str, shown: bool):
        """Обновляет индикатор «трек показан» на цветной плашке."""
        self._track_visible[tracker_id] = shown
        self._refresh()

    def _on_delete_clicked(self, tracker_id: str):
        self.deleteTracker.emit(tracker_id)

    def _on_rename_clicked(self, tracker_id: str):
        self.renameTracker.emit(tracker_id)

    def _on_cell_clicked(self, row: int, _column: int):
        # Одиночный клик — только центрирование карты (трек не включаем).
        if 0 <= row < len(self._row_ids):
            self.trackerClicked.emit(self._row_ids[row])

    def _on_cell_double_clicked(self, row: int, column: int):
        # Трек включается/выключается только двойным кликом по цветной плашке.
        if column == 0 and 0 <= row < len(self._row_ids):
            self.trackerDoubleClicked.emit(self._row_ids[row])


class SettingsDialog(QDialog):
    """Диалог настроек: Traccar, serial-порт/baud, retention, экспорт.

    Кнопки экспорта вызывают `export_cb("gpx"|"csv")` — обработчик живёт в
    MainWindow (там есть repo и текущий фильтр истории).
    """

    def __init__(self, settings: Settings, export_cb, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Настройки"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        # --- Язык интерфейса ---
        lang_box = QGroupBox(_("Язык"))
        lang_layout = QVBoxLayout(lang_box)
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Русский", "ru")
        self.lang_combo.addItem("English", "en")
        index = self.lang_combo.findData(settings.language)
        self.lang_combo.setCurrentIndex(index if index >= 0 else 0)
        lang_layout.addWidget(self.lang_combo)
        layout.addWidget(lang_box)

        # --- Traccar ---
        traccar_box = QGroupBox(_("Traccar (опция)"))
        traccar_layout = QVBoxLayout(traccar_box)
        self.traccar_check = QCheckBox(_("Отправлять позиции на free-gps.ru:5055"))
        self.traccar_check.setChecked(settings.traccar_on)
        traccar_layout.addWidget(self.traccar_check)
        traccar_hint = QLabel(
            _("По умолчанию выключено; при включении нужен интернет.")
        )
        traccar_hint.setEnabled(False)
        traccar_layout.addWidget(traccar_hint)
        layout.addWidget(traccar_box)

        # --- Serial ---
        serial_box = QGroupBox(_("Приёмник (serial)"))
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

        serial_form.addRow(_("Порт:"), self.port_combo)
        serial_form.addRow(_("Baud:"), self.baud_combo)
        layout.addWidget(serial_box)

        # --- Данные ---
        data_box = QGroupBox(_("Данные"))
        data_form = QFormLayout(data_box)

        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 3650)
        self.retention_spin.setSuffix(_(" дн."))
        self.retention_spin.setValue(max(1, settings.retention_days))
        data_form.addRow(_("Хранить историю:"), self.retention_spin)

        export_row = QHBoxLayout()
        gpx_btn = QPushButton(_("Экспорт GPX…"))
        csv_btn = QPushButton(_("Экспорт CSV…"))
        gpx_btn.setToolTip(_("Все трекеры за период текущего фильтра истории"))
        csv_btn.setToolTip(_("Все трекеры за период текущего фильтра истории"))
        gpx_btn.clicked.connect(lambda: export_cb("gpx"))
        csv_btn.clicked.connect(lambda: export_cb("csv"))
        export_row.addWidget(gpx_btn)
        export_row.addWidget(csv_btn)
        export_row.addStretch(1)
        data_form.addRow(_("Экспорт треков:"), export_row)
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
            "language": self.lang_combo.currentData(),
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
        init_translator(self.settings.language)

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
        self.tracker_panel.renameTracker.connect(self._on_rename_tracker)
        self.tracker_panel.deleteTracker.connect(self._on_delete_tracker)
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
        # Телеметрия без позиции {tracker_id: {batt, voltage, ts}} — заряд
        # из status-пакетов; главнее позиции (там 0 = «нет данных»).
        self._telemetry: dict[str, dict] = {}
        # Псевдонимы трекеров {tracker_id: name}; заполняются при старте.
        self._tracker_names: dict[str, str] = {}
        # Трекеры с включённым треком (зеркало JS set; для индикатора в списке).
        self._visible_tracks: set[str] = set()
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
        self.bridge.trackShown.connect(self._on_track_shown)

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

        # Статус-бар. Состояния хранятся отдельно, тексты рендерятся по языку.
        self._port_state = "none"  # none | connected | demo | disconnected | error
        self._port_value = ""
        self._queue_size: int | None = None
        self.status_port = QLabel()
        self.status_queue = QLabel()
        self.status_active = QLabel()
        self.status_map = ClickableLabel()
        self.status_map.setCursor(Qt.PointingHandCursor)
        self.status_map.setToolTip(_("Управление картами"))
        self.status_map.clicked.connect(self._open_map_manager)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(180)
        self.port_combo.activated.connect(self._on_port_selected)

        self._render_port_status()
        self._render_queue_status()
        self._update_active_status()

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
        self.log_dock = QDockWidget(_("Лог"), self)
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
            # Передать начальные фильтр, цветовой режим и язык в JS
            self._push_filter_to_js()
            self._push_color_mode_to_js()
            self._push_language_to_js()

    def _push_language_to_js(self):
        if self._web_loaded:
            self.web.page().runJavaScript(f"applyLanguage('{self.settings.language}')")

    def retranslate_ui(self):
        """Перестраивает интерфейс окна после смены языка (без рестарта)."""
        self.log_dock.setWindowTitle(_("Лог"))
        self.tracker_panel.retranslate()
        self.status_map.setToolTip(_("Управление картами"))

        # Тулбар: пересоздаём, сохраняя текущий фильтр и цветовой режим.
        filter_index = self._filter_combo.currentIndex() if self._filter_combo else 0
        color_mode = self._color_combo.currentData() if self._color_combo else "palette"
        if self._toolbar is not None:
            self.removeToolBar(self._toolbar)
            self._toolbar.deleteLater()
            self._toolbar = None
        self._setup_toolbar()
        self._filter_combo.blockSignals(True)
        self._filter_combo.setCurrentIndex(filter_index)
        self._filter_combo.blockSignals(False)
        cidx = self._color_combo.findData(color_mode)
        self._color_combo.blockSignals(True)
        self._color_combo.setCurrentIndex(cidx if cidx >= 0 else 0)
        self._color_combo.blockSignals(False)

        # Меню пересоздаём полностью.
        self.menuBar().clear()
        self._setup_menu()

        # Статус-бар перерисовываем из сохранённого состояния.
        self._render_port_status()
        self._render_queue_status()
        self._update_active_status()
        self._update_map_status()

    def _setup_toolbar(self):
        toolbar = QToolBar(_("История и треки"))
        self.addToolBar(toolbar)
        self._toolbar = toolbar

        toolbar.addWidget(QLabel(_("История:")))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems([_("Сегодня"), _("Вчера"), _("Период…")])
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_combo)

        toolbar.addWidget(QLabel(_("Цвет трека:")))
        self._color_combo = QComboBox()
        self._color_combo.addItem(_("Палитра"), "palette")
        self._color_combo.addItem(_("Высота"), "altitude")
        self._color_combo.addItem(_("Варио"), "vario")
        index = self._color_combo.findData(self.settings.track_color_mode)
        self._color_combo.blockSignals(True)
        self._color_combo.setCurrentIndex(index if index >= 0 else 0)
        self._color_combo.blockSignals(False)
        self._color_combo.currentIndexChanged.connect(self._on_color_mode_changed)
        toolbar.addWidget(self._color_combo)

        clear_btn = QPushButton(_("Очистить историю"))
        clear_btn.setToolTip(_("Удалить все сохранённые позиции"))
        clear_btn.clicked.connect(self._on_clear_history)
        toolbar.addWidget(clear_btn)

        # Начальное значение фильтра — сегодня
        self._apply_filter_range(0)

    def _setup_menu(self):
        """Главное меню приложения."""
        menu_bar = self.menuBar()

        map_menu = menu_bar.addMenu(_("Карта"))
        download_action = map_menu.addAction(_("Загрузить новую карту…"))
        download_action.setStatusTip(_("Скачать дополнительный регион для офлайн-карт"))
        download_action.triggered.connect(self._on_download_map)
        manage_action = map_menu.addAction(_("Управление картами…"))
        manage_action.setStatusTip(_("Список карт, статусы, удаление, докачка"))
        manage_action.triggered.connect(self._open_map_manager)

        data_menu = menu_bar.addMenu(_("Данные"))
        settings_action = QAction(_("Настройки…"), self)
        settings_action.setShortcut("Ctrl+,")
        # На macOS HIG требует, чтобы настройки были в меню приложения; задаём
        # роль явно, иначе Qt угадывает по тексту и поведение зависит от языка.
        settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        settings_action.triggered.connect(self._open_settings)
        data_menu.addAction(settings_action)
        data_menu.addSeparator()
        gpx_action = data_menu.addAction(_("Экспорт GPX…"))
        gpx_action.triggered.connect(lambda: self._export_tracks("gpx"))
        csv_action = data_menu.addAction(_("Экспорт CSV…"))
        csv_action.triggered.connect(lambda: self._export_tracks("csv"))
        data_menu.addSeparator()

        # Быстрое включение/выключение моковых данных без перезапуска.
        self._demo_action = QAction(_("Демо-режим (тестовые данные)"), self)
        self._demo_action.setCheckable(True)
        self._demo_action.setStatusTip(
            _("Моковые позиции вместо serial-приёмника; отключается снятием галки")
        )
        self._demo_action.setChecked(self._demo)
        self._demo_action.toggled.connect(self._on_demo_toggled)
        data_menu.addAction(self._demo_action)

        help_menu = menu_bar.addMenu(_("Помощь"))
        about_action = help_menu.addAction(_("О программе"))
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.setStatusTip(_("Информация о MeshTrack Desktop"))
        about_action.triggered.connect(self._show_about)
        licenses_action = help_menu.addAction(_("Лицензии компонентов"))
        licenses_action.setStatusTip(
            _("Сторонние компоненты, версии и тексты лицензий")
        )
        licenses_action.triggered.connect(self._show_licenses)

    def _show_about(self):
        """Диалог «О программе»."""
        from . import __version__

        text = (
            "<h3>MeshTrack Desktop</h3>"
            f"{_('Версия {v}').format(v=__version__)}<br><br>"
            f"{_('Бесплатная программа для локального отображения данных, поступающих с приёмника LoRa-трекеров MeshTrack или Aglora.')}<br><br>"
            f"{_('Распространяется по лицензии MIT: использование свободное, но без каких-либо гарантий.')} "
            f'<a href="https://opensource.org/licenses/MIT">MIT</a><br><br>'
            f"{_('Автор: Евгений Шлягин')}<br>"
            f'{_("Почта:")} <a href="mailto:shlyagin@gmail.com">shlyagin@gmail.com</a>'
        )
        QMessageBox.about(self, _("О программе"), text)

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
        lang_changed = values["language"] != self.settings.language

        self.settings.traccar_on = values["traccar_on"]
        self.settings.port_pref = values["port_pref"]
        self.settings.baud = values["baud"]
        self.settings.retention_days = values["retention_days"]
        self.settings.language = values["language"]
        try:
            self.settings.save()
        except Exception:
            self.logger.exception("Ошибка сохранения настроек")

        self.publisher.enable = self.settings.traccar_on and not self._demo
        self.logger.info(
            "Настройки: Traccar=%s, порт=%s, baud=%d, retention=%d дн., язык=%s",
            "вкл" if self.settings.traccar_on else "выкл",
            self.settings.port_pref or "—",
            self.settings.baud,
            self.settings.retention_days,
            self.settings.language,
        )

        if lang_changed:
            init_translator(self.settings.language)
            self.retranslate_ui()
            self._push_language_to_js()

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
            QMessageBox.critical(
                parent, _("Экспорт"), _("Не удалось прочитать историю.")
            )
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
                parent, _("Экспорт"), _("За выбранный период нет данных.")
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
            parent,
            _("Экспорт треков"),
            str(Path(start_dir) / default_name),
            file_filter,
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
            QMessageBox.critical(parent, _("Экспорт"), _("Не удалось сохранить файл."))
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
        dlg.setWindowTitle(_("Выберите период"))
        layout = QVBoxLayout(dlg)

        now = QDateTime.currentDateTime()
        from_edit = QDateTimeEdit(now.addDays(-1))
        from_edit.setCalendarPopup(True)
        from_edit.setDisplayFormat("dd.MM.yyyy hh:mm")
        to_edit = QDateTimeEdit(now)
        to_edit.setCalendarPopup(True)
        to_edit.setDisplayFormat("dd.MM.yyyy hh:mm")

        form = QHBoxLayout()
        form.addWidget(QLabel(_("С:")))
        form.addWidget(from_edit)
        form.addWidget(QLabel(_("По:")))
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
            _("Очистить историю"),
            _(
                "Удалить все сохранённые позиции трекеров?\nТекущие маркеры останутся на карте до закрытия."
            ),
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

        self.port_combo.addItem(_("Выбрать порт…"))
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
        worker.telemetry.connect(self._handle_telemetry)
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

        self._port_state = "connected"
        self._port_value = port
        self._render_port_status()

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

        self._port_state = "demo"
        self._render_port_status()
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
        self._port_state = "none"
        self._render_port_status()
        self.logger.info("Демо-режим выключен")

    def _on_worker_finished(self):
        self.logger.info("Поток данных завершён")
        self._data_timer.stop()
        self._port_state = "disconnected"
        self._render_port_status()

    def _handle_position(self, pos: dict):
        # ts — время с устройства; recv_ts — время приёма на ПК
        pos = dict(pos)
        recv_ts = time.time()
        device_ts = pos.get("device_ts")
        pos["ts"] = device_ts if device_ts is not None else recv_ts
        pos["recv_ts"] = recv_ts
        tracker_id = pos.get("id", "unknown")

        # Псевдоним трекера (если задан) имеет приоритет над демо-именем.
        if tracker_id in self._tracker_names:
            pos["name"] = self._tracker_names[tracker_id]

        lat = float(pos.get("lat", 0))
        lon = float(pos.get("lon", 0))
        alt = float(pos.get("altitude")) if "altitude" in pos else None
        batt = float(pos["batt"]) if "batt" in pos and pos["batt"] else None
        voltage = float(pos["voltage"]) if "voltage" in pos and pos["voltage"] else None
        sos = int(pos.get("sos", 0)) if "sos" in pos else None

        # Позиция может нести batt=0/mv=0 («нет данных»); тогда берём заряд
        # из телеметрии (status-пакет) — она достовернее позиции.
        tel = self._telemetry.get(tracker_id)
        if (
            (batt is None or not (1 <= batt <= 100))
            and tel
            and tel.get("batt") is not None
        ):
            batt = tel["batt"]
        if not voltage and tel and tel.get("voltage") is not None:
            voltage = tel["voltage"]

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

    def _handle_telemetry(self, pos: dict):
        """Status-пакет без координат: обновляет заряд/напряжение трекера.

        Телеметрия — самый достоверный источник заряда (позиция часто несёт
        0 = «данных нет»), поэтому она перезаписывает batt/voltage у трекера,
        который уже есть на карте. Для неизвестного трекера значение просто
        кэшируется до первой позиции (см. _handle_position).
        """
        tracker_id = pos.get("id")
        if not tracker_id:
            return
        tel = {"ts": time.time()}
        if "batt" in pos and pos["batt"] is not None:
            tel["batt"] = float(pos["batt"])
        if "voltage" in pos and pos["voltage"] is not None:
            tel["voltage"] = float(pos["voltage"])
        self._telemetry[tracker_id] = tel

        cur = self._last_positions.get(tracker_id)
        if cur is None:
            return  # позиции ещё не было — применим при первой
        changed = False
        for key in ("batt", "voltage"):
            if key in tel and cur.get(key) != tel[key]:
                cur = dict(cur)
                cur[key] = tel[key]
                changed = True
        if not changed:
            return
        self._last_positions[tracker_id] = cur
        self.logger.debug(
            "Телеметрия %s: batt=%s%% voltage=%s",
            tracker_id,
            tel.get("batt"),
            tel.get("voltage"),
        )
        self.tracker_panel.update_tracker(cur)
        self.bridge.pushPosition(cur)

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

    def _render_port_status(self):
        if self._port_state == "demo":
            self.status_port.setText(_("Порт: ДЕМО"))
            self.status_port.setStyleSheet("color: #b8860b;")
        elif self._port_state == "connected":
            self.status_port.setText(_("Порт: {port}").format(port=self._port_value))
            self.status_port.setStyleSheet("color: green;")
        elif self._port_state == "error":
            self.status_port.setText(_("Порт: ошибка"))
            self.status_port.setStyleSheet("color: red;")
        elif self._port_state == "disconnected":
            self.status_port.setText(_("Порт: отключён"))
            self.status_port.setStyleSheet("color: gray;")
        else:
            self.status_port.setText(_("Порт: нет"))
            self.status_port.setStyleSheet("color: gray;")

    def _render_queue_status(self):
        if self._queue_size is None:
            self.status_queue.setText(_("Queue: —"))
        else:
            self.status_queue.setText(_("Queue: {n}").format(n=self._queue_size))

    def _handle_queue_size(self, size: int):
        self._queue_size = size
        self._render_queue_status()

    def _handle_serial_error(self, msg: str):
        self._port_state = "error"
        self._render_port_status()
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
        self.status_active.setText(_("Активных: {n}").format(n=len(active)))

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
        self._tracker_names = self.repo.tracker_names()
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
            self.status_map.setText(_("Карта: нет"))
            return
        path = self.settings.get_map_path(map_id)
        if not path or not Path(path).exists():
            self.status_map.setText(
                _("Карта: {map_id} (файл не найден)").format(map_id=map_id)
            )
            return
        self.status_map.setText(_("Карта: {map_id}").format(map_id=map_id))

    def _on_tracker_clicked(self, tracker_id: str):
        # Одиночный клик: только центрируем карту и показываем попап.
        self.web.page().runJavaScript(f'centerTracker("{tracker_id}")')

    def _on_tracker_double_clicked(self, tracker_id: str):
        # Двойной клик по цветной плашке: показать/скрыть трек.
        self.web.page().runJavaScript(f'toggleTrack("{tracker_id}")')

    def _on_track_shown(self, tracker_id: str, shown: bool):
        """Зеркалит видимость трека из JS (индикатор на плашке в списке)."""
        if shown:
            self._visible_tracks.add(tracker_id)
        else:
            self._visible_tracks.discard(tracker_id)
        self.tracker_panel.set_track_visible(tracker_id, shown)

    def _on_delete_tracker(self, tracker_id: str):
        """Удаление трекера: подтверждение, удаление из БД и с карты."""
        label = tracker_id
        last = self._last_positions.get(tracker_id)
        if last and last.get("name"):
            label = last["name"]
        reply = QMessageBox.question(
            self,
            _("Удалить трекер"),
            _(
                "Удалить все данные трекера «{label}» ({tracker_id})?\n"
                "Все позиции, треки и маркер будут удалены безвозвратно."
            ).format(label=label, tracker_id=tracker_id),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            deleted = self.repo.delete_tracker(tracker_id)
        except Exception:
            self.logger.exception("Ошибка удаления трекера %s", tracker_id)
            return
        self.logger.info("Удалён трекер %s, позиций удалено: %d", tracker_id, deleted)
        self._last_positions.pop(tracker_id, None)
        self._points_cache.pop(tracker_id, None)
        self._tracker_names.pop(tracker_id, None)
        self.tracker_panel.remove_tracker(tracker_id)
        self.web.page().runJavaScript(f'removeTracker("{tracker_id}")')
        self._update_active_status()

    def _on_rename_tracker(self, tracker_id: str):
        """Задать/изменить/снять псевдоним трекера."""
        current = self._tracker_names.get(tracker_id, "")
        label = tracker_id
        text, ok = QInputDialog.getText(
            self,
            _("Псевдоним трекера"),
            _(
                "Псевдоним для {tracker_id}\n"
                "(оставьте поле пустым, чтобы убрать псевдоним):"
            ).format(tracker_id=tracker_id),
            text=current,
        )
        if not ok:
            return
        new = text.strip()
        if new == "" and current:
            reply = QMessageBox.question(
                self,
                _("Убрать псевдоним"),
                _("Убрать псевдоним «{current}» у трекера {tracker_id}?").format(
                    current=current, tracker_id=tracker_id
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        if new == current:
            return
        try:
            self.repo.set_tracker_name(tracker_id, new or None)
        except Exception:
            self.logger.exception("Ошибка сохранения псевдонима %s", tracker_id)
            return
        if new:
            self._tracker_names[tracker_id] = new
        else:
            self._tracker_names.pop(tracker_id, None)
        self.logger.info("Псевдоним %s: %r → %r", tracker_id, label, new or None)
        pos = self._last_positions.get(tracker_id)
        if pos is None:
            return
        pos["name"] = new or None
        self._last_positions[tracker_id] = pos
        self.tracker_panel.update_tracker(pos)
        self.bridge.pushPosition(pos)

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
