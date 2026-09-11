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

    def as_dict(self) -> dict:
        """Возвращает копию текущей конфигурации."""
        return dict(self._config)
