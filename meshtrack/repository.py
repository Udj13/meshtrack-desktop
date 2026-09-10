"""SQLite-хранилище позиций и трекеров.

Использует WAL и минимальную схему, описанную в PROJECT.md §9.
"""
import sqlite3
import time
from pathlib import Path


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
    ) -> None:
        """Добавляет позицию. Время по умолчанию — now()."""
        if ts is None:
            ts = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO positions
                   (ts, tracker_id, lat, lon, alt, batt, voltage, sos)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, tracker_id, lat, lon, alt, batt, voltage, sos),
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
        """Список трекеров с позицией не старше max_age_s."""
        cutoff = time.time() - max_age_s
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT p.* FROM positions p
                   INNER JOIN (
                       SELECT tracker_id, MAX(ts) AS ts
                       FROM positions
                       GROUP BY tracker_id
                   ) m ON p.tracker_id = m.tracker_id AND p.ts = m.ts
                   WHERE p.ts >= ?
                   ORDER BY p.ts DESC""",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]

    def last_points(self, tracker_id: str, seconds: float = 60) -> list[tuple]:
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
            rows = conn.execute(
                "SELECT id FROM trackers ORDER BY id"
            ).fetchall()
            return [r["id"] for r in rows]
