"""Тесты format_age/display_id (`обновлён» и id трекера в UI)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meshtrack.app import display_id, format_age


def _age(seconds: int) -> str:
    return format_age(time.time() - seconds)


def test_none():
    assert format_age(None) == "—"


def test_under_minute():
    assert _age(0) == "0 с"
    assert _age(59) == "59 с"


def test_minutes_only_below_two_hours():
    assert _age(60) == "1 минута"
    assert _age(17 * 60) == "17 минут"
    assert _age(3599) == "59 минут"


def test_hours_minutes_below_two_hours():
    assert _age(60 * 60 + 17 * 60) == "1 час 17 минут"


def test_hours_only_from_two_hours():
    assert _age(5 * 3600) == "5 часов"
    assert _age(7200) == "2 часа"


def test_days_hours_below_two_days():
    assert _age(29 * 3600) == "1 день 5 часов"
    assert _age(104400) == "1 день 5 часов"


def test_days_only_from_two_days():
    assert _age(172800) == "2 дня"
    assert _age(3 * 86400 + 20) == "3 дня"


def test_plural_forms():
    assert _age(21 * 60) == "21 минута"
    assert _age(23 * 3600) == "23 часа"
    assert _age(5 * 86400) == "5 дней"


def test_display_id_strips_boon():
    assert display_id("boon2297873940") == "2297873940"
    assert display_id("boon1") == "1"


def test_display_id_leaves_rest():
    assert display_id("no-prefix") == "no-prefix"
    assert display_id("") == ""
    assert display_id("Boon5") == "Boon5"  # регистр важен