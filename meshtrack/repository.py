"""SQLite-хранилище позиций и трекеров.

Использует WAL и минимальную схему, описанную в PROJECT.md §9.
"""

import sqlite3
import time
from pathlib import Path


MAX_TRACK_POINTS = 2000


def decimate_points(points: list[dict], limit: int = MAX_TRACK_POINTS) -> list[dict]:
    """Редуцирует список точек до limit, равномерно сохраняя первую и последнюю.

    Используется stride-подобный подбор индексов; дубликаты исключаются.
    """
    n = len(points)
    if n <= limit or limit <= 0:
        return points
    if limit == 1:
        return [points[-1]]
    indices = {int(round(i * (n - 1) / (limit - 1))) for i in range(limit)}
    return [points[i] for i in sorted(indices)]


class Repository:
    """Хранит позиции и мета-информацию трекеров.

    Аргументы:
        db_path: путь к файлу SQLite. Родительская директория создаётся.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS trackers(
        id TEXT PRIMARY KEY,
        name TEXT,
        color TEXT
    );
    CREATE TABLE IF NOT EXISTS positions(
        ts REAL,
        tracker_id TEXT,
        lat REAL,
        lon REAL,
        alt REAL,
        batt REAL,
        voltage REAL,
        sos INTEGER,
        recv_ts REAL,
        PRIMARY KEY(ts, tracker_id)
    );
    CREATE INDEX IF NOT EXISTS idx_pos_trk_ts ON positions(tracker_id, ts);
    """

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        with self._connect() as conn:
            conn.executescript(self.SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection):
        """Добавляет колонку recv_ts в существующую БД и заполняет её."""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(positions)")}
        if "recv_ts" not in cols:
            conn.execute("ALTER TABLE positions ADD COLUMN recv_ts REAL")
            conn.execute("UPDATE positions SET recv_ts = ts WHERE recv_ts IS NULL")

    def add_position(
        self,
        tracker_id: str,
        lat: float,
        lon: float,
        alt: float | None = None,
        batt: float | None = None,
        voltage: float | None = None,
        sos: int | None = None,
        ts: float | None = None,
        recv_ts: float | None = None,
    ) -> None:
        """Добавляет позицию.

        ts — время с устройства (при недоступности — время приёма).
        recv_ts — время приёма пакета на ПК; по умолчанию = ts.
        """
        if ts is None:
            ts = time.time()
        if recv_ts is None:
            recv_ts = ts
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO positions
                   (ts, tracker_id, lat, lon, alt, batt, voltage, sos, recv_ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, tracker_id, lat, lon, alt, batt, voltage, sos, recv_ts),
            )
            conn.execute(
                "INSERT OR IGNORE INTO trackers(id) VALUES (?)",
                (tracker_id,),
            )

    def latest(self, tracker_id: str) -> dict | None:
        """Возвращает последнюю позицию трекера или None."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM positions
                   WHERE tracker_id = ?
                   ORDER BY ts DESC LIMIT 1""",
                (tracker_id,),
            ).fetchone()
            return dict(row) if row else None

    def active_trackers(self, max_age_s: float = 300) -> list[dict]:
        """Список трекеров с пакетом, принятым не старше max_age_s (recv_ts)."""
        cutoff = time.time() - max_age_s
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT p.* FROM positions p
                   INNER JOIN (
                       SELECT tracker_id, MAX(recv_ts) AS recv_ts
                       FROM positions
                       GROUP BY tracker_id
                   ) m ON p.tracker_id = m.tracker_id AND p.recv_ts = m.recv_ts
                   WHERE p.recv_ts >= ?
                   ORDER BY p.recv_ts DESC""",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]

    def last_points(self, tracker_id: str, seconds: float = 600) -> list[tuple]:
        """Возвращает последние точки трекера за seconds секунд.

        Формат: [(ts, lat, lon, alt), ...], отсортировано по ts.
        """
        cutoff = time.time() - seconds
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT ts, lat, lon, alt FROM positions
                   WHERE tracker_id = ? AND ts >= ?
                   ORDER BY ts ASC""",
                (tracker_id, cutoff),
            ).fetchall()
            return [(r["ts"], r["lat"], r["lon"], r["alt"]) for r in rows]

    def all_trackers(self) -> list[str]:
        """Все известные tracker_id."""
        with self._connect() as conn:
            rows = conn.execute("SELECT id FROM trackers ORDER BY id").fetchall()
            return [r["id"] for r in rows]

    def tracker_names(self) -> dict[str, str]:
        """Все псевдонимы трекеров: {tracker_id: name} (без пустых)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name FROM trackers WHERE name IS NOT NULL AND name != ''"
            ).fetchall()
            return {r["id"]: r["name"] for r in rows}

    def get_tracker_name(self, tracker_id: str) -> str | None:
        """Псевдоним трекера или None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT name FROM trackers WHERE id = ?", (tracker_id,)
            ).fetchone()
            return row["name"] if row else None

    def set_tracker_name(self, tracker_id: str, name: str | None) -> None:
        """Задаёт/обновляет псевдоним трекера; None/пусто — снимает."""
        name = (name or "").strip()
        value: str | None = name or None
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO trackers(id) VALUES (?)", (tracker_id,))
            conn.execute(
                "UPDATE trackers SET name = ? WHERE id = ?", (value, tracker_id)
            )

    def points(
        self,
        tracker_id: str,
        ts_from: float | None = None,
        ts_to: float | None = None,
        limit: int = MAX_TRACK_POINTS,
    ) -> list[dict]:
        """Возвращает точки трека за период, редуцированные до limit.

        Формат элемента: {"ts", "lat", "lon", "alt", "batt", "voltage", "sos"}.
        """
        where = ["tracker_id = ?"]
        params: list = [tracker_id]
        if ts_from is not None:
            where.append("ts >= ?")
            params.append(ts_from)
        if ts_to is not None:
            where.append("ts <= ?")
            params.append(ts_to)

        sql = f"""SELECT ts, lat, lon, alt, batt, voltage, sos FROM positions
                  WHERE {" AND ".join(where)}
                  ORDER BY ts ASC"""
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        pts = [
            {
                "ts": r["ts"],
                "lat": r["lat"],
                "lon": r["lon"],
                "alt": r["alt"],
                "batt": r["batt"],
                "voltage": r["voltage"],
                "sos": r["sos"],
            }
            for r in rows
        ]
        return decimate_points(pts, limit)

    def purge_old(self, days: int) -> int:
        """Удаляет позиции старше days дней. Возвращает количество удалённых строк."""
        if days <= 0:
            return 0
        cutoff = time.time() - days * 86400
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM positions WHERE ts < ?", (cutoff,))
            return cur.rowcount

    def clear_all_positions(self) -> int:
        """Удаляет все позиции (очистка истории). Возвращает количество удалённых строк."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM positions")
            return cur.rowcount

    def delete_tracker(self, tracker_id: str) -> int:
        """Удаляет все позиции и запись трекера.

        Возвращает количество удалённых позиций; запись в `trackers` удаляется
        всегда (даже если позиций не было).
        """
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM positions WHERE tracker_id = ?", (tracker_id,)
            )
            deleted = cur.rowcount
            conn.execute("DELETE FROM trackers WHERE id = ?", (tracker_id,))
        return deleted
