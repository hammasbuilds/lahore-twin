import json
from pathlib import Path

import pytest

from lahore_twin.bus import Bus
from lahore_twin.climate import JUNE, OCTOBER, hm
from lahore_twin.home import build
from lahore_twin.home_sim import HomeSim
from lahore_twin.plan import Plan
from lahore_twin.power import Battery, Inverter, InverterSettings, RoofTank

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def plan():
    return Plan.load("home.json")


@pytest.fixture(scope="module")
def day(plan):
    sc = build(plan, JUNE, seed=7)
    return sc, {m: HomeSim(sc, m).run() for m in ("default", "ups", "gridsense")}


# ---- physics ---------------------------------------------------------------

def test_overload_trips_the_inverter_for_a_minute_in_an_outage():
    inv = Inverter()
    r = inv.step(100, 10, {"a": 4.0, "b": 2.5}, {"a", "b"}, grid_up=False, pv_kw=0.0)
    assert r.tripped and r.dark and not r.served and inv.trips == 1
    r = inv.step(130, 10, {"a": 1.0}, {"a"}, grid_up=False, pv_kw=0.0)
    assert r.dark                                   # still inside the minute
    r = inv.step(170, 10, {"a": 1.0}, {"a"}, grid_up=False, pv_kw=0.0)
    assert not r.dark and "a" in r.served


def test_battery_stops_at_cutoff_and_the_house_goes_dark():
    inv = Inverter(battery=Battery(soc=0.105))
    dark = False
    for k in range(200):
        r = inv.step(k * 10, 10, {"fan": 0.4}, {"fan"}, grid_up=False, pv_kw=0.0)
        dark = dark or r.dark
    assert dark and inv.battery.soc >= 0.099


def test_sbu_spends_the_battery_only_above_back_to_grid():
    inv = Inverter(battery=Battery(soc=0.5), settings=InverterSettings("SBU", 0.45, 0.0))
    r = inv.step(0, 10, {"x": 1.0}, {"x"}, grid_up=True, pv_kw=0.0)
    assert r.batt_kw > 0.9 and r.grid_kw < 0.1
    inv.battery.soc = 0.40
    r = inv.step(10, 10, {"x": 1.0}, {"x"}, grid_up=True, pv_kw=0.0)
    assert r.batt_kw == 0 and r.grid_kw == pytest.approx(1.0)


def test_exported_solar_is_not_counted_as_used_at_home():
    inv = Inverter(battery=Battery(soc=1.0))
    r = inv.step(0, 10, {"x": 0.5}, {"x"}, grid_up=True, pv_kw=3.0)
    assert r.grid_kw == pytest.approx(-2.5) and r.pv_used_kw == pytest.approx(0.5)


def test_tank_runs_dry_and_counts_it():
    tank = RoofTank(level_l=10)
    got = tank.step(10, 25, pumping=False)
    assert got == 10 and tank.empty_s == 10


# ---- scenario -----------------------------------------------------------------

def test_the_family_lives_the_same_day_under_every_controller(day):
    _, sims = day
    trips = [json.dumps(s.trips_log) for s in sims.values()]
    assert trips[0] == trips[1] == trips[2]


def test_outages_mix_published_and_unannounced(plan):
    for seed in range(1, 6):
        sc = build(plan, JUNE, seed=seed)
        pub = [o for o in sc.outages if o.published]
        assert sum(o.end - o.start for o in pub) == 5 * 3600            # category IV
        assert any(not o.published for o in sc.outages)
        assert all(a.end <= b.start for a, b in zip(sc.outages, sc.outages[1:]))


def test_october_is_milder_than_june():
    assert OCTOBER.outdoor_temp(hm("15:00")) < JUNE.outdoor_temp(hm("15:00")) - 5
    assert OCTOBER.pv_kwh_per_kwp < JUNE.pv_kwh_per_kwp


# ---- controllers -----------------------------------------------------------------

def test_default_goes_dark_where_gridsense_does_not(day):
    _, sims = day
    m = {k: s.metrics() for k, s in sims.items()}
    assert m["default"]["house_dark_min"] > 0
    assert m["gridsense"]["house_dark_min"] == 0 and m["gridsense"]["no_fan_person_min"] == 0


def test_ups_wiring_loses_the_acs_in_an_outage_and_wastes_solar(day):
    _, sims = day
    ups = sims["ups"]
    assert "ac:bed1" not in ups.ctrl.on_inverter and "fan:bed1" in ups.ctrl.on_inverter
    m = {k: s.metrics() for k, s in sims.items()}
    assert m["ups"]["hot_sleep_person_min"] > m["gridsense"]["hot_sleep_person_min"]
    assert m["ups"]["solar_wasted_kwh"] > 0


def test_gridsense_holds_a_reserve_before_a_published_outage(day):
    sc, sims = day
    gs = sims["gridsense"]
    night = next(o for o in sc.outages if o.published and o.start >= hm("21:00"))
    i = night.start // 60 - 1
    target, _ = gs.ctrl.reserve_soc(night.start - 60)
    assert gs.series["soc"][i] >= target - 0.05


def test_outage_rationing_does_not_flap(day):
    sc, sims = day
    gs = sims["gridsense"]
    flips = 0
    for o in sc.outages:
        changes = [c for c in gs.dev_changes if c[1].startswith("ac:") and o.start <= c[0] < o.end]
        flips += len(changes)
    assert flips <= 12, flips


def test_gridsense_never_trips_the_inverter_over_five_days(plan):
    for seed in range(1, 6):
        m = HomeSim(build(plan, JUNE, seed=seed), "gridsense").run().metrics()
        assert m["overload_trips"] == 0, seed


def test_low_voltage_protects_the_compressors(plan):
    from lahore_twin.gridsense import GridSense
    sc = build(plan, JUNE, seed=7)
    s = HomeSim(sc, "gridsense")
    bus, ctrl = s.bus, s.ctrl
    bus.now = hm("20:00")
    bus.publish("home/grid/voltage", 182.0)
    ctrl.tick(hm("20:00"))
    assert ctrl.state["fridge"] is False
    bus.publish("home/grid/voltage", 220.0)
    ctrl.tick(hm("20:01"))
    assert ctrl.state["fridge"] is False             # waits for a steady supply
    ctrl.tick(hm("20:03"))
    assert ctrl.state["fridge"] is True
    assert isinstance(ctrl, GridSense)


def test_the_bill_values_the_battery_left_at_the_end(day):
    _, sims = day
    for s in sims.values():
        m = s.metrics()
        raw = m["grid_peak_kwh"] * 50 + m["grid_offpeak_kwh"] * 42 - m["export_kwh"] * 11
        delta = (s.inverter.battery.soc - s.soc_start) * s.inverter.battery.capacity_kwh
        assert abs(m["bill_rs"] - (raw - delta * 42)) <= 1      # metrics use unrounded kWh


def test_committed_home_replay_matches_the_current_code():
    from lahore_twin.export import source_digest
    text = (ROOT / "viewer" / "home_replay.js").read_text(encoding="utf-8")
    meta = json.loads(text[len("window.HOME = "):].rstrip().rstrip(";"))["meta"]
    assert meta.get("digest") == source_digest("home"), "run `python demo_home.py` to regenerate viewer/home_replay.js"
