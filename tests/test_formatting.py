"""Тесты format_age («обновлён» в таблице трекеров) для ru и en."""
import time

from meshtrack.app import format_age


def _age(seconds: int) -> str:
    return format_age(time.time() - seconds)


def test_none():
    assert format_age(None) == "—"


def test_under_minute(use_lang):
    use_lang("ru")
    assert _age(0) == "0 с"
    assert _age(59) == "59 с"
    use_lang("en")
    assert _age(0) == "0 s"
    assert _age(59) == "59 s"


def test_minutes_only_below_two_hours(use_lang):
    use_lang("ru")
    assert _age(60) == "1 минута"
    assert _age(17 * 60) == "17 минут"
    assert _age(3599) == "59 минут"
    use_lang("en")
    assert _age(60) == "1 minute"
    assert _age(17 * 60) == "17 minutes"
    assert _age(3599) == "59 minutes"


def test_hours_minutes_below_two_hours(use_lang):
    use_lang("ru")
    assert _age(60 * 60 + 17 * 60) == "1 час 17 минут"
    use_lang("en")
    assert _age(60 * 60 + 17 * 60) == "1 hour 17 minutes"


def test_hours_only_from_two_hours(use_lang):
    use_lang("ru")
    assert _age(5 * 3600) == "5 часов"
    assert _age(7200) == "2 часа"
    use_lang("en")
    assert _age(5 * 3600) == "5 hours"
    assert _age(7200) == "2 hours"


def test_days_hours_below_two_days(use_lang):
    use_lang("ru")
    assert _age(29 * 3600) == "1 день 5 часов"
    assert _age(104400) == "1 день 5 часов"
    use_lang("en")
    assert _age(29 * 3600) == "1 day 5 hours"
    assert _age(104400) == "1 day 5 hours"


def test_days_only_from_two_days(use_lang):
    use_lang("ru")
    assert _age(172800) == "2 дня"
    assert _age(3 * 86400 + 20) == "3 дня"
    use_lang("en")
    assert _age(172800) == "2 days"
    assert _age(3 * 86400 + 20) == "3 days"


def test_plural_forms(use_lang):
    use_lang("ru")
    assert _age(21 * 60) == "21 минута"
    assert _age(23 * 3600) == "23 часа"
    assert _age(5 * 86400) == "5 дней"
    use_lang("en")
    assert _age(21 * 60) == "21 minutes"
    assert _age(23 * 3600) == "23 hours"
    assert _age(5 * 86400) == "5 days"