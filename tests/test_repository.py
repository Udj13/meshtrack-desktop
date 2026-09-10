"""Тесты repository.py (headless, без Qt)."""
import time
from pathlib import Path

import pytest

from meshtrack.repository import Repository


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return Repository(str(tmp_path / "test.db"))


def test_empty_latest(repo: Repository):
    assert repo.latest("boon1") is None
    assert repo.active_trackers() == []


def test_add_and_latest(repo: Repository):
    repo.add_position("boon7", 54.4, 45.4, alt=500, batt=87, voltage=4020, sos=0)
    latest = repo.latest("boon7")
    assert latest is not None
    assert latest["tracker_id"] == "boon7"
    assert latest["lat"] == 54.4
    assert latest["lon"] == 45.4
    assert latest["alt"] == 500
    assert latest["batt"] == 87
    assert latest["voltage"] == 4020
    assert latest["sos"] == 0


def test_active_trackers_age(repo: Repository):
    now = time.time()
    repo.add_position("boon1", 54.0, 45.0, ts=now - 10)
    repo.add_position("boon2", 54.1, 45.1, ts=now - 400)
    active = repo.active_trackers(max_age_s=300)
    assert len(active) == 1
    assert active[0]["tracker_id"] == "boon1"


def test_last_points(repo: Repository):
    now = time.time()
    for i in range(5):
        repo.add_position("boon3", 54.0 + i * 0.001, 45.0, alt=100 + i, ts=now - 10 + i)
    pts = repo.last_points("boon3", seconds=60)
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
