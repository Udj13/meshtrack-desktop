"""Общие фикстуры для тестов: язык каталога переводов.

Глобальный переводчик сбрасывается в "ru" до и после каждого теста,
чтобы порядок исполнения не влиял на результаты.
"""
import pytest

from meshtrack import i18n


@pytest.fixture(autouse=True)
def _reset_lang_before():
    i18n.init_translator("ru")
    yield


@pytest.fixture(autouse=True)
def _reset_lang_after():
    yield
    i18n.init_translator("ru")


@pytest.fixture
def use_lang(_reset_lang_before):
    """Переключает язык в теле теста: set_lang(code)."""

    def _set(code: str):
        i18n.init_translator(code)

    yield _set