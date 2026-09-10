"""Точка входа: python -m meshtrack [--port PORT]"""
import argparse
import sys

from PySide6.QtWidgets import QApplication

from .app import MainWindow


def main():
    ap = argparse.ArgumentParser(prog="python -m meshtrack")
    ap.add_argument("--port", default=None, help="Serial порт или file://PATH")
    args, qt_argv = ap.parse_known_args()

    app = QApplication(qt_argv)
    win = MainWindow()
    if args.port:
        win._connect_serial(args.port)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
