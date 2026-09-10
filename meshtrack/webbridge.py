"""Мост Python ↔ JS через QWebChannel.

Python-сторона принимает позицию и испускает сигнал `positionReceived`,
который транслируется в JS через `pushPosition`. В будущих фазах здесь
появятся методы для запроса треков и конфигурации.
"""
from PySide6.QtCore import QObject, Signal, Slot


class WebBridge(QObject):
    """QObject-мост, опубликованный в QWebChannel под именем `bridge`."""

    # Сигнал Python → JS. JS подключается через bridge.positionReceived.connect(...)
    positionReceived = Signal(dict)

    @Slot(dict)
    def pushPosition(self, position: dict):
        """JS может вызывать bridge.pushPosition(pos) — пробрасываем дальше."""
        self.positionReceived.emit(position)

    @Slot(str, result=str)
    def echo(self, value: str) -> str:
        """Простая тестовая точка для проверки канала."""
        return value
