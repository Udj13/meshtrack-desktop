"""Снимки окна приложения в демо-режиме для сайта проекта.

Запуск:
    .venv/bin/python tools/screenshot.py [--output DIR]

Результат (по умолчанию — site/assets/img/ в корне репозитория):
    main.webp   — карта с трекерами и панель трекеров
    popup.webp  — попап трекера
    maps.png    — диалог «Управление картами»

Скриншоты с картой сохраняются в WebP (1800 px по ширине) — PNG с детальной
картой весит больше мегабайта, что для веба избыточно.

Требования: скачанные карты (центр демо берётся из активной карты в
config.json) и схема map://, зарегистрированная до создания QApplication
(иначе тайлы не отрисуются).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from meshtrack.app import MainWindow  # noqa: E402
from meshtrack.map_dialog import MapManagerDialog  # noqa: E402
from meshtrack.mapscheme import register_map_scheme  # noqa: E402

MAIN_DELAY_MS = 14_000  # ждём загрузку веб-карты и первые позиции демо
STEP_MS = 1_500
WEBP_MAX_WIDTH = 1800
WEBP_QUALITY = 82


def main() -> int:
    ap = argparse.ArgumentParser(prog="tools/screenshot.py")
    ap.add_argument(
        "--output",
        default=str(ROOT / "site" / "assets" / "img"),
        help="Каталог для скриншотов (по умолчанию site/assets/img в корне репо)",
    )
    args = ap.parse_args()
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Схема map:// должна быть зарегистрирована до создания QApplication,
    # иначе тайлы оффлайн-карты не отрисуются (как в meshtrack/__main__.py).
    register_map_scheme()

    app = QApplication(sys.argv)
    win = MainWindow(demo=True)
    win.show()
    win.raise_()
    win.activateWindow()
    win.log_dock.hide()

    def grab(name: str, widget=None):
        app.processEvents()
        widget = widget or win
        pix = widget.grab()
        if name.endswith(".webp"):
            if pix.width() > WEBP_MAX_WIDTH:
                pix = pix.scaledToWidth(WEBP_MAX_WIDTH, Qt.SmoothTransformation)
            ok = pix.save(str(out_dir / name), "WEBP", WEBP_QUALITY)
        else:
            ok = pix.save(str(out_dir / name))
        print(("saved " if ok else "FAILED ") + str(out_dir / name))

    def shot_main():
        grab("main.webp")

    def shot_popup():
        win.web.page().runJavaScript('centerTracker("boon101")')
        QTimer.singleShot(STEP_MS, lambda: (grab("popup.webp"), shot_maps()))

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