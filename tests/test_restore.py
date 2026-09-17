"""Тесты build_restored_positions: восстановление трекеров из истории (headless)."""

import sqlite3
import time
from pathlib import Path

from meshtrack.app import build_restored_positions
from meshtrack.repository import Repository


def _make_repo(path: Path, now: float) -> Repository:
    repo = Repository(str(path))

    # Свежий трекер: две точки в пределах 5 минут.
    t = now - 120
    repo.add_position(
        "trkA", 54.1, 45.1, alt=300, batt=80, voltage=4000, sos=0, ts=t, recv_ts=t
    )
    repo.add_position(
        "trkA",
        54.11,
        45.11,
        alt=320,
        batt=80,
        voltage=4000,
        sos=0,
        ts=t + 60,
        recv_ts=t + 60,
    )

    # Устаревший трекер: давность больше STALE_AGE_S (20 мин).
    tb = now - 7200
    repo.add_position(
        "trkB", 54.2, 45.2, alt=500, batt=90, voltage=4100, sos=0, ts=tb, recv_ts=tb
    )

    # «Пустой» трекер: зарегистрирован, но позиций нет — должен быть пропущен.
    with sqlite3.connect(str(path)) as conn:
        conn.execute("INSERT OR IGNORE INTO trackers(id) VALUES (?)", ("trkEmpty",))

    return repo


def test_restored_skips_trackers_without_positions(tmp_path: Path):
    now = time.time()
    repo = _make_repo(tmp_path / "restore.db", now)
    restored = build_restored_positions(repo, now=now)

    ids = {p["id"] for p in restored}
    assert ids == {"trkA", "trkB"}


def test_restored_includes_alias(tmp_path: Path):
    now = time.time()
    repo = _make_repo(tmp_path / "restore.db", now)
    repo.set_tracker_name("trkA", "Параплан")
    restored = build_restored_positions(repo, now=now)
    by_id = {p["id"]: p for p in restored}
    assert by_id["trkA"]["name"] == "Параплан"
    assert by_id["trkB"]["name"] is None


def test_restored_fields_and_stale(tmp_path: Path):
    now = time.time()
    repo = _make_repo(tmp_path / "restore.db", now)
    restored = build_restored_positions(repo, now=now)
    by_id = {p["id"]: p for p in restored}

    fresh = by_id["trkA"]
    assert fresh["lat"] == 54.11
    assert fresh["lon"] == 45.11
    assert fresh["altitude"] == 320
    assert fresh["batt"] == 80
    assert fresh["voltage"] == 4000
    assert fresh["sos"] == 0
    assert fresh["stale"] is False
    # Две свежие точки → производные метрики есть.
    assert fresh["gs_kmh"] is not None
    assert "trend" in fresh

    old = by_id["trkB"]
    assert old["lat"] == 54.2
    assert old["stale"] is True
    # Одна точка вне окна истории → метрик нет.
    assert old["gs_kmh"] is None


def test_restored_empty_history(tmp_path: Path):
    repo = Repository(str(tmp_path / "empty.db"))
    assert build_restored_positions(repo) == []


def test_restored_sorted_by_ts_desc(tmp_path: Path):
    now = time.time()
    repo = _make_repo(tmp_path / "restore.db", now)
    restored = build_restored_positions(repo, now=now)
    tss = [p["ts"] for p in restored]
    assert tss == sorted(tss, reverse=True)
