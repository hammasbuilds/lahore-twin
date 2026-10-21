"""Phase 6: smog, underpass flooding and streetlights on the real roads."""

import json
from pathlib import Path

import pytest

from lahore_twin import city
from lahore_twin.export import source_digest
from lahore_twin.roads import load

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def net():
    return load()


@pytest.fixture(scope="module")
def smog():
    return city.smog(seed=7, minutes=20)


def test_smog_stays_inside_what_lahore_has_measured(smog):
    """Hourly peaks near 900 µg/m³ were reported; the first version reached 1,891."""
    m = smog["metrics"]
    assert 100 < m["area_mean_peak"] < 400
    assert m["worst_cell_peak"] < 1200
    for frame in smog["truth"].values():
        assert min(frame) >= city.background(0, 20) - 1         # never below the regional haze


def test_traffic_is_the_calibrated_share_near_roads(smog):
    g, truth = smog["grid"], smog["truth"]
    peak = range(5, 20)
    near = [k for k in range(g.nx * g.ny) if any(truth[m][k] > city.background(m, 20) + 0.5 for m in peak)]
    traffic = sum(truth[m][k] - city.background(m, 20) for m in peak for k in near)
    total = sum(truth[m][k] for m in peak for k in near)
    assert 0.25 < traffic / total < 0.45


def test_sensors_beat_one_monitor_and_find_the_hotspot(smog):
    m = smog["metrics"]
    assert m["map_error_sensors"] < 0.8 * m["map_error_today"]
    assert m["hotspot_found_m"] <= 700
    assert m["hotspot_after"] < m["hotspot_before"]                # adaptive signals cut idling there
    assert m["true_hotspot_after"] < m["true_hotspot_before"]      # and the real hotspot gains too
    assert len(smog["sensors"]) == 26 and sum(1 for s in smog["sensors"] if s["kind"] == "junction") == 10


def test_underpasses_fill_without_power_and_stay_shallow_with_a_generator(net):
    ups = city.underpasses(net)
    assert len(ups) >= 5 and len({u["name"] for u in ups}) == len(ups)          # no two share a name
    for u in ups:
        today = city.depth_series(u, city.GEN_TODAY, 7200)          # the storm runs 80 min; two hours to drain
        conn = city.depth_series(u, city.GEN_CONNECTED, 7200)
        assert 0.2 < max(today) < 1.5                                              # half a metre, not 4.6
        assert max(conn) < max(today)
        assert today[-1] == 0.0                                                    # pumped dry after the storm


def test_closed_underpasses_strand_nobody(net):
    r = city.flood(seed=7, minutes=60)      # the storm peaks after 20 min and the power cut runs to 19:05
    a, b = r["modes"]["today"], r["modes"]["connected"]
    assert a["stranded"] > 0 and b["stranded"] == 0
    assert b["rerouted"] > 0 and any(b["closed_min"].values())
    assert b["gridlocked"] <= a["gridlocked"]


def test_adaptive_streetlights_save_energy_and_keep_main_roads_lit():
    r = city.streetlights(seed=7, per_hour=600, minutes=150)
    a, b = r["modes"]["today"], r["modes"]["connected"]
    assert b["kwh"] < 0.8 * a["kwh"]
    assert b["busy_road_minutes_dark"] < a["busy_road_minutes_dark"]
    assert b["failures_known_by_morning"] == len(r["fails"]) and a["failures_known_by_morning"] == 0
    assert a["kwh"] <= r["night_full_kwh"]


def test_committed_city_replay_matches_the_current_code():
    text = (ROOT / "viewer" / "city_replay.js").read_text(encoding="utf-8")
    meta = json.loads(text[len("window.CITY = "):].rstrip().rstrip(";"))["meta"]
    assert meta["digest"] == source_digest("city"), "run python demo_city.py to refresh the replay"
