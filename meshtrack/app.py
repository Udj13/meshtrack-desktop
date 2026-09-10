"""Главное окно приложения MeshTrack.

Пока — заглушка с заголовком. Карта появится в Фазе 1–4.
"""
import sys
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MeshTrack")
        self.resize(1000, 700)
        label = QLabel("MeshTrack — скелет (Фаза 0)")
        label.setStyleSheet("font-size: 18px; padding: 40px;")
        self.setCentralWidget(label)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()
