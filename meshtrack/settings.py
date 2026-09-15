"""Управление конфигурацией приложения в config.json.

Файл располагается в app_data_dir (PROJECT.md §8). В Фазе 3 поддерживаются
минимальные ключи: retention_days и track_color_mode. В Фазе 5 схема
расширится до полноценных настроек.
"""
from __future__ import annotations

import json
from pathlib import Path


DEFAULT_CONFIG = {
    "retention_days": 90,
    "track_color_mode": "palette",  # palette | altitude | vario
    "maps": [],  # список dict{id, name, path}
    "active_map_id": None,
    "traccar_on": False,
    "port_pref": "",
    "baud": 115200,
    "exports_dir": "",
}

VALID_COLOR_MODES = ("palette", "altitude", "vario")


class Settings:
    """JSON-конфиг приложения с ленивой загрузкой и сохранением."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._config: dict = {}
        self.load()

    def load(self) -> None:
        """Загружает config.json или создаёт значения по умолчанию."""
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self._config = {**DEFAULT_CONFIG, **loaded}
                else:
                    self._config = dict(DEFAULT_CONFIG)
            except (json.JSONDecodeError, OSError):
                self._config = dict(DEFAULT_CONFIG)
        else:
            self._config = dict(DEFAULT_CONFIG)
        self._normalize()

    def save(self) -> None:
        """Атомарно сохраняет текущую конфигурацию на диск."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)

    def _normalize(self) -> None:
        try:
            self._config["retention_days"] = int(self._config.get("retention_days", 90))
        except (TypeError, ValueError):
            self._config["retention_days"] = 90
        if self._config.get("track_color_mode") not in VALID_COLOR_MODES:
            self._config["track_color_mode"] = "palette"
        self._config["traccar_on"] = bool(self._config.get("traccar_on", False))
        if not isinstance(self._config.get("port_pref"), str):
            self._config["port_pref"] = ""
        if not isinstance(self._config.get("exports_dir"), str):
            self._config["exports_dir"] = ""
        try:
            baud = int(self._config.get("baud", 115200))
        except (TypeError, ValueError):
            baud = 115200
        self._config["baud"] = baud if baud > 0 else 115200
        if not isinstance(self._config.get("maps"), list):
            self._config["maps"] = []
        # Убираем записи без обязательных полей
        self._config["maps"] = [
            m for m in self._config["maps"]
            if isinstance(m, dict) and m.get("id") and m.get("path")
        ]

    @property
    def retention_days(self) -> int:
        return int(self._config.get("retention_days", 90))

    @retention_days.setter
    def retention_days(self, value: int) -> None:
        self._config["retention_days"] = int(value)

    @property
    def track_color_mode(self) -> str:
        return self._config.get("track_color_mode", "palette")

    @track_color_mode.setter
    def track_color_mode(self, value: str) -> None:
        if value not in VALID_COLOR_MODES:
            value = "palette"
        self._config["track_color_mode"] = value

    @property
    def traccar_on(self) -> bool:
        """Отправлять ли позиции на Traccar (по умолчанию False)."""
        return bool(self._config.get("traccar_on", False))

    @traccar_on.setter
    def traccar_on(self, value: bool) -> None:
        self._config["traccar_on"] = bool(value)

    @property
    def port_pref(self) -> str:
        """Предпочитаемый serial-порт ('' если не задан)."""
        return self._config.get("port_pref", "")

    @port_pref.setter
    def port_pref(self, value: str) -> None:
        self._config["port_pref"] = str(value or "")

    @property
    def baud(self) -> int:
        """Скорость serial-порта."""
        try:
            return int(self._config.get("baud", 115200))
        except (TypeError, ValueError):
            return 115200

    @baud.setter
    def baud(self, value: int) -> None:
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 115200
        self._config["baud"] = value if value > 0 else 115200

    @property
    def exports_dir(self) -> str:
        """Последняя папка экспорта ('' если не задана)."""
        return self._config.get("exports_dir", "")

    @exports_dir.setter
    def exports_dir(self, value: str) -> None:
        self._config["exports_dir"] = str(value or "")

    @property
    def maps(self) -> list[dict]:
        """Список карт [{id, name, path}]."""
        return list(self._config.get("maps", []))

    @property
    def has_maps(self) -> bool:
        """True, если в конфиге есть хотя бы одна карта."""
        return len(self._config.get("maps", [])) > 0

    @property
    def active_map_id(self) -> str | None:
        """Id активной карты или None."""
        return self._config.get("active_map_id")

    @active_map_id.setter
    def active_map_id(self, value: str | None) -> None:
        self._config["active_map_id"] = value

    def default_map_id(self) -> str | None:
        """Возвращает id первой доступной карты."""
        maps = self._config.get("maps", [])
        return maps[0]["id"] if maps else None

    def first_existing_map_id(self) -> str | None:
        """Возвращает id первой карты, чей файл существует на диске."""
        for m in self._config.get("maps", []):
            path = m.get("path")
            if path and Path(path).exists():
                return m.get("id")
        return None

    def get_map_path(self, map_id: str) -> str | None:
        """Путь к MBTiles по id карты."""
        for m in self._config.get("maps", []):
            if m.get("id") == map_id:
                return m.get("path")
        return None

    def add_map(
        self,
        map_id: str,
        name: str,
        path: str,
        south: float | None = None,
        north: float | None = None,
        west: float | None = None,
        east: float | None = None,
        zmin: int | None = None,
        zmax: int | None = None,
    ) -> None:
        """Добавляет или обновляет карту. Дополнительные поля сохраняются, если заданы."""
        extra = {}
        if south is not None:
            extra["south"] = south
        if north is not None:
            extra["north"] = north
        if west is not None:
            extra["west"] = west
        if east is not None:
            extra["east"] = east
        if zmin is not None:
            extra["zmin"] = zmin
        if zmax is not None:
            extra["zmax"] = zmax
        maps = self._config.get("maps", [])
        for m in maps:
            if m.get("id") == map_id:
                m["name"] = name
                m["path"] = path
                m.update(extra)
                return
        maps.append({"id": map_id, "name": name, "path": path, **extra})
        self._config["maps"] = maps

    def remove_map(self, map_id: str) -> bool:
        """Удаляет карту из конфига. Возвращает True если была удалена."""
        before = self._config.get("maps", [])
        after = [m for m in before if m.get("id") != map_id]
        self._config["maps"] = after
        if self._config.get("active_map_id") == map_id:
            self._config["active_map_id"] = self.first_existing_map_id()
        return len(after) < len(before)

    def as_dict(self) -> dict:
        """Возвращает копию текущей конфигурации."""
        return dict(self._config)
