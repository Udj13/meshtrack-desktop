# MeshTrack Desktop — описание проекта

> Настольное оффлайн-приложение для живого трекинга планеров и парапланеров.
> Данные приходят от LoRa-приёмника через USB/serial; позиции отображаются на
> локальной топографической карте с вектором движения, высотой и трендом
> набора/снижения. Работает без интернета после первичной загрузки карт.

Этот документ — единственный источник истины по архитектуре и спецификациям.
Пошаговая реализация — в `PLAN.md`. Любой агент/разработчик, начинающий новую
фазу, обязан сначала прочитать этот файл.

---

## 1. Назначение и аудитория

- **Что делает:** читает пакеты с LoRa-приёмника (USB-UART), парсит
  телеметрию летателей (id, координаты, высота, заряд, SOS), показывает их на
  карте, сохраняет историю перемещений локально.
- **Аудитория:** пилоты и наземная поддержка без компьютерных навыков.
  Установка = скачать один установщик и запустить. Никаких IDE, Python,
  драйверов настраивать не нужно (кроме стандартных USB-UART драйверов ОС).
- **Платформы:** Windows 10/11 x64, macOS 12+ (Intel и Apple Silicon).
- **Полный оффлайн:** единственная сетевая активность — (а) однократная
  загрузка карт при первом запуске, (б) опциональная отправка на Traccar
  (по умолчанию **выключена**, включается в настройках).

## 2. Легаси-источник

Исходник `main.py` (консольный монитор; удалён из репо в Фазе 5): чтение serial (115200 baud), сборка
текстовых блоков между маркерами `Radio Received packet!` …
`Postfix: OK` / `Received valid LoRa data packet!`, парсинг regex’ами,
опциональная отправка на Traccar (free-gps.ru:5055). Парсер переносится в
`meshtrack/parser.py` почти без изменений (см. §6).

## 3. Технологический стек

| Слой | Выбор | Почему |
|---|---|---|
| Язык | Python 3.11+ | ровно тот же язык, что легаси-парсер |
| GUI | PySide6 (Qt 6) | нативный вид, QtWebEngine для карты, сборка PyInstaller |
| Карта (JS) | Leaflet 1.9 (локально, из assets) | растровые топо-тайлы, простота кастомного протокола |
| Тайлы | MBTiles (SQLite-контейнер, PNG внутри) | один файл на область, оффлайн-раздача через `map://` |
| История | SQLite (WAL) | ноль администрирования, встроенная |
| Serial | pyserial | как в легаси |
| HTTP | requests | загрузка тайлов + Traccar |
| Тесты | pytest | unit + интеграционные без GUI |
| Сборка | PyInstaller (onedir) + Inno Setup (Win) / DMG (macOS) | один установщик |

Виртуальное окружение — `.venv/` **внутри корня проекта** (см. §13 команды).

## 4. Архитектура

```
┌─────────────────────────── PySide6 app ───────────────────────────┐
│ tools/fake_serial.py (тест) ─┐                                     │
│                              ▼                                     │
│ SerialWorker (QThread) ──► Parser (чистая функция)                 │
│                              │ dict(id, lat, lon, alt, batt, ...)  │
│                              ▼                                     │
│                        Repository (SQLite) ──► Derivation          │
│                          history append        (GS, курс, vario)   │
│                              │                                     │
│                              ▼                                     │
│                     WebBridge (QWebChannel)                        │
│                              │ pushPosition(...) / setTrack(...)   │
│                              ▼                                     │
│   QtWebEngine ◄─ Leaflet ──► маркеры/стрелки/треки                 │
│       ▲                                                          │
│       │ map://{map_id}/{z}/{x}/{y}.png                            │
│   MapSchemeHandler ──► MapStore (MBTiles/SQLite)                   │
│                                                                  │
│ Настройки: config.json  |  TraccarPublisher (опция, по ум. ВЫКЛ)   │
└─────────────────────────────────────────────────────────────────────┘
```

### Модули (пакет `meshtrack/`)

| Модуль | Ответственность |
|---|---|
| `meshtrack/parser.py` | Чистый парсер raw-блока → dict. Не зависит от Qt. Докарп кандидат legacy-regex’ов. |
| `meshtrack/serial_worker.py` | QThread: открытие порта, сборка блоков по маркерам, `sig_position(dict)`. |
| `meshtrack/derivation.py` | По истории точек считает GS (geometry-ema), курс (bearing), варио (Δalt/Δt). |
| `meshtrack/repository.py` | SQLite: `positions`, `trackers`; append; запросы по фильтрам. |
| `meshtrack/mapstore.py` | Работа с MBTiles: создание, вставка тайлов, чтение, verify. |
| `meshtrack/downloader.py` | Скачивание тайлов по bbox/zooms с rate-limit, resume, прогрессом. |
| `meshtrack/regions.py` | Встроенные регионы (bbox по трём аэродромам), пользовательские bbox. |
| `meshtrack/webbridge.py` | QObject-мост Python↔JS (QWebChannel): positions, tracks, config. |
| `meshtrack/publisher.py` | TraccarPublisher: очередь + retry; при `enable=False` — no-op (см. §11). |
| `meshtrack/exporter.py` | Экспорт треков за период в GPX/CSV (чистые функции, без Qt). |
| `meshtrack/app.py` | MainWindow: карта + панель трекеров, статус-бар, dock-виджет лога, диалог настроек. |
| `meshtrack/logutil.py` | Настройка логирования: файл в `app_data_dir` + `QtLogHandler` для UI. |
| `meshtrack/settings.py` | `config.json`: traccar_on, слои, palette, retention, serial prefs. |
| `meshtrack/demo.py` | Демо-режим (`--demo` / `MESHTRACK_DEMO=1`): `DemoWorker` с моковыми позициями и заполнение истории; отдельная БД, по умолчанию выключен. |
| `tools/fake_serial.py` | Генератор сценариев для тестов (см. §10). |
| `tools/download_region.py` | CLI скачивания области → MBTiles. |

### Структура каталогов

```
MeshTrack desktop/
├─ PROJECT.md            # этот файл
├─ PLAN.md               # фазы и критерии
├─ requirements.txt
├─ .gitignore
├─ .venv/                # локальное окружение (git-ignored)
├─ meshtrack/
│  ├─ __init__.py
│  ├─ __main__.py        # python -m meshtrack -> app
│  └─ ... модули по таблице выше
├─ assets/
│  └─ web/               # index.html, app.js, leaflet.(js|css) локально, icons
├─ tools/                # fake_serial.py, download_region.py
├─ tests/
└─ installer/            # PyInstaller spec, inno/dmg скрипты (git-ignored вывод)
```

## 5. Пользовательский интерфейс

Главное окно: **карта** (слева) + **панель трекеров** (справа, 300px).

- **Маркер летателя:** круг Ø 14px цвета трекера (см. палитру), белая обводка.
  Внутри — тренд: `▲` (набор), `▼` (снижение), `—` (ровно). При SOS —
  красная пульсирующая рамка. Если последняя позиция старше 20 минут,
  маркер и стрелка рисуются серыми (данные устарели, но устройство всё ещё
  известно/включено).
- **Стрелка курса:** от маркера, повёрнута по курсу, длина ∝ GS
  (1 px/(км/ч), cap 80px, цвет = цвет трекера, полупрозрачная).
- **Трек:** polyline того же цвета; режим цвета переключается в настройках:
  «палитра», «градиент по высоте» (синий→красный по MSL),
  «градиент по варио» (зелёный набор / красный снижение).
- **Попап** по клику на маркер: скорость (км/ч), высота MSL (м), варио (м/с с ▲/▼),
  заряд %, напряжение В, «обновлено N с назад», флаг SOS и ссылка
  «Показать/скрыть трек».
- **Панель трекеров:** строка = цвет-чип + id + скорость + alt + тренд + заряд +
  «last update»; устаревшим (>20 мин) добавляется `(!)` и «last update»
  рисуется серым текстом; клик — центрирует карту и показывает трек; двойной
  клик — скрывает трек (повторный клик — снова показывает).
- **Фильтр истории:** «Сегодня / Вчера / Период…» (QDateTimeEdit-диалог).
- **Статус-бар:** порт (зелёный = подключён) • очередь из легаси (если есть
  в потоке) • активных трекеров • зона загрузки карты (для мастера).
- **Диалог «Настройки»:** тумблер Traccar, порт/baud (из `list_ports`),
  retention_days, «Экспорт GPX/CSV» (все трекеры за текущий фильтр истории,
  через `QFileDialog`). При старте приложение подключается к `port_pref`,
  если порт доступен, иначе — к единственному присутствующему.

**Палитра (12 цветов, детерминированно по id):** `#e6194b #3cb44b #ffe119
#4363d8 #f58231 #911eb4 #46f0f0 #f032e6 #bfef45 #3cb44b #808000 #9a6324`

## 6. Входные данные (формат пакета)

Пакет = набор строк между `Radio Received packet!` и
`Postfix: OK` (или `Received valid LoRa data packet!`). Парсимые поля
(legacy-regex’ы, перенесены в `meshtrack/parser.py`):

```
Device ID: 123
Latitude:  54.12345
Longitude: 45.67890
Altitude:  1230        # метры (MSL)
Date/Time: 2026-09-10 12:34:56
SOS: 0                 # 1 = тревога
Battery Voltage: 4020  # мВ
Battery Level: 87%     # %
```

- Все поля опциональны; минимум для обновления позиции — `id`, `lat`, `lon`.
- `id` нормализуется как `boon{id}` (наследие легаси; сохраняем).
- `Date/Time` → ISO `YYYY-MM-DDTHH:MM:SSZ` + `device_ts` (unix epoch, UTC);
  ошибка → `timestamp` = `'N/A'`, `device_ts` отсутствует.
- Строки `Queue size: N` распознаются отдельно (индикатор нагрузки приёмника).
- Разумно-полей: lat −90…90, lon −180…180, alt 0…10000 — иначе запись
  отклоняется (считается в log).

## 7. Производные метрики (`derivation.py`)

Из последних точек трекера (окно ≤ 60 сек, минимум 2 точки; время `ts` —
с устройства, считается UTC-точным):
- **GS** = haversine(последний сегмент)/Δt, сглаживание EMA (α = 0.5);
  если окно пусто → `None`.
- **Курс** = bearing(последнего сегмента), ° (0=N, 90=E), сглаж. EMA.
- **Варио** = (alt_last − alt_earliest) / Δt_window (м/с); тренд:
  `▲` если > +0.5, `▼` если < −0.5, иначе `—`.
- Все вычисления чистые функции принимающие `list[(t, lat, lon, alt)]` →
  `dict(gs, course, vario, trend)` (unit-тестируемо).

Актуальность (возраст в панели/попапе, «устарел >20 мин») считается
относительно времени устройства; «живость» канала (статус «Активных: N») —
по времени приёма `recv_ts`.

## 8. Карты

- **Слой:** топографическая = OpenTopoMap
  (`https://tile.opentopomap.org/{z}/{x}/{y}.png`, растровые PNG).
- **Формат хранения:** MBTiles (SQLite): `metadata(name)`, `tiles(zoom_level,
  tile_column, tile_row, tile_data)`; один файл = одна область.
- **Доставка в Leaflet:** приложение регистрирует scheme `map`; URL
  `map://{map_id}/{z}/{x}/{y}.png` → `MapSchemeHandler` (потомок
  `QWebEngineUrlSchemeHandler`) читает BLOB из MBTiles; при отсутствии —
  1×1 прозрачный PNG­-заглушка.
- **Скачивание:** перв-запуск мастер (список предопределённых регионов или
  произвольный bbox через мини-карту), потоковый downloader с rate-limit
  (≥ 200 мс между запросами), resume (чек-point в config), прогресс по
  файлу-мапе. Регион «город» ≈ 50–150 МБ (z 9–15).
- **Встроенные регионы** (координаты `regions.py`, **уточнить у заказчика**):

| id map | Регион | S–N (lat) | W–E (lon) |
|---|---|---|---|
| `lyambir_airfield` | Мордовия — аэродром Лямбирь (радиус 15 км) | 54.15263–54.42291 | 44.93453–45.39755 |
| `napolnaya_tavla` | Мордовия — Напольная Тавла / Кочкурово / Семилей (радиус 15 км) | 53.88496–54.15524 | 45.17828–45.63832 |
| `penza_sosnovka` | Пензенская обл. — аэродром Сосновка | 52.25–52.95 | 44.55–45.55 |
| `lenoblast_nikolskoe` | Ленинградская обл. — аэродром Никольское | 59.30–59.85 | 29.60–30.70 |

  Пользователь может добавить новые bbox через Настройки (JSON-редактор).
- **Пути хранения:** Windows `%APPDATA%/MeshTrack/`, macOS
  `~/Library/Application Support/MeshTrack/` — `maps/*.mbtiles`, `meshtrack.db`,
  `config.json`.

## 9. Данные (SQLite `meshtrack.db`)

```sql
CREATE TABLE trackers(
  id TEXT PRIMARY KEY,          -- boon123
  name TEXT,                     -- опциональный человекочит. ярлык
  color TEXT                     -- назначенный цвет палитры
);
CREATE TABLE positions(
  ts REAL,                       -- время с устройства (unix epoch; при
                                 -- недоступности Date/Time — время приёма)
  tracker_id TEXT,
  lat REAL, lon REAL, alt REAL,
  batt REAL, voltage REAL, sos INTEGER,
  recv_ts REAL,                  -- время приёма пакета на ПК
  PRIMARY KEY(ts, tracker_id)
);
CREATE INDEX idx_pos_trk_ts ON positions(tracker_id, ts);
```

Миграция: колонка `recv_ts` добавляется через `ALTER TABLE` при первом
запуске на старой БД; существующие строки получают `recv_ts = ts`.
Пакеты в одну и ту же секунду устройства перезаписываются
(`INSERT OR REPLACE`, допустимо для LoRa).

Retention: по умолчанию хранить 90 дней; настройка «очистить историю». WAL.

## 10. Тестовая инфраструктура

`tools/fake_serial.py` — генератор сценариев через
`pty` (mac/Linux) или loopback (Win, com0com отсутствует — тесты дер ворм на
PySide-less pipeline): выдаёт легаси-текст на stdout-файл, который SerialWorker
может открыть как File в `--port aux` режиме. Сценарии:
- `static` — точка без движения (проверка GS≈0, тренд «—»);
- `circle` — круг 200 м, GS ~40 км/ч (проверка угла/длины стрелки);
- `climb` — набор +1.5 м/с (тренд ▲);
- `descend` — снижение (−2 м/с, ▼);
- `sos` — всплеск SOS=1 (красная подсветка).
Сценарии описываются в код-комментах и воспроизводимы без GUI (repo+de­riv).

## 11. Traccar (опция)

- Тумблер в Настройках «Отправлять на Traccar (free-gps.ru)», **off by
  default**.
- При on: очередь + retry (5 failed → пауза 5 мин, payload возвращается в
  очередь), endpoint фиксированный `http://free-gps.ru:5055`, payload как в
  легаси (id, lat, lon, altitude, timestamp ISO, sos, voltage, batt, ttl=3);
  отправка в фоновом потоке (`threading`), интерфейс не блокируется.
- Выключен → `enqueue()` — no-op, ни одного сетевого запроса (тест Фазы 5).

## 12. Сборка и дистрибуция

- PyInstaller (onedir):
  - Windows → `installer/win/MeshTrack.spec` + Inno Setup script `setup.iss`
    → `MeshTrackSetup.exe`
  - macOS → `MeshTrack.spec` → `.app` → `hdiutil` → `MeshTrack.dmg`
- Подпись: нет (Gatekeeper: запуск правой-кнопкой «Открыть», SmartScreen:
  «Подробнее → Выполнить»). Документировать в README.
- Установщик содержит: QtWebEngine, Leaflet, иконки; карты — отдельно
  (пользователь качает регион в перв-запуск; оформить опцию выпуска
  «MeshTrackSetup-Saratov.exe» с предупакованным регіоном через GitHub
  Releases при необходимости).

## 13. Рабочие команды (dev)

```bash
python3 -m venv .venv
source .venv/bin/activate          # macOS/Linux;  на Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m meshtrack                 # запуск приложения
python -m meshtrack --demo          # демо-режим с моковыми данными (без приёмника)
MESHTRACK_DEMO=1 python -m meshtrack  # то же через переменную окружения
pytest -q                           # тесты
python tools/fake_serial.py --scenario climb --output /tmp/fake.txt
python tools/download_region.py --region lyambir_airfield --out ~/MeshTrack/maps/lyambir.mbtiles
```

Git workflow: каждая фаза завершается `git commit` + `git push` (remote
GitHub); сообщение вида `phase-N: <короткое имя>`.

## 14. Глоссарий

- **GS** — ground speed (км/ч), от показаний GPS-тракта.
- **Курс/Track** — направление движения, °.
- **Варио** — вертикальная скорость (м/с).
- **MSL** — высота над средним уровнем моря.
- **MBTiles** — SQLite-контейнер тайлов (спецификация mapbox).
- **LoRa-слой** — физический приёмник этих пакетов (внешний USB-UART).
- **Traccar** — сторонний сервер аггрегации (опция).
