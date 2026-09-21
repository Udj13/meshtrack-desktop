"""Лёгкая локализация: JSON-каталоги переводов без gettext/QTranslator.

MSGID — исходные русские строки; для языка \"ru\" каталог пустой
(identity: отсутствующий ключ возвращается как есть), для \"en\" —
каталог переводов. Плюралы хранятся как {one, few, many}/{one, other}
и выбираются по правилу языка через `pl`.

Модуль чистый (без Qt) — тестируется headless.
"""
from __future__ import annotations

import json
import locale
import os
from pathlib import Path

LANGUAGES = ("ru", "en")
DEFAULT_LANG = "ru"

_DATA_DIR = Path(__file__).parent / "i18n_data"


class Translator:
    """Загружает каталог перевода и отдаёт строки по msgid."""

    def __init__(self, code: str = DEFAULT_LANG, data_dir: Path | None = None):
        self.code = code if code in LANGUAGES else DEFAULT_LANG
        self._messages: dict = {}
        self._data_dir = Path(data_dir) if data_dir is not None else _DATA_DIR
        self._load()

    def _load(self) -> None:
        path = self._data_dir / f"catalog_{self.code}.json"
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data.get("messages"), dict):
                self._messages = data["messages"]
        except (OSError, json.JSONDecodeError):
            self._messages = {}

    @property
    def language(self) -> str:
        return self.code

    def tr(self, msgid: str) -> str:
        """Возвращает перевод msgid или сам msgid, если перевода нет."""
        if not self._messages:
            return msgid
        msg = self._messages.get(msgid)
        if isinstance(msg, str):
            return msg
        return msgid

    def pl(self, msgid: str, n: int) -> str:
        """Возвращает перевод msgid с выбором плюрал-формы по числу n.

        Если перевод не найден или это не словарь плюралов — вернёт msgid.
        Плюрал-шаблон поддерживает плейсхолдер {n}.
        """
        msg = self._messages.get(msgid, {}) if self._messages else {}
        if not isinstance(msg, dict):
            return msgid
        form = self._plural_form(n)
        result = msg.get(form, msgid)
        if isinstance(result, str) and "{n}" in result:
            result = result.replace("{n}", str(n))
        return result

    def _plural_form(self, n: int) -> str:
        if self.code == "ru":
            if n % 10 == 1 and n % 100 != 11:
                return "one"
            if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
                return "few"
            return "many"
        # en / default
        return "one" if n == 1 else "other"


_current = Translator(DEFAULT_LANG)


def init_translator(code: str) -> Translator:
    """Устанавливает глобальный переводчик по коду языка."""
    global _current
    _current = Translator(code)
    return _current


def current() -> Translator:
    return _current


def tr(msgid: str) -> str:
    """Глобальная функция перевода (аналог gettext _())."""
    return _current.tr(msgid)


def pl(msgid: str, n: int) -> str:
    """Глобальная функция перевода с плюралами."""
    return _current.pl(msgid, n)


def detect_system_language() -> str:
    """Определяет язык по локали ОС: 'ru' для русской системы, иначе 'en'.

    Fallback (без Qt): локаль процесса, затем переменные окружения. В GUI
    вызывающий код может уточнить результат через QLocale.system().
    """
    raw = ""
    try:
        lang = locale.getlocale()[0]
        if lang:
            raw = lang
    except (ValueError, TypeError):
        pass
    if not raw:
        for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
            value = os.environ.get(var)
            if value:
                raw = value
                break
    code = raw.split(".")[0].split("_")[0].strip().lower()
    return "ru" if code == "ru" else "en"