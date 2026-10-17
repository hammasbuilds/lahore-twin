import itertools
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from lahore_twin.bus import Bus, topic_matches
from lahore_twin.devices import C_OUT, RoomEnv
from lahore_twin.office import build, hm
from lahore_twin.plan import Plan
from lahore_twin.rules import Attendance, Automation
from lahore_twin.sim import Sim

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def plan():
    return Plan.load("office.json")


@pytest.fixture(scope="module")
def day(plan):
    sc = build(plan, seed=7)
    return sc, {m: Sim(sc, m).run() for m in ("schedule", "pir", "pir+co2")}


# ---- plan and routing ---------------------------------------------------

def _crossing_ok(plan, a, b):
    ra, rb = plan.room_at(*a), plan.room_at(*b)
    if ra == rb:
        return True
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    for d in plan.doors:
        if {d.a, d.b} == {ra, rb}:
            along = mid[0] if d.axis == "x" else mid[1]
            if d.lo <= along <= d.hi:
                return True
    return False


def test_every_spot_reaches_every_other_through_doors_only(plan):
    spots = [v[0] for v in plan.spots.values()] + plan.parking_spots[:2]
    for a, b in itertools.combinations(spots, 2):
        pts = plan.route(a, b)
        assert pts[0] == a and pts[-1] == b
        for p, q in zip(pts, pts[1:]):
            assert _crossing_ok(plan, p, q), (a, b, p, q)


def test_route_never_cuts_through_a_wall(plan):
    # booth 1 to booth 2 share a wall; the route must go out into the corridor
    pts = plan.route(plan.spots["booth1_seat"][0], plan.spots["booth2_seat"][0])
    assert any(plan.room_at(*p) == "vcorr" for p in pts)


def test_a_door_outside_its_shared_edge_is_rejected(tmp_path, plan):
    raw = json.loads((ROOT / "plans" / "office.json").read_text(encoding="utf-8"))
    raw["doors"][0]["span"] = [40, 41]
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="outside edge"):
        Plan.load(f)


# ---- bus -----------------------------------------------------------------

def test_mqtt_wildcards():
    assert topic_matches("office/+/motion", "office/work/motion")
    assert not topic_matches("office/+/motion", "office/work/light")
    assert topic_matches("office/#", "office/a/b/c")
    assert not topic_matches("office/+", "office/a/b")


def test_quiet_message_that_causes_something_is_kept_for_why():
    bus = Bus()
    m = bus.publish("office/work/motion", 1)
    assert m not in bus.log
    act = bus.publish("office/work/light", True, m.id, "Lights on")
    chain = bus.why(act.id)
    assert [c.topic for c in chain] == ["office/work/light", "office/work/motion"]


# ---- physics ---------------------------------------------------------------

def test_co2_settles_where_mass_balance_says():
    env = RoomEnv("b", "booth", 10.0, True)
    for _ in range(36000):
        env.step(10, hm("12:00"), 1, False, False)
    expected = C_OUT + 5.2 / 30.0 * 3600     # n*G/V divided by ACH/3600
    assert math.isclose(env.co2, expected, rel_tol=0.01)


def test_ac_holds_the_setpoint_band():
    env = RoomEnv("w", "workspace", 100.0, True, temp=30.0)
    temps = []
    for i in range(2000):
        env.step(10, hm("15:00"), 10, True, True)
        if i > 600:
            temps.append(env.temp)
    assert 23.0 < min(temps) and max(temps) < 25.0


# ---- rules ---------------------------------------------------------------

def _auto(plan, mode, bookings=()):
    bus = Bus()
    return bus, Automation(bus, plan, mode, list(bookings))


def test_schedule_switches_everything_at_0830(plan):
    bus, auto = _auto(plan, "schedule")
    bus.now = hm("08:30")
    auto.tick(hm("08:30"))
    assert all(st.light for st in auto.rooms.values())
    assert auto.rooms["work"].ac and not auto.rooms["corr1"].ac


def test_motion_turns_room_on_and_silence_turns_it_off(plan):
    bus, auto = _auto(plan, "pir")
    bus.now = hm("10:00")
    bus.publish("office/meet_s/motion", 1)
    assert auto.rooms["meet_s"].light and auto.rooms["meet_s"].ac
    auto.tick(hm("10:09"))
    assert auto.rooms["meet_s"].light
    auto.tick(hm("10:10"))
    assert not auto.rooms["meet_s"].light and not auto.rooms["meet_s"].ac


def test_steady_co2_keeps_a_still_room_on_only_in_co2_mode(plan):
    for mode, expect in (("pir", False), ("pir+co2", True)):
        bus, auto = _auto(plan, mode)
        bus.now = hm("10:00")
        bus.publish("office/mgr1/motion", 1)
        for k in range(12):                      # an hour of steady 700 ppm
            bus.now = hm("09:00") + 300 * k
            bus.publish("office/mgr1/co2", 700.0)
        auto.tick(hm("10:11"))
        assert auto.rooms["mgr1"].light is expect, mode


def test_decaying_co2_does_not_keep_an_empty_room_on(plan):
    bus, auto = _auto(plan, "pir+co2")
    bus.now = hm("10:00")
    bus.publish("office/mgr1/motion", 1)
    for k in range(12):
        bus.now = hm("09:00") + 60 * k
        bus.publish("office/mgr1/co2", 900.0 - 25 * k)
    auto.tick(hm("10:11"))
    assert not auto.rooms["mgr1"].light


def test_rules_fire_on_crossing_a_time_not_on_equality(plan):
    # bookings start at odd seconds and rules tick every 5 s
    from lahore_twin.office import Booking
    b = Booking("x", "meet_s", "Test", hm("11:00") + 3, hm("11:30") + 3)
    bus, auto = _auto(plan, "pir", [b])
    for t in range(hm("10:40"), hm("11:20"), 5):
        bus.now = t
        auto.tick(t)
    topics = [m.topic for m in bus.log]
    assert "office/meet_s/booking" in topics           # pre-cool fired
    assert "office/alert/no_show" in topics            # and the no-show was caught


# ---- attendance ------------------------------------------------------------

class _P:
    def __init__(self, pid, role="staff"):
        self.id, self.name, self.role = pid, pid, role


def test_unexplained_beam_is_a_tailgate_and_nearest_badge_wins():
    bus = Bus()
    att = Attendance(bus, {"a": _P("a"), "b": _P("b")})
    bus.now = 100
    bus.publish("office/reception/manual", "a")        # manual check-in, valid for 4 min
    bus.now = 200
    bus.publish("office/gate/badge", {"person": "b", "dir": "in", "gate": "corr1"})
    bus.publish("office/gate/beam", {"dir": "in", "gate": "corr1"})              # b, explained by b's badge
    bus.now = 230
    bus.publish("office/gate/beam", {"dir": "in", "gate": "corr1"})              # a walks through on the manual check-in
    bus.now = 300
    bus.publish("office/gate/beam", {"dir": "in", "gate": "corr1"})              # nobody's credential
    att.tick(400)
    assert att.tailgate_alerts == [300]


# ---- whole day -------------------------------------------------------------

def test_people_live_the_same_day_under_every_rule_set(day):
    _, sims = day
    trips = [json.dumps(s.trips) for s in sims.values()]
    assert trips[0] == trips[1] == trips[2]


def test_occupancy_control_saves_energy_against_the_schedule(day):
    _, sims = day
    m = {k: s.metrics() for k, s in sims.items()}
    assert m["pir"]["total_kwh"] < m["schedule"]["total_kwh"]
    assert m["pir+co2"]["false_offs"] < m["pir"]["false_offs"]
    assert m["pir+co2"]["person_min_in_dark"] < m["pir"]["person_min_in_dark"]


def test_everybody_who_came_is_in_the_register_or_flagged(day):
    _, sims = day
    s = sims["pir+co2"]
    m = s.metrics()
    missing = set(m["missing_from_register"])
    tailgaters = {pid for _, pid in s.truth.tailgates}
    assert missing <= tailgaters


def test_every_person_who_arrives_also_leaves(day):
    _, sims = day
    s = sims["schedule"]
    for p in s.people:
        if p.arrive < hm("20:30"):
            assert p.gone, (p.id, p.label)


def test_replay_is_valid_js_object(day, tmp_path):
    from lahore_twin.export import run_all, write
    replay, _ = run_all(seed=7)
    out = write(replay, tmp_path / "replay.js")
    text = out.read_text(encoding="utf-8")
    assert text.startswith("window.REPLAY = {") and text.rstrip().endswith(";")
    data = json.loads(text[len("window.REPLAY = "):].rstrip().rstrip(";"))
    assert set(data["modes"]) == {"schedule", "pir", "pir+co2"}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_viewer_core_under_node():
    r = subprocess.run(["node", str(ROOT / "tests" / "viewer_core.test.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_results_do_not_depend_on_the_process_hash_seed():
    import os
    import sys
    code = ("from lahore_twin.office import build; from lahore_twin.plan import Plan; "
            "from lahore_twin.sim import Sim; import json; "
            "print(json.dumps(Sim(build(Plan.load('office.json'), seed=3), 'pir+co2').run().metrics()))")
    outs = []
    for h in ("1", "2"):
        env = dict(os.environ, PYTHONHASHSEED=h, PYTHONUTF8="1")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, env=env)
        assert r.returncode == 0, r.stderr
        outs.append(r.stdout)
    assert outs[0] == outs[1]


def test_hot_room_gets_a_longer_precool(plan):
    from lahore_twin.office import Booking
    b = Booking("x", "prayer", "Zuhr congregation", hm("13:26"), hm("13:41"))
    bus, auto = _auto(plan, "pir", [b])
    bus.now = hm("12:00")
    bus.publish("office/prayer/temp", 31.0)
    fired_at = None
    for t in range(hm("12:00"), hm("13:30"), 5):
        bus.now = t
        auto.tick(t)
        if fired_at is None and auto.rooms["prayer"].ac:
            fired_at = t
    # 7 degrees above setpoint needs well over the 10-minute minimum
    assert hm("13:26") - fired_at >= 30 * 60


def test_same_second_double_count_is_not_called_a_tailgate():
    bus = Bus()
    att = Attendance(bus, {"a": _P("a")})
    bus.now = 500
    bus.publish("office/gate/badge", {"person": "a", "dir": "in", "gate": "corr1"})
    bus.publish("office/gate/beam", {"dir": "in", "gate": "corr1"})
    bus.publish("office/gate/beam", {"dir": "in", "gate": "corr1"})      # lingering, or a follower in the same second
    att.tick(600)
    assert att.tailgate_alerts == [] and att.double_counts == [500]
    assert any(m.topic == "office/alert/door_count" for m in bus.log)


def test_a_badge_at_another_door_explains_nothing():
    bus = Bus()
    att = Attendance(bus, {"a": _P("a")})
    bus.now = 700
    bus.publish("office/gate/badge", {"person": "a", "dir": "in", "gate": "reception"})
    bus.publish("office/gate/beam", {"dir": "in", "gate": "corr1"})
    att.tick(800)
    assert att.tailgate_alerts == [700]


def test_staff_outside_the_badge_line_are_registered_on_arrival(day):
    _, sims = day
    s = sims["schedule"]
    for role in ("receptionist", "guard"):
        p = next(x for x in s.people if x.role == role)
        assert abs(s.att.checkin[p.id] - p.arrive) < 120, (role, s.att.checkin.get(p.id), p.arrive)


def test_hold_grows_after_a_wrong_switch_off_and_relaxes_after_a_right_one(plan):
    bus, auto = _auto(plan, "pir")
    st = auto.rooms["mgr1"]
    bus.now = hm("10:00")
    bus.publish("office/mgr1/motion", 1)
    auto.tick(hm("10:10"))                      # 10 min silence -> off
    assert not st.light and st.hold_mult == 1
    bus.now = hm("10:10") + 15
    bus.publish("office/mgr1/motion", 1)        # someone was there all along
    assert st.light and st.hold_mult == 2
    auto.tick(hm("10:31"))                      # now needs 20 min of silence (last motion 10:10:15)
    assert not st.light
    auto.tick(hm("10:32"))                      # nobody contradicted it: relax
    assert st.hold_mult == 1


def test_wall_switch_works_under_every_rule_set(plan):
    for mode in ("schedule", "pir", "pir+co2"):
        bus, auto = _auto(plan, mode)
        bus.now = hm("07:40")
        bus.publish("office/work/switch", True)
        assert auto.rooms["work"].light, mode


def test_gate_results_do_not_depend_on_the_rule_set(day):
    _, sims = day
    keys = ("tailgates_true", "tailgates_caught", "tailgate_false_alarms", "beam_misses", "door_count_alerts")
    got = [{k: s.metrics()[k] for k in keys} for s in sims.values()]
    assert got[0] == got[1] == got[2]


def test_rollcall_estimate_counts_the_tailgater_until_they_leave():
    bus = Bus()
    att = Attendance(bus, {"a": _P("a"), "t": _P("t")})
    bus.now = 100
    bus.publish("office/gate/badge", {"person": "a", "dir": "in", "gate": "corr1"})
    bus.publish("office/gate/beam", {"dir": "in", "gate": "corr1"})
    bus.now = 103
    bus.publish("office/gate/beam", {"dir": "in", "gate": "corr1"})     # t follows, no badge
    att.tick(200)
    assert att.register_inside() == 1 and att.estimate_inside() == 2
    bus.now = 5000
    bus.publish("office/gate/badge", {"person": "t", "dir": "out", "gate": "corr1"})
    assert att.estimate_inside() == 1      # the unknown entry left


def test_drifted_door_counters_are_rezeroed_to_the_estimate():
    bus = Bus()
    att = Attendance(bus, {"a": _P("a")})
    bus.now = 100
    bus.publish("office/gate/badge", {"person": "a", "dir": "in", "gate": "corr1"})
    for _ in range(3):                      # three phantom counts
        bus.publish("office/gate/beam", {"dir": "in", "gate": "corr1"})
    att.counted_inside = 4
    att.rollcall_tick(1000)
    assert att.counted_inside == 4          # not yet: needs 15 minutes of disagreement
    att.rollcall_tick(1000 + 900)
    assert att.counted_inside == att.estimate_inside()


def test_people_do_not_stand_on_each_other(day):
    """Shared spots are claimed on arrival; only a full washroom or queue tail may stack."""
    sc, _ = day
    import collections
    s = Sim(sc, "pir")
    stacked = collections.Counter()
    orig = s._report

    def watch(t):
        c = collections.Counter((round(p.pos[0], 2), round(p.pos[1], 2))
                                for p in s.people if p.on_site and not p.path)
        stacked.update(k for k, v in c.items() if v > 1)
        orig(t)

    s._report = watch
    s.run()
    assert sum(stacked.values()) <= 30, stacked.most_common(5)     # person-minutes in a day
    prayer = {tuple(x) for x in s.plan.spots["prayer_spot"]}
    assert not any(k in prayer for k in stacked)


def test_committed_replay_matches_the_current_code():
    """viewer/replay.js is committed so the viewer opens without Python; it must not go stale."""
    from lahore_twin.export import source_digest
    text = (ROOT / "viewer" / "replay.js").read_text(encoding="utf-8")
    meta = json.loads(text[len("window.REPLAY = "):].rstrip().rstrip(";"))["meta"]
    assert meta.get("digest") == source_digest(), "run `python demo.py` to regenerate viewer/replay.js"
