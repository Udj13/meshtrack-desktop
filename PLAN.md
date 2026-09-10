# MeshTrack Desktop — поэтапный план реализации

> Каждая фаза самодостаточна: в ней описаны цель, входные условия, файлы,
> проверки (команды/тесты) и критерии завершения. Перед стартом любой фазы
> прочитай `PROJECT.md` — там архитектура, форматы, UI-спецификация и
> команды. После успешной фазы делается commit + push
> (сообщение `phase-N: …`).

Статус: ✅ — выполнена, 🔄 — в работе, ⛶ — не начата.

| # | Фаза | Статус |
|---|---|---|
| 0 | Скелет: parser, fake_serial, env, Qt-окно | ⛶ |
| 1 | Живые маркеры: serial-QThread → repo → bridge → Leaflet | ⛶ |
| 2 | Вектор GS/курс/варио + панель трекеров | ⛶ |
| 3 | История и треки, фильтры по дате | ⛶ |
| 4 | Карты: first-run мастер, downloader, MBTiles, map:// | ⛶ |
| 5 | Traccar-опция, настройки, экспорт GPX/CSV | ⛶ |
| 6 | Сборка: PyInstaller, Inno (Win), DMG (macOS) | ⛶ |
| 7 | (Опц.) Импорт Ozi `.map + .png/.jpg` → MBTiles | ⛶ |

---

## Фаза 0 — Скелет проекта

**Цель:** инфраструктура + чистый парсер (из legacy) + генератор тестовых
сценариев + пустое Qt-окно.

**Вход:** ничего кроме этого репо и `main.py` (легаси).

**Результаты:**
- `.gitignore`, `requirements.txt` (PySide6, pyserial, requests, pytest,
  pyinstaller), `.venv/`
- `meshtrack/__init__.py`, `meshtrack/__main__.py`, `meshtrack/app.py`
  (пустое MainWindow, заголовок «MeshTrack»)
- `meshtrack/parser.py` — `parse_data(block: str) -> dict`; regex’ы и норма-
  лизация `id → boon{id}` взяты из `main.py` **без изменений логики**;
  исключены serial/Qt зависимости
- `tools/fake_serial.py` — сценарии `static|circle|climb|descend|sos`, флаг
  `--output FILE` (пишет текст-пакеты), `--interval S` (default 0.5с)
- `tests/test_parser.py` — fixture-строки каждой сценарий → assert-ы полей

**Проверки (все должны пройти):**
1. `pytest -q` — зелёный (parser).
2. `python -m meshtrack` — открывается окно с заголовком «MeshTrack» (можно
   закрыть вручную, CI-вариант: `QT_QPA_PLATFORM=offscreen pytest` пропускаем).
3. `python tools/fake_serial.py --scenario climb --output /tmp/f.txt` — файл
   с пакетами; `python - <<EOF` import parser, прочитать, разобрать — ок.
4. `python -c "import meshtrack"` — импорты чисты.

**Завершение:** commit `phase-0: parser + skeleton`.

---

## Фаза 1 — Живые маркеры на карте

**Цель:** от serial до Leaflet-маркера.

**Вход:** Фаза 0.

**Результаты:**
- `meshtrack/serial_worker.py` — QThread; API:
  `SerialWorker(port: str, baud=115200)`, сигналы `position(dict)`,
  `raw_line(str)`, `error(str)`; сборка блоков: маркер-start
  «Radio Received packet!», end «Postfix: OK» | «Received valid LoRa data
  packet!»; stop() пробрасывает `ser.close()`; отклонение `Queue size: N`
  отдельным сигналом `queue_size(int)`
- `meshtrack/repository.py` — SQLite (WAL); API: `Repository(db_path)`;
  `add_position(trk, lat, lon, alt, batt, volt, sos)`; `latest(track_id)`;
  `active_trackers(max_age_s=300)`
- `meshtrack/webbridge.py` — QObject:
  `positionReceived(dict)` — Python сторона; `pushPosition` — JS-invokable
  через `QWebChannel` (`webChannel.js` локально в assets)
- `assets/web/index.html`, `app.js`, локальная копия `leaflet.js/css`
  (скачивается один раз, фиксируется в репо)
- UI: маркер = circle (radius 7, цвет из palette по hash(id)), popup c полями;
  авто-подключение если доступен ровно 1 serial-порт (иначе — комбобокс в
  статус-баре)

**Проверки:**
1. `pytest -q tests/test_repository.py tests/test_bridge_units.py` (без GUI;
   связка repo+signal-queue — headless).
2. Manual: запусти app → fake_serial `--scenario circle` → маркер появится и
   движется по кругу; чек-лист: title, нет консольного вывода ошибок.
3. Manual: SOS-всплеск — маркер с красной рамкой.
4. `pytest -q` все зелёные.

**Завершение:** commit `phase-1: live markers`.

---

## Фаза 2 — Вектор, курс, высота, варио + панель трекеров

**Цель:** летательная аналитика + UI-справа.

**Вход:** Фаза 1.

**Результаты:**
- `meshtrack/derivation.py`: `derive(points: list[tuple(ts, lat, lon, alt)])
  -> dict(gs_kmh|None, course_deg|None, vario_ms|None, trend)`
  — haversine, EMA (α=.5), окно ≤60c, ≥2 точки
- `Repository.last_points(track_id, seconds=60)` + кэш последних точек в RAM
- `webbridge.positionReceived` расширяется полями gs/course/vario/trend
- `app.js`: стрелка курса = divIcon с rotate(course), length∝GS (1 px/(kmh)),
  vario chip внутри маркера (↗/↘/—), popup показывает GS, alt MSL, vario
- Правая панель `TrackerListPane` (QListWidget по tracker’ам): элемент — цвет
  chip, id, GS→, alt, trend, заряд, last-update «N c»; сорт по свёжести;
  click → `js: map.setView(marker)`, double-click → трек toggle

**Проверки:**
1. Unit-derive (no GUI):
   - `static`: 10 точек одна коорд. → gs≈0 (tol 1e-3), trend «—»
   - `climb`: fake alt +1.5/с за 60с → vario≈1.5, trend «↗»
   - `descend`: −2/с → «↘»
   - `circle`: mean course совпадает с истинным (считать bearing по fake)
     с допуском 10°
2. Manual UI: стрелка длина/угол соответствует fake-course; панель обновляет
   строки во времени; SOS красит.
3. `pytest -q` зелёная.

**Завершение:** commit `phase-2: vector + vario + tracker pane`.

---

## Фаза 3 — Треки и история

**Цель:** polyline-история + фильтры.

**Вход:** Фаза 2.

**Результаты:**
- `Repository.points(track_id, ts_from, ts_to)`, decimate (имплементация:
  Douglas-Peucker или stride) ≤ 2000 точек на ответ
- `webbridge`: метод `getTrack(track_id, from, to)` (invocable из JS) —
  возвращает сериализованный polyline; `clearHistory()` (настройки)
- `app.js`: слой трека, цвет режим per настройки (`colorMode`: palette |
  altitude | vario — высота = син→красн по [0..4000]м, варио = зел/красн по
  ±5 м/с)
- Фильтры UI: `QCombo`-пример «Сегодня / Вчера / Период» + datetimeedit
  диалог
- Настройка `retention_days` (default 90) — очистка на старте

**Проверки:**
1. Unit-repo: вставка N точек через 1с, запрос period возвращает правильное
   подмножество; decimate ≤ 2000.
2. Manual: `climb`-сценарий → после завершения toggle → трек отрисован;
   фильтр «Сегодня» показывает, «Вчера» — нет.
3. Manual: перезапуск app — история и трек сохранены (SQLite).
4. `pytest -q` зелёная.

**Завершение:** commit `phase-3: history tracks`.

---

## Фаза 4 — Карты: first-run wizard + MBTiles + map://

**Цель:** оффлайн-источник тайлов.

**Вход:** Фаза 3 (карта до этого с Leaflet но без тайлов — серый фон).

**Результаты:**
- `meshtrack/mapstore.py`: `MapStore(path)` → create/insert/get/verify;
  schema: `metadata` + `tiles`; batch-insert (transaction)
- `meshtrack/downloader.py`: `download(bbox, zmin=9, zmax=15, tmpl, dest,
  on_progress)` — threading (4 worker), rate-limit ≥ 200 мс per host,
  resume (checkpoint `config.json → downloads[{hash}]`), `429/5xx →
  exponential backoff`
- `meshtrack/regions.py`: PREBUILT bboxes (см. PROJECT §8) + user-defined
  (config)
- `meshtrack/mapscheme.py`: `MapSchemeHandler` (QWebEngineUrlSchemeHandler)
  — regex `^map://([-\w]+)/(\d+)/(\d+)/(\d+)\.png$`; miss → 1×1 transparent PNG;
  thread-safe доступ к MapStore (open per thread)
- `first_run_wizard.py` (QWizard): страницы — привет/выбор регіона (list +
  custom-bbox через minimap с `L.rectangle`)/загрузка (QProgressBar, cancel
  держит resume)/готово
- Стартуем: при отсутствии любой mbtiles → wizard; иначе — обычная работа

**Проверки:**
1. `pytest -q tests/test_mapstore.py` — insert/get/verify; invalid blob →
   прозр. заглушка.
2. `pytest -q tests/test_downloader.py` — mock-http (responses lib или local
   `http.server` fixture) — вернёт mbtiles; тест resume.
3. Manual: first-run пуст → wizard; скачивание bbox «1×1км, z 9–11» →
   list-map «mordovia…»; закрыть/открыть → тайлы есть.
4. Manual offline: отключить сеть до запуска → карта рендерит сохранённые
   тайлы, Leaflet не пустует.
5. `pytest -q` зелёная.

**Завершение:** commit `phase-4: offline maps`.

---

## Фаза 5 — Traccar-опция, настройки, экспорт

**Цель:** фин-фич и polish.

**Вход:** Фаза 4.

**Результаты:**
- `meshtrack/publisher.py`: `TraccarPublisher(enable: bool)` —
  enqueue/dequeue retry (failed>5 → стоп 5мин, requeue); если `enable=False` —
  метод `enqueue()` no-op
- `meshtrack/settings.py`: `config.json` схема `{traccar_on, tom coloring,
  retention_days, port_pref, baud, maps: [{id,bbox,z}], exports_dir}`
- UI Настроек (QDialog): вкл/выкл Traccar, mode-color треков, очистка истории
  (с confirmbox), порт/baud (combo-from-serial.tools.list_ports), Exports:
  `Экспорт GPX / CSV` (по trackі за фильтр) через `QFileDialog`
- Legacy `main.py` удалён; parser импортируется из meshtrack

**Проверки:**
1. Unit-publisher: mock-requests (pytest-mock) — emit при enable=True; при
   False — 0 запросов.
2. Unit-export: GPX-файл парсится `xml.etree`, csv-заголовк ок.
3. Manual: включить Traccar → free-gps.ru получает точки (если есть net);
   выкл → no-net (process netstat / Little Snitch).
4. `pytest -q` зелёная.

**Завершение:** commit `phase-5: traccar opt + settings + export`.

---

## Фаза 6 — Сборка и дистрибуция

**Цель:** артефакты Windows + macOS.

**Вход:** Фаза 5.

**Результаты:**
- `installer/MeshTrack.spec` (onedir, hiddenimports PySide6.QtWebEngine*,
  datas: assets/web, regions.json, icon)
- `installer/setup.iss` (Inno Setup, Windows)
- `installer/make_dmg.sh` (hdiutil, macOS)
- `README.md` (RU): Gatekeeper/SmartScreen, USB-driver FAQ, «нет карты →
  мастер» объяснения

**Проверки (manual, в чистой VM):**
1. Windows: setup.exe → установка → MeshTrack стартует → fake-flight →
   карта + маркер.
2. macOS: dmg → drag-drop → first-open: right-click «Открыть» → стартует.
3. В обоих: отключение сети после wizard → оффлайн работает.
4. Размер: установщик ≤ 250 МБ.

**Завершение:** commit `phase-6: packaging`.

---

## Фаза 7 (опционально) — Импорт Ozi `.map + .png/.jpg`

**Цель:** пользователь приносит свою привязанную растровую карту, приложение
конвертирует её в MBTiles.

**Результаты:** `tools/ozi_importer.py` (CLI) и/или Настройк-кнопка; парсинг
.calibration points из `.map`-text; геометрическое преобразование в Web
Mercator; PIL для ресемплинга; запись через MapStore.

**Проверки:** 1) unit-parse `.map` (sample fixture); 2) manual: импорт
sample → на карте подложка из скана.

**Завершение:** commit `phase-7: ozi importer` (если выполняется).

---

## Общие правила статусов

- Перед фазой: прочитай PROJECT.md, убедись предыдущая ✅.
- После фазы: обнов 1 строку в таблице (√), деталь при необходимости.
- Любой manual-check должен иметь чек-лист в фазе (соответствующая секция).
- Изменения архитектуры/названий модулей → сначала фиксируем PROJECT.md.
