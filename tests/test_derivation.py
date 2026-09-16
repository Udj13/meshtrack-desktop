"""Unit-тесты meshtrack/derivation.py (headless, без Qt)."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meshtrack.derivation import derive, haversine_m, bearing_deg
from meshtrack.parser import parse_packet

# Базовая точка как в tools/fake_serial.py
BASE_LAT = 54.4000
BASE_LON = 45.4000
CEN_ALT = 500.0


def _points_from_blocks(blocks: list[str], step_s: float = 2.0) -> list[tuple]:
    """Превращает JSON-строки fake_serial в точки derivation."""
    pts: list[tuple[float, float, float, float | None]] = []
    for i, block in enumerate(blocks):
        p = parse_packet(block)
        assert p is not None
        lat = float(p["lat"])
        lon = float(p["lon"])
        alt = float(p["altitude"]) if "altitude" in p else None
        pts.append((i * step_s, lat, lon, alt))
    return pts


def test_empty_and_single():
    assert derive([])["gs_kmh"] is None
    assert derive([(0.0, 54.4, 45.4, 100.0)])["vario_ms"] is None


def test_static_gs_near_zero():
    from tools.fake_serial import scenario_static

    pts = _points_from_blocks(list(scenario_static(10)))
    result = derive(pts)
    assert result["gs_kmh"] is not None
    assert result["gs_kmh"] < 1e-3
    assert result["trend"] == "—"
    assert result["vario_ms"] == 0.0


def test_climb_vario_and_trend():
    from tools.fake_serial import scenario_climb

    # 31 точка с шагом 2 с = 60 с окна, набор +1.5 м/с
    pts = _points_from_blocks(list(scenario_climb(31)))
    result = derive(pts)
    assert result["vario_ms"] is not None
    assert 1.3 <= result["vario_ms"] <= 1.7
    assert result["trend"] == "▲"


def test_descend_vario_and_trend():
    from tools.fake_serial import scenario_descend

    pts = _points_from_blocks(list(scenario_descend(31)))
    result = derive(pts)
    assert result["vario_ms"] is not None
    assert -2.3 <= result["vario_ms"] <= -1.7
    assert result["trend"] == "▼"


def test_circle_course_matches_tangent():
    from tools.fake_serial import scenario_circle

    count = 60
    pts = _points_from_blocks(list(scenario_circle(count)))
    result = derive(pts)
    assert result["gs_kmh"] is not None
    assert 35 <= result["gs_kmh"] <= 45
    assert result["course_deg"] is not None

    # Сравниваем с курсом последнего сегмента (EMA должен быть близок к нему)
    expected = bearing_deg(pts[-2][1], pts[-2][2], pts[-1][1], pts[-1][2])
    diff = abs((result["course_deg"] - expected + 180) % 360 - 180)
    assert diff <= 10, f"course={result['course_deg']}, expected~{expected}"


def test_haversine_known_distance():
    # ~111 км между широтами 0° и 1°
    d = haversine_m(0.0, 0.0, 1.0, 0.0)
    assert 110_000 <= d <= 111_500


def test_bearing_cardinal():
    assert abs(bearing_deg(0.0, 0.0, 1.0, 0.0) - 0.0) < 1e-6    # север
    assert abs(bearing_deg(0.0, 0.0, 0.0, 1.0) - 90.0) < 1e-6   # восток
    assert abs(bearing_deg(0.0, 0.0, -1.0, 0.0) - 180.0) < 1e-6 # юг
    assert abs(bearing_deg(0.0, 0.0, 0.0, -1.0) - 270.0) < 1e-6 # запад
