"""Снимки окна приложения в демо-режиме для лендинга (site/assets/img/).

Запуск:
    .venv/bin/python tools/screenshot.py

Результат:
    site/assets/img/main.png    — карта с трекерами и панель трекеров
    site/assets/img/popup.png   — попап трекера
    site/assets/img/maps.png    — диалог «Управление картами»
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from meshtrack.app import MainWindow  # noqa: E402
from meshtrack.map_dialog import MapManagerDialog  # noqa: E402

OUT_DIR = ROOT / "site" / "assets" / "img"
MAIN_DELAY_MS = 14_000  # ждём загрузку веб-карты и первые позиции демо
STEP_MS = 1_500


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    win = MainWindow(demo=True)
    win.show()
    win.raise_()
    win.activateWindow()
    win.log_dock.hide()

    def grab(name: str, widget=None):
        app.processEvents()
        widget = widget or win
        ok = widget.grab().save(str(OUT_DIR / name))
        print(("saved " if ok else "FAILED ") + str(OUT_DIR / name))

    def shot_main():
        grab("main.png")

    def shot_popup():
        win.web.page().runJavaScript('centerTracker("boon101")')
        QTimer.singleShot(STEP_MS, lambda: (grab("popup.png"), shot_maps()))

    def shot_maps():
        dlg = MapManagerDialog(
            win.settings, win.data_dir / "maps", bridge=win.bridge, parent=win
        )
        dlg.show()
        dlg.raise_()
        QTimer.singleShot(STEP_MS, lambda: (grab("maps.png", dlg), dlg.close(), app.quit()))

    QTimer.singleShot(MAIN_DELAY_MS, shot_main)
    QTimer.singleShot(MAIN_DELAY_MS + STEP_MS, shot_popup)

    app.exec()
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())