"""Тесты meshtrack/i18n.py: загрузка каталогов, плюралы, полнота перевода."""
import ast
import json
from pathlib import Path

import pytest

from meshtrack import i18n
from meshtrack.i18n import Translator, init_translator

DATA_DIR = Path(__file__).resolve().parent.parent / "meshtrack" / "i18n_data"


def _load(lang: str) -> dict:
    with (DATA_DIR / f"catalog_{lang}.json").open(encoding="utf-8") as f:
        return json.load(f)["messages"]


def test_languages_const():
    assert i18n.LANGUAGES == ("ru", "en")


def test_tr_identity_for_ru():
    t = Translator("ru")
    assert t.tr("Настройки") == "Настройки"
    assert t.tr("нет такого ключа") == "нет такого ключа"


def test_tr_missing_key_falls_back_to_msgid():
    t = Translator("en")
    assert t.tr("несуществующий msgid") == "несуществующий msgid"


def test_tr_known_en_translation():
    t = Translator("en")
    assert t.tr("Настройки") == "Settings"
    assert t.tr("Трекеры") == "Trackers"


def test_plurals_ru():
    t = Translator("ru")
    assert t.pl("минута", 1) == "минута"
    assert t.pl("минута", 2) == "минуты"
    assert t.pl("минута", 5) == "минут"
    assert t.pl("минута", 21) == "минута"
    assert t.pl("день", 11) == "дней"


def test_plurals_en():
    t = Translator("en")
    assert t.pl("минута", 1) == "minute"
    assert t.pl("минута", 2) == "minutes"
    assert t.pl("минута", 5) == "minutes"
    assert t.pl("день", 1) == "day"
    assert t.pl("день", 3) == "days"


def test_pl_placeholder_replaced():
    t = Translator("en")
    # плейсхолдер {n} подставляется в выбранную форму
    assert t.pl("с", 45) == "s"


def test_unknown_language_falls_back_to_ru():
    t = Translator("de")
    assert t.code == "ru"


def test_global_init_and_current(use_lang):
    use_lang("en")
    assert i18n.current().code == "en"
    assert i18n.tr("Настройки") == "Settings"


def test_detect_system_language_ru(monkeypatch):
    monkeypatch.setattr(i18n.locale, "getlocale", lambda *a: ("ru_RU", "UTF-8"))
    assert i18n.detect_system_language() == "ru"


def test_detect_system_language_non_ru_is_en(monkeypatch):
    monkeypatch.setattr(i18n.locale, "getlocale", lambda *a: ("de_DE", "UTF-8"))
    assert i18n.detect_system_language() == "en"


def test_detect_system_language_env_fallback(monkeypatch):
    monkeypatch.setattr(i18n.locale, "getlocale", lambda *a: (None, None))
    monkeypatch.setenv("LC_ALL", "")
    monkeypatch.setenv("LC_MESSAGES", "")
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    assert i18n.detect_system_language() == "ru"


def test_catalog_ru_has_plural_units():
    msgs = _load("ru")
    for unit in ("с", "минута", "час", "день"):
        assert unit in msgs, f"каталог ru должен содержать {unit}"
        assert set(msgs[unit]) == {"one", "few", "many"}


def test_catalog_en_plural_units():
    msgs = _load("en")
    for unit in ("с", "минута", "час", "день"):
        assert unit in msgs
        assert set(msgs[unit]) == {"one", "other"}


def _collect_python_msgids() -> set[str]:
    """Все литеральные msgid, использованные через _()/tr() в meshtrack/*.py
    (с учётом неявной конкатенации строковых литералов)."""
    sys = Path(__file__).resolve().parent.parent / "meshtrack"
    found: set[str] = set()
    for path in sorted(sys.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id not in ("_", "tr"):
                continue
            parts = []
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    parts.append(arg.value)
                else:
                    break
            else:
                if parts:
                    found.add("".join(parts))
    return found


def test_en_catalog_covers_python_msgids():
    en = _load("en")
    missing = sorted(_collect_python_msgids() - set(en))
    assert missing == [], f"нет перевода(msgid) в catalog_en.json: {missing}"


def test_js_catalog_covers_popup_keys():
    js = (Path(__file__).resolve().parent.parent / "assets" / "web" / "i18n.js").read_text(
        encoding="utf-8"
    )
    keys = [
        "Данные устарели (>20 мин)",
        "Скрыть трек",
        "Показать трек",
        "Скорость: {v}",
        "Курс: {v}°",
        "Высота: {v} м",
        "Варио: {v}",
        "Заряд: {v} ({v2})",
        "Обновлено {age} назад",
    ]
    for key in keys:
        assert f'"{key}"' in js, f"нет ключа в i18n.js: {key}"


def test_en_plurals_only_two_forms():
    en = _load("en")
    for key, val in en.items():
        if isinstance(val, dict):
            assert set(val) <= {"one", "other"}, f"{key}: EN плюралы должны быть one/other"


def test_en_translations_are_strings_or_dicts():
    en = _load("en")
    assert all(isinstance(v, (str, dict)) for v in en.values())


def test_en_covers_dynamic_labels():
    """Метки, передаваемые в _() динамически (по значению)."""
    from meshtrack.map_dialog import ACTIONS, COLUMNS, STATUS_LABELS

    action_labels = {t[0] for items in ACTIONS.values() for t in items}
    en = _load("en")
    needed = set(STATUS_LABELS.values()) | action_labels | set(COLUMNS)
    missing = sorted(needed - set(en))
    assert missing == [], f"нет перевода динамических меток в catalog_en.json: {missing}"