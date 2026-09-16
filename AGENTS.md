# AGENTS.md — гид по проекту для агента

Короткая ориентировка: что это за проект, как он работает и где что искать.
Полная архитектура и спецификации — в `PROJECT.md` (читай его перед
изменениями в соответствующих подсистемах).

## Что это

**MeshTrack Desktop** — оффлайн-настольное приложение для живого трекинга
планеров/парапланеристов. Данные приходят от LoRa-приёмника по USB-serial,
позиции показываются на локальной топографической карте (Leaflet в
QtWebEngine) с курсом, высотой и трендом набора/снижения. История хранится
в SQLite. Единственная сетевая активность — загрузка карт при первом запуске
и опциональная отправка на Traccar (по умолчанию выключена).

**Стек:** Python 3.11+, PySide6 (Qt 6 + QtWebEngine), Leaflet 1.9 (локально),
SQLite (история) + MBTiles (карты), pyserial, requests, pytest.
Сборка — PyInstaller (onedir) + Inno Setup (Win) / DMG (macOS).

## Как работает (поток данных)

```
LoRa-приёмник (USB-UART)
  → SerialWorker (QThread, meshtrack/serial_worker.py): построчное чтение
  → parser.parse_packet(line) (meshtrack/parser.py): JSON-строка → dict
  → app.py: запись в Repository (SQLite) + Derivation (GS/курс/варио)
  → Webbridge (QWebChannel) → Leaflet в QtWebEngine (assets/web/)
  └ тайлы: map://{map_id}/{z}/{x}/{y}.png → mapscheme.py → MapStore (MBTiles)
```

### Формат пакета (важно!)

Приёмник печатает **одну JSON-строку на принятый LoRa-пакет**:

```json
{"device_id":123,"lat":54.12345,"lon":45.67890,"alt":1230,
 "datetime":"2026-09-16T12:01:00","sos":0,"battery_pct":87,
 "battery_mv":4020,"rssi":"-27.00dBm","snr":"5.25dB","ttl":3,"crc":241}
```

- Парсится **только** JSON — строки «таблички» (`Radio Received packet!`,
  `Postfix: OK`, загрузочный лог ESP32) игнорируются.
- Обязательные поля: `device_id`, `lat`, `lon`; `alt` опционален.
- Маппинг в dict приложения: `device_id → id` (с префиксом `boon`),
  `alt → altitude`, `battery_pct → batt`, `battery_mv → voltage`,
  `datetime → timestamp` ("...Z") + `device_ts` (unix epoch), `sos`,
  `rssi`/`snr` → float (суффиксы отбрасываются), `ttl`/`crc` → int.
- Валидация диапазонов — `is_valid_position()` (lat −90..90, lon −180..180,
  alt 0..10000); невалидные пакеты отбрасываются.
- `Queue size: N` из строк порта → отдельный сигнал `queue_size` (индикатор
  нагрузки; реальное устройство это поле больше не шлёт).

## Где что искать

| Модуль | Что делает / где править |
|---|---|
| `meshtrack/parser.py` | Парсинг пакетов: `parse_packet()`, `parse_queue_size()`, `is_valid_position()`. Чистый, без Qt/serial. |
| `meshtrack/serial_worker.py` | QThread чтения serial/файла (`file://`), сигналы `position/raw_line/error/queue_size`. |
| `meshtrack/app.py` | `MainWindow`: карта, панель трекеров, попапы, статус-бар, диалоги настроек/карт, обработка всех сигналов, демо-режим. Самый большой модуль. |
| `meshtrack/repository.py` | SQLite-история: таблицы `positions`, `trackers`, retention. |
| `meshtrack/derivation.py` | Производные метрики: GS (EMA), курс (bearing), варио, тренд. Чистые функции. |
| `meshtrack/webbridge.py` | QObject-мост Python↔JS (`pushPosition`, `setTrack`, ...). |
| `assets/web/` | Фронт карты: `index.html`, `app.js`, Leaflet локально. |
| `meshtrack/mapstore.py`, `mapscheme.py` | MBTiles-хранилище и доставка тайлов по `map://`. |
| `meshtrack/downloader.py`, `map_manager.py`, `map_dialog.py`, `regions.py`, `first_run_wizard.py` | Скачивание тайлов, управление картами, встроенные регионы, мастер первого запуска. |
| `meshtrack/demo.py` | Демо-режим (`--demo` / `MESHTRACK_DEMO=1`): `DemoWorker`, `format_json()`, заполнение истории, имена трекеров (`TRACKER_NAMES`). |
| `meshtrack/publisher.py` | Traccar: очередь + retry; при `enable=False` — no-op. |
| `meshtrack/exporter.py`, `settings.py`, `logutil.py`, `licenses.py`, `licenses_dialog.py` | Экспорт GPX/CSV, `config.json`, логирование, лицензии. |
| `tools/fake_serial.py` | Генератор тестовых JSON-пакетов (сценарии static/circle/climb/descend/sos). |
| `tools/download_region.py` | CLI: скачивание области → MBTiles. |
| `tools/screenshot.py` | Пересъёмка скриншотов лендинга: демо-режим + `QWidget.grab()` → `site/assets/img/`. |
| `site/` | Лендинг проекта (статический HTML, RU). Деплой и TODO — в `site/README.md` (§15 PROJECT.md). |

## Тесты и команды

```bash
.venv/bin/python -m pytest -q        # все тесты (130+)
.venv/bin/python -m meshtrack        # запуск приложения
.venv/bin/python -m meshtrack --demo # демо-режим без приёмника
.venv/bin/python tools/fake_serial.py --scenario circle --count 5 --output /tmp/f.txt
```

- Тесты headless: парсер/derivation/repository — без Qt; `SerialWorker`
  тестируется через `file://`-источник; GUI-тесты не требуются.
- Приёмник реального устройства: `/dev/cu.usbserial-0001`, 115200 baud,
  CP2102. Открытие порта сбрасывает ESP32 — для чтения держи DTR/RTS = False.
- Данные приложения: `~/Library/Application Support/MeshTrack/`
  (`config.json`, `meshtrack.db`, `maps/*.mbtiles`, `meshtrack.log`).

## Конвенции

- Модули без Qt/serial-зависимостей держать «чистыми» (тестируемость).
- Документация в `PROJECT.md` — источник истины; обновляй её при изменении
  поведения/форматов.
- Сообщения коммитов вида `feat(...)`/`fix(...)`/`docs(...)` (см. `git log`).