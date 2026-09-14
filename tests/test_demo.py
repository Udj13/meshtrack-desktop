"""Тесты demo.py: моковые позиции, парсинг и заполнение истории."""
from meshtrack.demo import (
    TRACKER_IDS,
    DemoWorker,
    demo_base_point,
    format_block,
    local_midnight,
    position_at,
    seed_demo_history,
)
from meshtrack.parser import is_valid_position, parse_data
from meshtrack.repository import Repository


def test_position_at_all_trackers_valid():
    t_ref = local_midnight()
    t = t_ref + 3600
    for tracker_id in TRACKER_IDS:
        pos = position_at(tracker_id, t, t_ref)
        assert pos["id"] == tracker_id
        assert -90.0 <= pos["lat"] <= 90.0
        assert -180.0 <= pos["lon"] <= 180.0
        assert 0 <= pos["altitude"] <= 10000
        assert pos["device_ts"] == int(t)
        assert 0 <= pos["batt"] <= 100
        assert 3000 <= pos["voltage"] <= 4300


def test_position_at_moves():
    t_ref = local_midnight()
    p1 = position_at("boon101", t_ref + 100, t_ref)
    p2 = position_at("boon101", t_ref + 160, t_ref)
    assert (p1["lat"], p1["lon"]) != (p2["lat"], p2["lon"])


def test_format_block_roundtrip_parser():
    t_ref = local_midnight()
    pos = position_at("boon101", t_ref + 120, t_ref)
    parsed = parse_data(format_block(pos))
    assert is_valid_position(parsed)
    assert parsed["id"] == "boon101"
    assert parsed["device_ts"] == pos["device_ts"]
    assert float(parsed["lat"]) == pos["lat"]
    assert float(parsed["lon"]) == pos["lon"]
    assert int(parsed["altitude"]) == pos["altitude"]


def test_demo_base_point_prebuilt():
    class FakeSettings:
        active_map_id = "lyambir_airfield"

        def default_map_id(self):
            return self.active_map_id

    lat, lon = demo_base_point(FakeSettings())
    assert 54.0 < lat < 54.5
    assert 44.9 < lon < 45.5


def test_demo_base_point_default():
    class NoMap:
        active_map_id = None

        def default_map_id(self):
            return None

    lat, lon = demo_base_point(NoMap())
    assert (lat, lon) == (54.28777, 45.16604)


def test_seed_demo_history_idempotent(tmp_path):
    repo = Repository(str(tmp_path / "demo.db"))
    now = local_midnight() + 14 * 3600  # фиксированные 14:00 локального дня
    added = seed_demo_history(repo, now=now)
    assert added > 0

    day0 = local_midnight(now)
    today = repo.points("boon101", ts_from=day0, ts_to=day0 + 86400)
    yesterday = repo.points("boon101", ts_from=day0 - 86400, ts_to=day0)
    assert len(today) > 0
    assert len(yesterday) > 0

    # Повторный вызов пропускает заполнение: свежая история уже есть.
    assert seed_demo_history(repo, now=now) == 0
    assert len(repo.points("boon101", ts_from=day0, ts_to=day0 + 86400)) == len(today)


def test_demo_worker_emits_positions():
    from PySide6.QtCore import QCoreApplication, QTimer

    app = QCoreApplication.instance() or QCoreApplication([])
    positions = []
    worker = DemoWorker(interval=0.2)

    def on_position(pos):
        positions.append(pos)
        if len(positions) >= len(TRACKER_IDS):
            worker.stop()
            app.quit()

    worker.position.connect(on_position)

    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(app.quit)
    guard.start(10000)

    worker.start()
    app.exec()
    guard.stop()
    if worker.isRunning():
        worker.stop()

    assert {p["id"] for p in positions} == set(TRACKER_IDS)
