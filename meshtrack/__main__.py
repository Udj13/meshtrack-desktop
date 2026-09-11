"""Точка входа: python -m meshtrack [--port PORT] [--debug]"""
import argparse
import logging
import sys

from PySide6.QtWidgets import QApplication

from .app import MainWindow


def main():
    ap = argparse.ArgumentParser(prog="python -m meshtrack")
    ap.add_argument("--port", default=None, help="Serial порт или file://PATH")
    ap.add_argument(
        "--debug",
        action="store_true",
        help="Включить DEBUG-уровень логирования (raw-строки из порта и т.п.)",
    )
    args, qt_argv = ap.parse_known_args()

    app = QApplication(qt_argv)
    win = MainWindow(debug=args.debug)
    if args.port:
        win._connect_serial(args.port)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
