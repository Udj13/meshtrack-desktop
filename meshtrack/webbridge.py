"""Мост Python ↔ JS через QWebChannel.

Python-сторона принимает позицию и испускает сигнал `positionReceived`,
который транслируется в JS через `pushPosition`. В Фазе 3 добавлены:
- запрос треков `getTrack` из JS;
- сигнал/метод `historyCleared` для очистки истории.
"""
import json

from PySide6.QtCore import QObject, Signal, Slot


class WebBridge(QObject):
    """QObject-мост, опубликованный в QWebChannel под именем `bridge`."""

    # Сигнал Python → JS. JS подключается через bridge.positionReceived.connect(...)
    positionReceived = Signal(dict)

    # Сигнализирует, что история позиций была очищена.
    historyCleared = Signal()

    def __init__(self, repo=None, settings=None, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._settings = settings

    @Slot(dict)
    def pushPosition(self, position: dict):
        """JS может вызывать bridge.pushPosition(pos) — пробрасываем дальше."""
        self.positionReceived.emit(position)

    @Slot(str, float, float, result=str)
    def getTrack(self, tracker_id: str, ts_from: float, ts_to: float) -> str:
        """Возвращает трек как JSON {"points": [...]}."""
        if self._repo is None:
            return json.dumps({"points": []})
        try:
            pts = self._repo.points(
                tracker_id,
                ts_from=ts_from if ts_from >= 0 else None,
                ts_to=ts_to if ts_to >= 0 else None,
            )
            return json.dumps({"points": pts})
        except Exception:
            return json.dumps({"points": [], "error": "query failed"})

    @Slot(result=str)
    def getColorMode(self) -> str:
        """Текущий режим раскраски треков."""
        if self._settings is None:
            return "palette"
        return self._settings.track_color_mode

    @Slot()
    def clearHistory(self):
        """Очищает все позиции в БД и сигнализирует JS."""
        if self._repo is not None:
            self._repo.clear_all_positions()
        self.historyCleared.emit()

    @Slot(str, result=str)
    def echo(self, value: str) -> str:
        """Простая тестовая точка для проверки канала."""
        return value
