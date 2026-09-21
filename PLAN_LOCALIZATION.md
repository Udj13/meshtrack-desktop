# Локализация MeshTrack Desktop (RU + EN)

## Цель
Добавить английский язык и переключатель в настройках приложения. Стартовый
язык — русский (обратная совместимость).

## Ключевые решения
1. **Механизм** — собственный лёгкий модуль `meshtrack/i18n.py` (без Qt) на
   JSON-каталогах. Без gettext/QTranslator (UI строится Python-строками, не `tr()`).
2. **MSGID = русский** как источник, `catalog_en.json` — переводы. Минимальный
   дифф: существующие литералы только оборачиваются в `_()`.
3. **Live-переключение** без рестарта: модальные диалоги строятся по требованию,
   для `MainWindow` — метод `retranslate_ui()`.
4. **Логи не переводятся** (диагностика на русском), кроме заголовка дока «Лог»
   и статусов статус-бара (часть UI).
5. **Данные не переводятся**: имена демо-трекеров (`demo.TRACKER_NAMES`),
   названия регионов (`regions.PREBUILT_REGIONS`), псевдонимы в БД.

## Формат каталога (`meshtrack/i18n_data/catalog_*.json`)
```json
{
  "language": "en",
  "messages": {
    "Настройки": "Settings",
    "Порт: {port}": "Port: {port}",
    "{часом": {"one": "{n} hour", "few": "{n} hours", "many": "{n} hours"}
  }
}
```
Плюралы — по правилу языка (RU: one/few/many, EN: one/other).

## Фазы

### Фаза 0 — ядро локализации
- `meshtrack/i18n.py`: `Translator.load(code)`, `tr(msgid)`, `pl(msgid, n)`,
  глобальный хук `_`, `init_translator(lang)`.
- `meshtrack/i18n_data/catalog_ru.json` (identity) и `catalog_en.json`.
- Подключение в `app.py`: инициализация из `settings.language` до построения UI.

### Фаза 1 — настройка языка
- `settings.py`: ключ `language` в `DEFAULT_CONFIG` (`"ru"`),
  `VALID_LANGUAGES = ("ru", "en")`, property/setter, normalize.
- `SettingsDialog`: комбобокс «Язык / Language», добавление в `values()`,
  применение в `_open_settings`.

### Фаза 2 — Python-сторона UI
- Обернуть строки в app.py (панель трекеров, статус-бар, тулбар, меню, about,
  export/period/confirm диалоги, диалоги трекера).
- map_dialog.py, first_run_wizard.py, licenses_dialog.py.
- f-строки → `_("Порт: {port}").format(port=...)`.
- `_plural`/`format_age` перевести на `pl()` каталога.

### Фаза 3 — live-переключение
- `MainWindow.retranslate_ui()`: тулбар/меню/панель трекеров/статус-бар.
- Прокинуть язык в JS.

### Фаза 4 — Web-фронт
- `assets/web/i18n.js`: словари ru/en для строк app.js
  (попап, age, «Скрыть/Показать трек», «Данные устарели», SOS).
- Язык шлётся из Python в JS через `applyLanguage(code)` (`_push_language_to_js`);
  `WebBridge` слотов для языка не имеет.
- `<html lang>` и пересборка строк динамически.

### Фаза 5 — сборка
- PyInstaller: добавить `meshtrack/i18n_data/` в datas (spec Windows + macOS).

### Фаза 6 — тесты
- `test_i18n.py`: загрузка RU/EN, полнота EN-каталога, плюралы.
- Параметризация `test_formatting.py` по языку.
- `test_settings.py`: default/normalize `language`.

### Фаза 7 — документация
- Обновить PROJECT.md: подсистема локализации, ключ `language`,
  как добавлять язык.

## Оценка
- Фаза 0–1: ~полдня
- Фаза 2: ~день
- Фаза 3–4: ~день
- Фаза 5–7: ~день