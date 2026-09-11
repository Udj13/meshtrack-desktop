"""Работа с MBTiles — SQLite-контейнером растровых тайлов.

Спецификация Mapbox MBTiles 1.3:
- metadata(name TEXT PRIMARY KEY, value TEXT)
- tiles(zoom_level, tile_column, tile_row, tile_data BLOB,
        PRIMARY KEY(zoom_level, tile_column, tile_row))

Tile_row в MBTiles использует схему TMS (y отсчитывается снизу), тогда как
веб-карты используют XYZ (y сверху). Методы insert/get делают преобразование
автоматически, получая/отдавая координаты в формате XYZ.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


class MapStore:
    """Хранилище тайлов в формате MBTiles.

    Аргументы:
        path: путь к файлу .mbtiles. Родительская директория создаётся.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS metadata (
        name TEXT PRIMARY KEY,
        value TEXT
    );
    CREATE TABLE IF NOT EXISTS tiles (
        zoom_level INTEGER,
        tile_column INTEGER,
        tile_row INTEGER,
        tile_data BLOB,
        PRIMARY KEY (zoom_level, tile_column, tile_row)
    );
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._invalid = False
        try:
            self._ensure_schema()
        except sqlite3.Error:
            self._invalid = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(self.SCHEMA)

    @staticmethod
    def _xyz_to_tms_row(z: int, y: int) -> int:
        """Преобразует XYZ y в TMS row для данного zoom."""
        return (2**z - 1) - y

    @staticmethod
    def _tms_to_xyz_row(z: int, row: int) -> int:
        """Преобразует TMS row в XYZ y."""
        return (2**z - 1) - row

    def set_metadata(self, name: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO metadata(name, value) VALUES (?, ?)",
                (name, value),
            )

    def get_metadata(self, name: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM metadata WHERE name = ?", (name,)
            ).fetchone()
            return row[0] if row else None

    def insert(self, z: int, x: int, y: int, data: bytes) -> None:
        """Вставляет один тайл (x,y в XYZ)."""
        row = self._xyz_to_tms_row(z, y)
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tiles
                   (zoom_level, tile_column, tile_row, tile_data)
                   VALUES (?, ?, ?, ?)""",
                (z, x, row, data),
            )

    def insert_many(self, items: Iterable[tuple[int, int, int, bytes]]) -> int:
        """Batch-вставка тайлов. Каждый элемент: (z, x, y, data) в XYZ."""
        rows = []
        count = 0
        for z, x, y, data in items:
            rows.append((z, x, self._xyz_to_tms_row(z, y), data))
            count += 1
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO tiles
                   (zoom_level, tile_column, tile_row, tile_data)
                   VALUES (?, ?, ?, ?)""",
                rows,
            )
        return count

    def set_minmax_zoom(self, zmin: int, zmax: int) -> None:
        """Сохраняет min/max zoom в metadata (стандарт MBTiles)."""
        self.set_metadata("minzoom", str(int(zmin)))
        self.set_metadata("maxzoom", str(int(zmax)))

    def get_minmax_zoom(self, default_zmin: int = 9, default_zmax: int = 15) -> tuple[int, int]:
        """Возвращает (minzoom, maxzoom) из metadata или вычисляет из tiles."""
        zmin_str = self.get_metadata("minzoom")
        zmax_str = self.get_metadata("maxzoom")
        try:
            if zmin_str is not None and zmax_str is not None:
                return int(zmin_str), int(zmax_str)
        except ValueError:
            pass
        # Fallback: вычислить из таблицы tiles.
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MIN(zoom_level), MAX(zoom_level) FROM tiles"
            ).fetchone()
            if row and row[0] is not None:
                return int(row[0]), int(row[1])
        return default_zmin, default_zmax

    def get(self, z: int, x: int, y: int) -> bytes | None:
        """Возвращает BLOB тайла (x,y в XYZ) или None если отсутствует."""
        row = self._xyz_to_tms_row(z, y)
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT tile_data FROM tiles
                   WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?""",
                (z, x, row),
            )
            r = cur.fetchone()
            return r[0] if r else None

    def has(self, z: int, x: int, y: int) -> bool:
        """True, если тайл уже есть в хранилище."""
        return self.get(z, x, y) is not None

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()
            return row[0] if row else 0

    def verify(self) -> dict:
        """Проверяет целостность хранилища.

        Возвращает dict:
            ok: bool
            tile_count: int
            metadata: dict с парами name->value
            errors: список строк с ошибками
        """
        errors: list[str] = []
        if self._invalid:
            errors.append("file is not a valid database")
            return {"ok": False, "tile_count": 0, "metadata": {}, "errors": errors}
        try:
            with self._connect() as conn:
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "metadata" not in tables or "tiles" not in tables:
                    errors.append("missing required tables")
                    return {"ok": False, "tile_count": 0, "metadata": {}, "errors": errors}

                meta = {
                    name: value
                    for name, value in conn.execute(
                        "SELECT name, value FROM metadata"
                    ).fetchall()
                }
                count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
                nulls = conn.execute(
                    "SELECT COUNT(*) FROM tiles WHERE tile_data IS NULL"
                ).fetchone()[0]
                if nulls:
                    errors.append(f"{nulls} tiles with NULL tile_data")
                return {
                    "ok": len(errors) == 0,
                    "tile_count": count,
                    "metadata": meta,
                    "errors": errors,
                }
        except sqlite3.Error as exc:
            errors.append(f"sqlite error: {exc}")
            return {"ok": False, "tile_count": 0, "metadata": {}, "errors": errors}

    def list_tiles(self, z: int | None = None) -> list[tuple[int, int, int]]:
        """Возвращает список тайлов в формате (z, x, y_xyz)."""
        sql = "SELECT zoom_level, tile_column, tile_row FROM tiles"
        params: tuple = ()
        if z is not None:
            sql += " WHERE zoom_level = ?"
            params = (z,)
        sql += " ORDER BY zoom_level, tile_column, tile_row"
        with self._connect() as conn:
            return [
                (z_, x, self._tms_to_xyz_row(z_, row))
                for z_, x, row in conn.execute(sql, params).fetchall()
            ]
