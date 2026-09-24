"""Диалог «Управление картами».

Список карт с статусами и действиями:
- скачанная — сделать активной / удалить;
- частичная — сделать активной / докачать / удалить;
- файл не найден — скачать заново / убрать из списка;
- не подключена (осиротевший файл) — подключить / удалить;
- не скачана (встроенный регион) — скачать;
- повреждена — удалить.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QWizard,
)

from .downloader import _format_size
from .first_run_wizard import (
    DownloadThread,
    FirstRunWizard,
    OPENTOPOMAP_TEMPLATE,
)
from .i18n import tr as _
from .map_manager import (
    CORRUPTED,
    DOWNLOADED,
    MISSING,
    NOT_DOWNLOADED,
    ORPHAN,
    PARTIAL,
    MapEntry,
    delete_map,
    map_bbox,
    scan_maps,
)
from .regions import get_prebuilt
from .settings import Settings

logger = logging.getLogger(__name__)

COLUMNS = ["Название", "Область", "Зум", "Размер", "Тайлов", "Статус", "Активна", "Действия"]

STATUS_LABELS = {
    DOWNLOADED: "Скачана",
    PARTIAL: "Частично",
    MISSING: "Файл не найден",
    ORPHAN: "Не подключена",
    NOT_DOWNLOADED: "Не скачана",
    CORRUPTED: "Повреждена",
}

# Статус -> [(текст кнопки, handler)]
ACTIONS: dict[str, list[tuple[str, str]]] = {
    DOWNLOADED: [("Сделать активной", "activate"), ("Проверить", "verify"), ("Удалить", "delete")],
    PARTIAL: [("Сделать активной", "activate"), ("Проверить", "verify"), ("Докачать", "resume"), ("Удалить", "delete")],
    MISSING: [("Скачать заново", "download"), ("Убрать из списка", "unlist")],
    ORPHAN: [("Подключить", "connect"), ("Удалить", "delete")],
    NOT_DOWNLOADED: [("Скачать", "download")],
    CORRUPTED: [("Проверить", "verify"), ("Удалить", "delete")],
}


class MapManagerDialog(QDialog):
    """Диалог управления офлайн-картами."""

    def __init__(self, settings: Settings, maps_dir: Path, bridge=None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._maps_dir = Path(maps_dir)
        self._bridge = bridge
        self._thread: DownloadThread | None = None
        self._entries: list[MapEntry] = []

        self.setWindowTitle(_("Управление картами"))
        self.resize(920, 480)

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([_(c) for c in COLUMNS])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        refresh_btn = QPushButton(_("Обновить"))
        refresh_btn.clicked.connect(self._refresh)
        buttons.addWidget(refresh_btn)

        new_region_btn = QPushButton(_("Скачать новый регион…"))
        new_region_btn.clicked.connect(self._download_new_region)
        buttons.addWidget(new_region_btn)

        buttons.addStretch(1)
        close_btn = QPushButton(_("Закрыть"))
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self._refresh()

    # ---------- таблица ----------

    def _refresh(self):
        self._entries = scan_maps(self._settings, self._maps_dir)
        active_id = self._settings.active_map_id
        self.table.setRowCount(0)
        for entry in self._entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._set_item(row, 0, entry.name)
            self._set_item(row, 1, self._format_bbox(entry))
            self._set_item(row, 2, self._format_zoom(entry))
            self._set_item(row, 3, _format_size(entry.size_bytes) if entry.size_bytes else "—")
            self._set_item(row, 4, self._format_tiles(entry))
            self._set_item(row, 5, _(STATUS_LABELS.get(entry.status, entry.status)))
            self._set_item(row, 6, "✓" if entry.map_id == active_id else "")
            self.table.setCellWidget(row, 7, self._action_widget(row, entry))

    def _set_item(self, row: int, col: int, text: str):
        item = QTableWidgetItem(text)
        if text:
            item.setToolTip(text)
        self.table.setItem(row, col, item)

    @staticmethod
    def _format_bbox(entry: MapEntry) -> str:
        bbox = map_bbox(entry)
        if bbox is None:
            return "—"
        south, north, west, east = bbox
        return f"{south:.3f}, {north:.3f} / {west:.3f}, {east:.3f}"

    @staticmethod
    def _format_zoom(entry: MapEntry) -> str:
        if entry.zmin is None or entry.zmax is None:
            return "—"
        return f"{entry.zmin}–{entry.zmax}"

    @staticmethod
    def _format_tiles(entry: MapEntry) -> str:
        if not entry.tile_count:
            return "—"
        if entry.tile_count_expected:
            return f"{entry.tile_count}/{entry.tile_count_expected}"
        return str(entry.tile_count)

    def _action_widget(self, row: int, entry: MapEntry) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        for label, action in ACTIONS.get(entry.status, []):
            btn = QPushButton(_(label))
            btn.clicked.connect(lambda _=False, a=action, r=row: self._on_action(a, r))
            layout.addWidget(btn)
        layout.addStretch(1)
        return widget

    # ---------- действия ----------

    def _on_action(self, action: str, row: int):
        if not (0 <= row < len(self._entries)):
            return
        entry = self._entries[row]
        if action == "activate":
            self._activate(entry)
        elif action == "verify":
            self._verify(entry)
        elif action == "delete":
            self._delete(entry)
        elif action == "resume":
            self._resume(entry)
        elif action == "download":
            self._run_wizard(entry)
        elif action == "unlist":
            self._unlist(entry)
        elif action == "connect":
            self._connect(entry)

    def _activate(self, entry: MapEntry):
        self._settings.active_map_id = entry.map_id
        self._save_settings()
        self._push_active_map(entry.map_id)
        self._refresh()

    def _verify(self, entry: MapEntry):
        """Проверяет целостность MBTiles и показывает отчёт (диагностика)."""
        from .mapstore import MapStore

        try:
            store = MapStore(entry.path)
            report = store.verify()
            try:
                zmin, zmax = store.get_minmax_zoom()
                zoom_txt = f"{zmin}-{zmax}"
            except Exception:
                zoom_txt = "—"
        except Exception:
            logger.exception("Проверка карты %s упала", entry.map_id)
            QMessageBox.critical(
                self, _("Проверка карты"), _("Не удалось прочитать файл карты.")
            )
            return

        lines = [
            entry.path,
            _("Зум: {z}").format(z=zoom_txt),
            _("Тайлов: {n}").format(n=report["tile_count"]),
        ]
        if report["ok"]:
            lines.append(_("Карта в порядке"))
        else:
            lines.append(_("Проблемы:"))
            lines.extend(f"— {e}" for e in report["errors"])
            lines.append(_("Перекачайте карту или выберите другую"))
        msg = "\n".join(lines)
        title = _("Проверка карты")
        if report["ok"]:
            QMessageBox.information(self, title, msg)
        else:
            QMessageBox.warning(self, title, msg)
        logger.info(
            "Проверка карты %s: ok=%s, tiles=%s, errors=%s",
            entry.map_id,
            report["ok"],
            report["tile_count"],
            report["errors"],
        )

    def _delete(self, entry: MapEntry):
        size = _format_size(entry.size_bytes) if entry.size_bytes else ""
        was_active = self._settings.active_map_id == entry.map_id
        msg = _("Удалить карту «{name}»?").format(name=entry.name)
        if size:
            msg += _("\nРазмер: {size}").format(size=size)
        if was_active:
            msg += _("\nКарта активна — будет автоматически выбрана другая.")
        reply = QMessageBox.question(
            self,
            _("Удаление карты"),
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        new_active = delete_map(self._settings, entry.map_id)
        self._push_active_map(new_active or "")
        self._refresh()

    def _unlist(self, entry: MapEntry):
        was_active = self._settings.active_map_id == entry.map_id
        self._settings.remove_map(entry.map_id)
        self._save_settings()
        if was_active:
            self._push_active_map(self._settings.active_map_id or "")
        self._refresh()

    def _connect(self, entry: MapEntry):
        bbox = map_bbox(entry)
        kwargs = {}
        if bbox is not None:
            south, north, west, east = bbox
            kwargs.update(south=south, north=north, west=west, east=east)
        if entry.zmin is not None:
            kwargs["zmin"] = entry.zmin
        if entry.zmax is not None:
            kwargs["zmax"] = entry.zmax
        self._settings.add_map(entry.map_id, entry.name, entry.path, **kwargs)
        self._save_settings()
        self._refresh()

    def _run_wizard(self, entry: MapEntry):
        preselect = entry.map_id if get_prebuilt(entry.map_id) else None
        wizard = FirstRunWizard(
            self._settings,
            self._maps_dir,
            parent=self,
            show_welcome=False,
            preselect_region_id=preselect,
        )
        if wizard.exec() != QWizard.Accepted:
            return
        map_id = self._settings.active_map_id
        if map_id:
            self._save_settings()
            self._push_active_map(map_id)
        self._refresh()

    def _download_new_region(self):
        self._run_wizard(MapEntry(map_id="", name="", path="", source="", status=""))

    def _resume(self, entry: MapEntry):
        bbox = map_bbox(entry)
        if bbox is None:
            QMessageBox.warning(
                self, _("Докачка"), _("Нет данных о границах области для докачки.")
            )
            return
        zmin = entry.zmin or 9
        zmax = entry.zmax or 15

        from .mapstore import MapStore

        store = MapStore(entry.path)
        thread = DownloadThread(store, bbox, zmin, zmax, OPENTOPOMAP_TEMPLATE, parent=self)
        self._thread = thread

        progress = QProgressDialog(
            _("Докачка: {name}…").format(name=entry.name), _("Отмена"), 0, 100, self
        )
        progress.setWindowTitle(_("Докачка карты"))
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)
        progress.canceled.connect(thread.cancel)
        thread.progress.connect(
            lambda done, total, _stats: progress.setValue(
                int(done * 100 / total) if total else 0
            )
        )

        def on_finished(result: dict):
            progress.close()
            if result.get("failed", 0) == 0:
                store.set_metadata("complete", "1")
            self._settings.add_map(
                entry.map_id,
                entry.name,
                entry.path,
                south=bbox[0],
                north=bbox[1],
                west=bbox[2],
                east=bbox[3],
                zmin=zmin,
                zmax=zmax,
            )
            self._save_settings()
            self._refresh()

        def on_error(msg: str):
            progress.close()
            QMessageBox.critical(self, _("Ошибка докачки"), msg)
            self._refresh()

        thread.finished_ok.connect(on_finished)
        thread.error.connect(on_error)
        thread.start()

    # ---------- служебное ----------

    def _save_settings(self):
        try:
            self._settings.save()
        except Exception:
            logger.exception("Ошибка сохранения настроек")

    def _push_active_map(self, map_id: str):
        if self._bridge is not None:
            try:
                self._bridge.setActiveMapId(map_id)
            except Exception:
                logger.exception("Ошибка смены активной карты")

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait(3000)
        super().closeEvent(event)