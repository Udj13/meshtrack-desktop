"""Диалог «Лицензии компонентов»: список сторонних компонентов и тексты лицензий."""
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
)

from .licenses import COMPONENTS, load_license_text


class LicensesDialog(QDialog):
    """Окно со списком компонентов и полными текстами их лицензий."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Лицензии компонентов")
        self.resize(900, 600)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "MeshTrack Desktop использует следующие сторонние компоненты. "
            "Полные тексты лицензий приведены справа."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        splitter = QSplitter(Qt.Horizontal)
        self._list = QListWidget()
        self._list.setMinimumWidth(280)
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        splitter.addWidget(self._list)
        splitter.addWidget(self._browser)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for comp in COMPONENTS:
            item = QListWidgetItem(
                f"{comp['name']} ({comp['version']}) — {comp['license']}"
            )
            item.setData(Qt.UserRole, comp)
            self._list.addItem(item)

        self._list.currentRowChanged.connect(self._show_component)
        self._list.setCurrentRow(0)

    def _show_component(self, row: int):
        comp = self._list.item(row).data(Qt.UserRole)
        parts = [
            f"<h3>{escape(comp['name'])}</h3>",
            "<p>"
            f"<b>Версия:</b> {escape(comp['version'])}<br>"
            f"<b>Лицензия:</b> {escape(comp['license'])}<br>"
            f"<b>Копирайт:</b> {escape(comp['copyright'])}<br>"
            f"<b>Сайт:</b> "
            f'<a href="{comp["url"]}">{escape(comp["url"])}</a>'
            "</p>",
        ]
        note = comp.get("note")
        if note:
            parts.append(f"<p>{note}</p>")
        parts.append("<hr>")
        for filename in comp["files"]:
            try:
                text = load_license_text(filename)
            except OSError:
                text = f"(Файл лицензии {filename} не найден)"
            parts.append(
                f"<pre style=\"white-space: pre-wrap; "
                f"font-family: monospace;\">{escape(text)}</pre>"
            )
        self._browser.setHtml("".join(parts))