"""Тесты meshtrack/exporter.py (headless, без Qt)."""
import csv
import xml.etree.ElementTree as ET
from pathlib import Path

from meshtrack.exporter import CSV_HEADER, collect_tracks, export_csv, export_gpx
from meshtrack.repository import Repository

GPX_NS = {"g": "http://www.topografix.com/GPX/1/1"}


def _tracks():
    return {
        "1": [
            {"ts": 1700000000.0, "lat": 54.1, "lon": 45.2, "alt": 120,
             "batt": 90, "voltage": 4000, "sos": 0},
            {"ts": 1700000010.0, "lat": 54.2, "lon": 45.3, "alt": 130,
             "batt": 89, "voltage": 3990, "sos": 0},
        ],
        "2": [
            {"ts": 1700000005.0, "lat": 55.0, "lon": 46.0, "alt": None,
             "batt": None, "voltage": None, "sos": 1},
        ],
    }


def test_collect_tracks_period(tmp_path: Path):
    repo = Repository(str(tmp_path / "db.sqlite"))
    repo.add_position("1", 54.0, 45.0, alt=100, ts=1700000000)
    repo.add_position("1", 54.1, 45.1, alt=110, ts=1700000100)
    repo.add_position("2", 55.0, 46.0, ts=1700000000)

    tracks = collect_tracks(repo, ts_from=1700000050, ts_to=1700000200)
    assert list(tracks) == ["1"]
    assert len(tracks["1"]) == 1

    all_tracks = collect_tracks(repo)
    assert sorted(all_tracks) == ["1", "2"]


def test_export_gpx_parses(tmp_path: Path):
    path = tmp_path / "tracks.gpx"
    count = export_gpx(str(path), _tracks())
    assert count == 3

    root = ET.parse(path).getroot()
    assert root.tag == "{http://www.topografix.com/GPX/1/1}gpx"

    trks = root.findall("g:trk", GPX_NS)
    assert len(trks) == 2
    names = {t.findtext("g:name", namespaces=GPX_NS) for t in trks}
    assert names == {"1", "2"}

    trkpts = root.findall(".//g:trkpt", GPX_NS)
    assert len(trkpts) == 3
    assert trkpts[0].get("lat") == "54.1"
    assert trkpts[0].get("lon") == "45.2"
    assert trkpts[0].findtext("g:ele", namespaces=GPX_NS) == "120"
    assert trkpts[0].findtext("g:time", namespaces=GPX_NS) == "2023-11-14T22:13:20Z"


def test_export_gpx_skips_points_without_coords(tmp_path: Path):
    path = tmp_path / "tracks.gpx"
    tracks = {"1": [{"ts": 1.0, "lat": None, "lon": None, "alt": 10}]}
    assert export_gpx(str(path), tracks) == 0


def test_export_csv_header_and_rows(tmp_path: Path):
    path = tmp_path / "tracks.csv"
    rows = export_csv(str(path), _tracks())
    assert rows == 3

    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        assert next(reader) == CSV_HEADER
        data = list(reader)

    assert len(data) == 3
    assert data[0][0] == "1"
    assert data[0][1] == "1700000000.0"
    assert data[0][2] == "2023-11-14T22:13:20Z"
    assert data[1][0] == "1"
    assert data[2][0] == "2"
    assert data[2][8] == "1"
