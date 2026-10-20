"""Hospital: the campus from OSM, the scenario, and what each rule set changes."""

import json
from pathlib import Path

import pytest

from lahore_twin.export import source_digest
from lahore_twin.hospital import build
from lahore_twin.hospital_site import site
from lahore_twin.hospital_sim import MODES, HospitalSim
from lahore_twin.plan import Plan

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def plans():
    return Plan.load("hospital_ed.json"), Plan.load("hospital_ward.json")


@pytest.fixture(scope="module")
def runs(plans):
    ed, ward = plans
    sc = build(ed, ward, seed=7)
    return sc, {m: HospitalSim(sc, ed, ward, m).run() for m in MODES}


def test_the_campus_path_runs_between_buildings_and_the_floors_sit_in_their_footprints(plans):
    s = site()
    assert 150 < s["path_m"] < 400
    ed_bld = next(b for b in s["buildings"] if b["name"].startswith("Emergency"))
    xs = [p[0] for p in ed_bld["poly"]]
    ys = [p[1] for p in ed_bld["poly"]]
    # the ED plan's building part (without its forecourt) covers the OSM footprint to within a metre
    assert abs((max(xs) - min(xs)) - 31) < 1.5 and abs((max(ys) - min(ys)) - 50) < 1.5


def test_floors_connect_through_their_lifts_and_stairs(plans):
    from lahore_twin.plan import is_portal, path_length
    ed, ward = plans
    down = ed.route(ed.spots["walkin"][0], ed.spots["b_store_shelf"][0])
    hops = [(a, b) for a, b in zip(down, down[1:]) if is_portal(a, b)]
    assert len(hops) == 1 and ed.floor_at(*hops[0][0]) == "G" and ed.floor_at(*hops[0][1]) == "B1"
    # the hop costs the stairs (9 m), not the 60 m gap between the floors on the drawing
    assert path_length(down) < 90
    up = ward.route(ward.spots["entry"][0], ward.spots["bed_hdu"][0])
    assert [ward.floor_at(*p) for p in (up[0], up[-1])] == ["G", "2"]


def test_every_spot_on_both_floors_can_reach_every_other(plans):
    for p in plans:
        pts = [v[0] for v in p.spots.values()]
        for a in pts:
            assert p.route(pts[0], a)


def test_both_rule_sets_meet_the_same_patients_and_events(runs):
    sc, sims = runs
    a, b = (sims[m] for m in MODES)
    assert [r["arrive"] for r in a.records.values()] == [r["arrive"] for r in b.records.values()]
    assert [r["colour"] for r in a.records.values()] == [r["colour"] for r in b.records.values()]
    assert len(a.alarm_log) == len(b.alarm_log)
    assert build(*[Plan.load(f) for f in ("hospital_ed.json", "hospital_ward.json")], seed=7).ed_patients == sc.ed_patients


def test_patient_timestamps_run_forwards_and_everyone_is_accounted_for(runs):
    _, sims = runs
    for s in sims.values():
        for r in s.records.values():
            steps = [r[k] for k in ("arrive", "triaged", "seen", "results", "reviewed", "left") if r[k] is not None]
            assert steps == sorted(steps), r
            assert r["outcome"] in (None, "home", "admitted", "left unseen")
            if r["outcome"] == "left unseen":
                assert r["seen"] is None
        m = s.metrics()
        assert m["ed_arrivals"] == len(s.records)


def test_a_ward_bed_never_holds_two_patients(runs):
    _, sims = runs
    allowed = {"ready": {"reserved", "occupied"}, "reserved": {"occupied"}, "occupied": {"dirty"},
               "dirty": {"ready"}}
    for s in sims.values():
        last = {}
        for t, bed, st in s.bed_ev:
            if bed in last and last[bed] != st:
                assert st in allowed[last[bed]], (bed, last[bed], st, t)
            last[bed] = st


def test_the_alarm_delay_silences_false_alarms_and_says_what_it_hides(runs):
    _, sims = runs
    today, conn = sims["today"].metrics(), sims["connected"].metrics()
    assert conn["alarms_sounded"] < today["alarms_sounded"]
    assert conn["false_alarm_trips"] < today["false_alarm_trips"]
    brief = sum(1 for r in sims["connected"].alarm_log if r["kind"] == "brief")
    assert 0 < conn["brief_true_events_not_sounded"] <= brief
    assert today["brief_true_events_not_sounded"] == 0
    # critical alarms skip the delay: they sound the second they start
    crit = [r for r in sims["connected"].alarm_log if r["kind"] == "critical"]
    assert crit and all(r["annunciated"] == r["t"] for r in crit)
    assert all(r["annunciated"] == r["t"] + 15 for r in sims["connected"].alarm_log
               if r["kind"] == "sustained" and r["annunciated"] is not None)


def test_the_locator_ends_the_search_and_the_audit_flatters(runs):
    _, sims = runs
    today, conn = sims["today"].metrics(), sims["connected"].metrics()
    assert conn["equipment_search_min"] < today["equipment_search_min"] / 10
    # same behaviour underneath, different reports
    assert abs(today["hand_hygiene_true_pct"] - conn["hand_hygiene_true_pct"]) < 6
    assert today["hand_hygiene_reported_pct"] > today["hand_hygiene_true_pct"] + 15
    assert abs(conn["hand_hygiene_reported_pct"] - conn["hand_hygiene_true_pct"]) < 5
    assert conn["fridge_minutes_over_8C"] < today["fridge_minutes_over_8C"]
    assert conn["bed_turnaround_min"] < today["bed_turnaround_min"]


def test_equipment_is_in_one_place_at_a_time(runs):
    _, sims = runs
    for s in sims.values():
        holders = {}
        for t, aid, b, x, y, holder in s.asset_ev:
            holders[aid] = holder
        for x in s.assets.values():
            assert not (x["holder"] and x["attached"]), x


def test_committed_hospital_replay_matches_the_current_code():
    text = (ROOT / "viewer" / "hospital_replay.js").read_text(encoding="utf-8")
    meta = json.loads(text[len("window.HOSPITAL = "):].rstrip().rstrip(";"))["meta"]
    assert meta["digest"] == source_digest("hospital"), "run python demo_hospital.py to refresh the replay"


def test_no_one_is_stranded_mid_task(runs):
    """A walk whose last leg has zero length (already standing at the door) once left the
    walker frozen: three porters held the ED's trolleys at the ward entrance all day."""
    _, sims = runs
    for s in sims.values():
        stuck = [(t.kind, t.taken) for t in s.tasks
                 if t.taken and t.done is None and t.arrived is not None and 86400 - t.arrived > 3600]
        assert not stuck, stuck
        admitted = [r for r in s.records.values() if r["outcome"] == "admitted"]
        assert len(admitted) >= 5
