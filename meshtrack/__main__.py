"""Точка входа: python -m meshtrack [--port PORT] [--debug]"""
import argparse
import logging
import sys

from PySide6.QtWidgets import QApplication

from .app import MainWindow, app_data_dir
from .first_run_wizard import run_first_run_wizard
from .mapscheme import register_map_scheme
from .settings import Settings


def main():
    ap = argparse.ArgumentParser(prog="python -m meshtrack")
    ap.add_argument("--port", default=None, help="Serial порт или file://PATH")
    ap.add_argument(
        "--debug",
        action="store_true",
        help="Включить DEBUG-уровень логирования (raw-строки из порта и т.п.)",
    )
    args, qt_argv = ap.parse_known_args()

    # Регистрация кастомной схемы map:// должна произойти до создания QApplication.
    register_map_scheme()

    app = QApplication(qt_argv)

    # Проверяем наличие карт до создания главного окна.
    data_dir = app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(data_dir / "config.json")
    if not settings.has_maps:
        ok = run_first_run_wizard(settings, data_dir / "maps")
        if not ok:
            return 0

    win = MainWindow(debug=args.debug)
    if args.port:
        win._connect_serial(args.port)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
