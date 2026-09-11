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

    # Сигнализирует о смене активной карты (id для map://).
    activeMapChanged = Signal(str)

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

    @Slot(result=str)
    def getActiveMapId(self) -> str:
        """Id активной карты для URL map://{id}/{z}/{x}/{y}.png."""
        if self._settings is None:
            return ""
        return self._settings.active_map_id or self._settings.default_map_id() or ""

    @Slot(str)
    def setActiveMapId(self, map_id: str):
        """Устанавливает активную карту и уведомляет JS."""
        if self._settings is not None:
            self._settings.active_map_id = map_id
        self.activeMapChanged.emit(map_id)

    @Slot(result=int)
    def getMinZoom(self) -> int:
        """Минимальный zoom активной карты."""
        return self._map_zoom_range()[0]

    @Slot(result=int)
    def getMaxZoom(self) -> int:
        """Максимальный zoom активной карты."""
        return self._map_zoom_range()[1]

    def _map_zoom_range(self) -> tuple[int, int]:
        if self._settings is None:
            return 9, 15
        map_id = self._settings.active_map_id or self._settings.default_map_id()
        if not map_id:
            return 9, 15
        path = self._settings.get_map_path(map_id)
        if not path:
            return 9, 15
        try:
            from .mapstore import MapStore
            store = MapStore(path)
            return store.get_minmax_zoom()
        except Exception:
            return 9, 15

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
