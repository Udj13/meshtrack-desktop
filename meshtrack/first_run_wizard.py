"""First-run мастер загрузки офлайн-карт.

QWizard с четырьмя страницами:
1. Приветствие.
2. Выбор региона (встроенный список или пользовательский bbox).
3. Прогресс скачивания.
4. Завершение.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from . import downloader, regions
from .mapstore import MapStore
from .settings import Settings

logger = logging.getLogger(__name__)

# URL-шаблон OpenTopoMap (PROJECT.md §8).
OPENTOPOMAP_TEMPLATE = "https://tile.opentopomap.org/{z}/{x}/{y}.png"


class DownloadThread(QThread):
    """Поток скачивания тайлов; испускает сигналы прогресса и результата."""

    progress = Signal(int, int, dict)  # (done, total, stats)
    finished_ok = Signal(dict)         # {"total": int, "downloaded": int, ...}
    error = Signal(str)

    def __init__(
        self,
        store: MapStore,
        bbox: tuple[float, float, float, float],
        zmin: int,
        zmax: int,
        url_template: str,
        parent=None,
    ):
        super().__init__(parent)
        self.store = store
        self.bbox = bbox
        self.zmin = zmin
        self.zmax = zmax
        self.url_template = url_template
        self.cancel_event = threading.Event()

    def run(self):
        try:
            result = downloader.download(
                self.store,
                self.bbox,
                self.url_template,
                zmin=self.zmin,
                zmax=self.zmax,
                on_progress=lambda done, total, stats: self.progress.emit(
                    done, total, stats
                ),
                cancel_event=self.cancel_event,
            )
            self.finished_ok.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))

    def cancel(self):
        self.cancel_event.set()


class WelcomePage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Добро пожаловать в MeshTrack")
        self.setSubTitle(
            "Для работы офлайн необходимо загрузить топографическую карту региона."
        )
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Выберите один из встроенных регионов или задайте собственную область. "
                "Скачанные тайлы сохраняются локально и будут доступны без интернета."
            )
        )
        layout.addStretch()


class RegionPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Выбор региона")
        self.setSubTitle("Укажите область для загрузки карты")

        self._radio_prebuilt = QRadioButton("Встроенный регион")
        self._radio_prebuilt.setChecked(True)
        self._radio_custom = QRadioButton("Свой bbox")

        self._group = QButtonGroup(self)
        self._group.addButton(self._radio_prebuilt)
        self._group.addButton(self._radio_custom)

        self._list = QListWidget()
        for region in regions.list_prebuilt():
            item = QListWidgetItem(region.name)
            item.setData(Qt.UserRole, region.id)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

        self._south = QLineEdit()
        self._north = QLineEdit()
        self._west = QLineEdit()
        self._east = QLineEdit()
        for edit in (self._south, self._north, self._west, self._east):
            edit.setPlaceholderText("0.00000")
            edit.setEnabled(False)

        self._radio_prebuilt.toggled.connect(self._update_ui)
        self._radio_custom.toggled.connect(self._update_ui)

        grid = QGridLayout()
        grid.addWidget(self._radio_prebuilt, 0, 0, 1, 2)
        grid.addWidget(self._list, 1, 0, 1, 2)
        grid.addWidget(self._radio_custom, 2, 0, 1, 2)
        grid.addWidget(QLabel("Юг:"), 3, 0)
        grid.addWidget(self._south, 3, 1)
        grid.addWidget(QLabel("Север:"), 4, 0)
        grid.addWidget(self._north, 4, 1)
        grid.addWidget(QLabel("Запад:"), 5, 0)
        grid.addWidget(self._west, 5, 1)
        grid.addWidget(QLabel("Восток:"), 6, 0)
        grid.addWidget(self._east, 6, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addStretch()
        self.setLayout(layout)

    def _update_ui(self):
        prebuilt = self._radio_prebuilt.isChecked()
        self._list.setEnabled(prebuilt)
        for edit in (self._south, self._north, self._west, self._east):
            edit.setEnabled(not prebuilt)

    def validatePage(self):
        if self._radio_prebuilt.isChecked():
            return self._list.currentItem() is not None
        try:
            south = float(self._south.text().replace(",", "."))
            north = float(self._north.text().replace(",", "."))
            west = float(self._west.text().replace(",", "."))
            east = float(self._east.text().replace(",", "."))
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Введите числовые координаты bbox")
            return False
        ok, msg = regions.validate_bbox(south, north, west, east)
        if not ok:
            QMessageBox.warning(self, "Ошибка", msg)
            return False
        return True

    def selected_region(self) -> tuple[str, tuple[float, float, float, float]]:
        """Возвращает (region_id, bbox). Для встроенного region_id != None."""
        if self._radio_prebuilt.isChecked():
            item = self._list.currentItem()
            region_id = item.data(Qt.UserRole)
            region = regions.get_prebuilt(region_id)
            return region_id, region.bbox
        south = float(self._south.text().replace(",", "."))
        north = float(self._north.text().replace(",", "."))
        west = float(self._west.text().replace(",", "."))
        east = float(self._east.text().replace(",", "."))
        bbox = regions.normalize_bbox(south, north, west, east)
        return None, bbox


class DownloadPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Загрузка карты")
        self.setSubTitle("Идёт скачивание тайлов…")

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)

        self._status = QLabel("Подготовка…")
        self._cancel_btn = QPushButton("Отменить")
        self._cancel_btn.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)
        layout.addWidget(self._cancel_btn)
        layout.addStretch()

        self._thread: DownloadThread | None = None
        self._result: dict | None = None
        self._cancelled = False

    def initializePage(self):
        wizard = self.wizard()
        map_id = wizard.map_id
        bbox = wizard.bbox
        zmin = wizard.zmin
        zmax = wizard.zmax
        dest = wizard.dest_path

        self._status.setText(f"Регион: {map_id}\nФайл: {dest}")
        self._progress.setValue(0)

        store = MapStore(dest)
        store.set_metadata("name", map_id)
        store.set_metadata("format", "png")
        store.set_metadata("version", "1.1")

        self._thread = DownloadThread(
            store, bbox, zmin, zmax, OPENTOPOMAP_TEMPLATE, parent=self
        )
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_ok.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setEnabled(True)
        if wizard is not None:
            wizard.button(QWizard.BackButton).setEnabled(False)
        self._thread.start()

    def _on_progress(self, done: int, total: int, stats: dict):
        if total > 0:
            self._progress.setValue(int(done * 100 / total))
        size = downloader._format_size(stats.get("bytes_downloaded", 0))
        estimated = downloader._format_size(stats.get("bytes_estimated", 0))
        remaining = stats.get("seconds_remaining")
        time_str = (
            downloader._format_time(remaining)
            if remaining is not None
            else "подсчёт…"
        )
        self._status.setText(
            f"Загружено {done} из {total} тайлов\n"
            f"{size} / ~{estimated} осталось ~{time_str}"
        )

    def _on_finished(self, result: dict):
        self._result = result
        size = downloader._format_size(result.get("bytes_downloaded", 0))
        elapsed = result.get("elapsed_seconds", 0)
        self._status.setText(
            f"Готово: скачано {result['downloaded']} тайлов ({size})\n"
            f"пропущено {result['skipped']}, ошибок {result['failed']}, "
            f"за {downloader._format_time(elapsed)}"
        )
        self.completeChanged.emit()

    def _on_error(self, msg: str):
        self._result = {"error": msg}
        self._status.setText(f"Ошибка: {msg}")
        QMessageBox.critical(self, "Ошибка загрузки", msg)
        self.completeChanged.emit()

    def _on_cancel(self):
        self._cancelled = True
        if self._thread is not None:
            self._thread.cancel()
        self._status.setText("Загрузка отменена. Скачанные тайлы сохранены.")
        self._cancel_btn.setEnabled(False)
        self.completeChanged.emit()

    def isComplete(self):
        return self._result is not None or self._cancelled

    def cleanupPage(self):
        if self._thread is not None and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait(3000)


class DonePage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Готово")
        self.setSubTitle("Карта сохранена и готова к работе")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Регион загружен. Теперь приложение будет использовать "
                "офлайн-карту при отсутствии интернета."
            )
        )
        layout.addStretch()


class FirstRunWizard(QWizard):
    """Мастер загрузки карты (первый запуск или добавление новой карты)."""

    def __init__(
        self,
        settings: Settings,
        maps_dir: Path,
        parent=None,
        show_welcome: bool = True,
    ):
        super().__init__(parent)
        self.setWindowTitle(
            "MeshTrack — первый запуск" if show_welcome else "MeshTrack — загрузка карты"
        )
        self.resize(640, 480)

        # Watermark для левой панели wizard
        # ModernStyle отображает watermark слева на всех страницах.
        self.setWizardStyle(QWizard.ModernStyle)
        watermark_path = (
            Path(__file__).resolve().parent.parent / "assets" / "wizard_watermark.png"
        )
        if watermark_path.exists():
            self.setPixmap(QWizard.WatermarkPixmap, QPixmap(str(watermark_path)))
        else:
            logger.warning("Watermark не найден: %s", watermark_path)

        self._settings = settings
        self._maps_dir = Path(maps_dir)
        self._maps_dir.mkdir(parents=True, exist_ok=True)

        self.map_id: str | None = None
        self.bbox: tuple[float, float, float, float] | None = None
        self.zmin = 9
        self.zmax = 15
        self.dest_path: str | None = None

        if show_welcome:
            self.addPage(WelcomePage(self))
        self._region_page = RegionPage(self)
        self.addPage(self._region_page)
        self.addPage(DownloadPage(self))
        self.addPage(DonePage(self))

        self.setButtonText(QWizard.FinishButton, "Готово")
        self.setButtonText(QWizard.CancelButton, "Отмена")
        self.setOption(QWizard.HaveCustomButton1, False)

    def validateCurrentPage(self):
        page = self.currentPage()
        if page is self._region_page:
            region_id, bbox = self._region_page.selected_region()
            self.bbox = bbox
            if region_id:
                self.map_id = region_id
            else:
                from .regions import make_region_id

                self.map_id = make_region_id(f"custom_{bbox[0]}_{bbox[1]}")
            self.dest_path = str(self._maps_dir / f"{self.map_id}.mbtiles")
        return super().validateCurrentPage()

    def accept(self):
        # Сохраняем карту в настройках
        if self.map_id and self.dest_path:
            self._settings.add_map(self.map_id, self.map_id, self.dest_path)
            self._settings.active_map_id = self.map_id
            try:
                self._settings.save()
            except Exception:
                pass
        return super().accept()


def run_first_run_wizard(settings: Settings, maps_dir: Path, parent=None) -> bool:
    """Запускает мастер первого запуска."""
    wizard = FirstRunWizard(settings, maps_dir, parent=parent, show_welcome=True)
    return wizard.exec() == QWizard.Accepted


def run_download_map_wizard(settings: Settings, maps_dir: Path, parent=None) -> bool:
    """Запускает мастер для докачки дополнительной карты."""
    wizard = FirstRunWizard(settings, maps_dir, parent=parent, show_welcome=False)
    return wizard.exec() == QWizard.Accepted
