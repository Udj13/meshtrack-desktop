"""Тесты repository.py (headless, без Qt)."""

import time
from pathlib import Path

import pytest

from meshtrack.repository import Repository


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return Repository(str(tmp_path / "test.db"))


def test_empty_latest(repo: Repository):
    assert repo.latest("1") is None
    assert repo.active_trackers() == []


def test_add_and_latest(repo: Repository):
    repo.add_position("7", 54.4, 45.4, alt=500, batt=87, voltage=4020, sos=0)
    latest = repo.latest("7")
    assert latest is not None
    assert latest["tracker_id"] == "7"
    assert latest["lat"] == 54.4
    assert latest["lon"] == 45.4
    assert latest["alt"] == 500
    assert latest["batt"] == 87
    assert latest["voltage"] == 4020
    assert latest["sos"] == 0


def test_active_trackers_age(repo: Repository):
    now = time.time()
    repo.add_position("1", 54.0, 45.0, ts=now - 10)
    repo.add_position("2", 54.1, 45.1, ts=now - 400)
    active = repo.active_trackers(max_age_s=300)
    assert len(active) == 1
    assert active[0]["tracker_id"] == "1"


def test_recv_ts_separate_from_ts(repo: Repository):
    repo.add_position("1", 54.0, 45.0, ts=1700000000.0, recv_ts=1750000000.0)
    latest = repo.latest("1")
    assert latest is not None
    assert latest["ts"] == 1700000000.0
    assert latest["recv_ts"] == 1750000000.0

    now = time.time()
    repo.add_position("2", 54.1, 45.1, ts=now)
    latest2 = repo.latest("2")
    assert latest2 is not None
    assert latest2["recv_ts"] == latest2["ts"]


def test_last_points(repo: Repository):
    now = time.time()
    for i in range(5):
        repo.add_position("3", 54.0 + i * 0.001, 45.0, alt=100 + i, ts=now - 10 + i)
    pts = repo.last_points("3", seconds=60)
    assert len(pts) == 5
    assert pts[0] == (now - 10, 54.0, 45.0, 100)
    assert pts[-1] == (now - 6, 54.0 + 0.004, 45.0, 104)


def test_wal_mode(repo: Repository):
    # journal_mode=WAL должно быть включено
    import sqlite3

    conn = sqlite3.connect(repo.db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    conn.close()


def test_points_filter_by_period(repo: Repository):
    now = time.time()
    # 1: точки вчера, сегодня и завтра
    repo.add_position("1", 54.0, 45.0, alt=100, ts=now - 86400)
    repo.add_position("1", 54.1, 45.1, alt=200, ts=now - 3600)
    repo.add_position("1", 54.2, 45.2, alt=300, ts=now + 3600)

    pts = repo.points("1", ts_from=now - 7200, ts_to=now + 100)
    assert len(pts) == 1
    assert pts[0]["alt"] == 200

    pts_all = repo.points("1")
    assert len(pts_all) == 3
    assert pts_all[0]["ts"] < pts_all[-1]["ts"]


def test_points_decimate_limit(repo: Repository):
    now = time.time()
    for i in range(2500):
        repo.add_position("2", 54.0 + i * 0.0001, 45.0, alt=i, ts=now - 2500 + i)
    pts = repo.points("2")
    assert len(pts) <= 2000
    # Первая и последняя точки должны сохраниться
    assert pts[0]["alt"] == 0
    assert pts[-1]["alt"] == 2499


def test_decimate_points_function():
    from meshtrack.repository import decimate_points

    pts = [{"i": i} for i in range(10)]
    assert decimate_points(pts, 20) == pts
    assert decimate_points(pts, 0) == pts
    assert decimate_points(pts, 1) == [{"i": 9}]
    reduced = decimate_points(pts, 5)
    assert len(reduced) == 5
    assert reduced[0] == {"i": 0}
    assert reduced[-1] == {"i": 9}


def test_purge_old(repo: Repository):
    now = time.time()
    repo.add_position("3", 54.0, 45.0, ts=now - 100 * 86400)
    repo.add_position("3", 54.1, 45.1, ts=now - 10 * 86400)
    repo.add_position("3", 54.2, 45.2, ts=now)

    deleted = repo.purge_old(30)
    assert deleted == 1
    assert len(repo.points("3")) == 2


def test_clear_all_positions(repo: Repository):
    repo.add_position("4", 54.0, 45.0)
    repo.add_position("4", 54.1, 45.1)
    assert len(repo.points("4")) == 2
    deleted = repo.clear_all_positions()
    assert deleted == 2
    assert repo.points("4") == []
    # trackers остаются
    assert "4" in repo.all_trackers()


def test_delete_tracker(repo: Repository):
    repo.add_position("A", 54.0, 45.0, alt=100, ts=1000)
    repo.add_position("A", 54.1, 45.1, alt=110, ts=1100)
    repo.add_position("B", 54.2, 45.2, alt=200, ts=1200)

    deleted = repo.delete_tracker("A")
    assert deleted == 2
    assert repo.points("A") == []
    assert "A" not in repo.all_trackers()
    # Второй трекер не тронут
    assert repo.points("B") == [
        {
            "ts": 1200,
            "lat": 54.2,
            "lon": 45.2,
            "alt": 200,
            "batt": None,
            "voltage": None,
            "sos": None,
        }
    ]


def test_delete_tracker_without_positions(repo: Repository):
    repo.add_position("C", 54.0, 45.0)
    deleted = repo.delete_tracker("ghost")
    assert deleted == 0
    assert "ghost" not in repo.all_trackers()
    assert "C" in repo.all_trackers()


def test_set_tracker_name(repo: Repository):
    repo.add_position("N", 54.0, 45.0)
    assert repo.get_tracker_name("N") is None

    repo.set_tracker_name("N", "Параплан")
    assert repo.get_tracker_name("N") == "Параплан"
    assert repo.tracker_names() == {"N": "Параплан"}

    # Изменение псевдонима
    repo.set_tracker_name("N", "Дуэт-1")
    assert repo.get_tracker_name("N") == "Дуэт-1"

    # Пустая строка/None снимает псевдоним
    repo.set_tracker_name("N", "")
    assert repo.get_tracker_name("N") is None
    assert repo.tracker_names() == {}


def test_set_tracker_name_creates_row(repo: Repository):
    # Псевдоним задаётся даже без позиций: строка в trackers появляется.
    repo.set_tracker_name("Z", "Бланик")
    assert repo.get_tracker_name("Z") == "Бланик"
    assert "Z" in repo.all_trackers()


def test_delete_tracker_removes_name(repo: Repository):
    repo.add_position("D", 54.0, 45.0)
    repo.set_tracker_name("D", "Мечта")
    repo.delete_tracker("D")
    assert "D" not in repo.all_trackers()
    assert repo.get_tracker_name("D") is None
