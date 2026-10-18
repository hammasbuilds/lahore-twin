import json
from pathlib import Path

import pytest

from lahore_twin.bus import Bus
from lahore_twin.climate import JUNE, OCTOBER, hm
from lahore_twin.home import build
from lahore_twin.home_sim import HomeSim, run_day
from lahore_twin.plan import Plan
from lahore_twin.power import Battery, Inverter, InverterSettings, RoofTank

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def plan():
    return Plan.load("home.json")


@pytest.fixture(scope="module")
def day(plan):
    sc = build(plan, JUNE, seed=7)
    return sc, {m: run_day(sc, m) for m in ("default", "ups", "gridsense_eco", "gridsense")}


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
    assert r.batt_kw > 0.9 and r.grid_in_kw < 0.1
    inv.battery.soc = 0.40
    r = inv.step(10, 10, {"x": 1.0}, {"x"}, grid_up=True, pv_kw=0.0)
    assert r.batt_kw == 0 and r.grid_in_kw == pytest.approx(1.0)

def test_solar_is_split_exactly_once():
    """Grid up: surplus goes out to the house's grid side. Outage with a full battery: it
    is curtailed (the review found it reported as used). Either way the parts add up."""
    inv = Inverter(battery=Battery(soc=1.0))
    r = inv.step(0, 10, {"x": 0.5}, {"x"}, grid_up=True, pv_kw=3.0)
    assert r.pv_load_kw == pytest.approx(0.5) and r.pv_out_kw == pytest.approx(2.5) and r.curtailed_kw == 0
    r = inv.step(10, 10, {"x": 0.3}, {"x"}, grid_up=False, pv_kw=4.0)
    assert r.pv_load_kw == pytest.approx(0.3) and r.curtailed_kw == pytest.approx(3.7) and r.pv_out_kw == 0
    for grid in (True, False):
        for soc in (0.2, 0.7, 1.0):
            inv = Inverter(battery=Battery(soc=soc), settings=InverterSettings("UTI", 0.3, 3.0))
            r = inv.step(0, 10, {"x": 1.2}, {"x"}, grid_up=grid, pv_kw=4.5)
            assert r.pv_load_kw + r.pv_batt_kw + r.pv_out_kw + r.curtailed_kw == pytest.approx(4.5)


def test_sun_and_grid_share_one_charge_limit():
    inv = Inverter(battery=Battery(soc=0.3), settings=InverterSettings("UTI", 0.9, 3.0))
    before = inv.battery.soc
    r = inv.step(0, 3600, {}, set(), grid_up=True, pv_kw=4.5)
    charged_kw = (inv.battery.soc - before) * inv.battery.capacity_kwh / inv.battery.efficiency
    assert charged_kw <= inv.battery.max_charge_kw + 1e-6 and r.pv_batt_kw + (r.grid_in_kw) <= 5.0 + 1e-6


def test_asking_more_than_the_battery_can_give_is_an_overload_not_a_cutoff():
    inv = Inverter(battery=Battery(soc=0.8))
    r = inv.step(0, 10, {"x": 5.3}, {"x"}, grid_up=False, pv_kw=0.0)
    assert r.dark and r.dark_reason == "overload" and r.tripped

def test_tank_runs_dry_and_counts_it():
    tank = RoofTank(level_l=10)
    got = tank.step(10, 25, pumping=False)
    assert got == 10 and tank.empty_s == 10


# ---- scenario -----------------------------------------------------------------

def test_the_family_lives_the_same_day_under_every_controller(day):
    _, sims = day
    trips = [json.dumps(s.trips_log) for s in sims.values()]
    assert len(trips) == 4 and len(set(trips)) == 1


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


def test_ups_wiring_loses_the_acs_in_an_outage_and_curtails_more_sun(day):
    _, sims = day
    ups = sims["ups"]
    assert "ac:bed1" not in ups.ctrl.on_inverter and "fan:bed1" in ups.ctrl.on_inverter
    m = {k: s.metrics() for k, s in sims.items()}
    assert m["ups"]["hot_sleep_person_min"] > m["gridsense"]["hot_sleep_person_min"]
    # a full battery in a cut has nowhere to put the sun when the big loads are grid-only
    assert m["ups"]["solar_wasted_kwh"] > m["gridsense"]["solar_wasted_kwh"]

def test_gridsense_holds_a_reserve_before_a_published_outage(day):
    """At the start of a published night outage the battery holds the reserve sized for it.
    A block at 00:00 is prepared the evening before (tomorrow's schedule is published), so
    there the check is the level carried over midnight."""
    sc, sims = day
    gs = sims["gridsense"]
    night = next(o for o in sc.outages if o.published and (o.start >= hm("21:00") or o.start < hm("06:00")))
    soc = gs.soc_start if night.start == 0 else gs.series["soc"][night.start // 60 - 1]
    target, _ = gs.ctrl.reserve_soc(night.start - 60 if night.start else 0)
    assert soc >= target - 0.05, (soc, target)


def test_outage_rationing_does_not_flap(day):
    """Flapping = one AC changing state more than three times inside ten minutes."""
    sc, sims = day
    for mode in ("gridsense", "gridsense_eco"):
        changes: dict[str, list[int]] = {}
        for t, aid, _, _ in sims[mode].dev_changes:
            if aid.startswith("ac:"):
                changes.setdefault(aid, []).append(t)
        for aid, ts in changes.items():
            for i in range(len(ts)):
                window = [x for x in ts[i:] if x - ts[i] <= 600]
                assert len(window) <= 3, (mode, aid, ts[i], len(window))


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


def test_the_bill_agrees_with_the_minute_series(day):
    """An independent path: integrate the minute samples of the meter instead of the
    10-second accumulators, price them, and credit the battery's end-of-day change."""
    _, sims = day
    for s in sims.values():
        S, cost = s.series, 0.0
        for t, kw in zip(S["t"], S["grid_kw"]):
            price = 50 if s.season.is_peak(t) else 42
            cost += (kw * price if kw > 0 else kw * 11) / 60
        b = s.inverter.battery
        cost -= (b.soc - s.soc_start) * b.capacity_kwh * 42
        assert abs(s.metrics()["bill_rs"] - cost) <= max(12, 0.05 * abs(cost)), (s.mode, s.metrics()["bill_rs"], cost)

def test_committed_home_replay_matches_the_current_code():
    from lahore_twin.export import source_digest
    text = (ROOT / "viewer" / "home_replay.js").read_text(encoding="utf-8")
    first = text.split("\n", 1)[0]
    scen = json.loads(first[len("window.HOME_SCENARIOS = "):].rstrip().rstrip(";"))
    assert set(scen) == {"june", "october"}
    meta = scen["june"]["meta"]
    assert scen["october"]["meta"]["digest"] == meta["digest"]
    assert meta.get("digest") == source_digest("home"), "run `python demo_home.py` to regenerate viewer/home_replay.js"


def test_eco_is_never_dark_and_cheaper_than_the_default_over_five_days(plan):
    """The product claim: the same reliability guarantees for less money."""
    bills = {"default": 0, "gridsense_eco": 0}
    for seed in range(1, 6):
        sc = build(plan, JUNE, seed=seed)
        for mode in bills:
            m = HomeSim(sc, mode).run().metrics()
            bills[mode] += m["bill_rs"]
            if mode == "gridsense_eco":
                assert m["house_dark_min"] == 0 and m["no_fan_person_min"] == 0, seed
    assert bills["gridsense_eco"] < bills["default"]


def test_people_who_go_out_are_not_at_home(plan):
    """The bug this guards: someone reaching the street was 'arriving' again at their bed."""
    from lahore_twin.home_sim import HomeSim as HS
    s = HS(build(plan, JUNE, seed=1), "default")
    seen = {}
    orig = s._physics

    def watch(t):
        orig(t)
        if t == hm("10:30"):
            seen.update({p.id: p.on_site for p in s.people})

    s._physics = watch
    s.run()
    out = [p.id for p in s.people if any(st.label == "Out" for st in p.day)]
    assert out and all(seen[pid] is False for pid in out), seen


@pytest.mark.parametrize("case", ["forecast_wrong", "cut_before_night"])
def test_gridsense_keeps_the_lights_on_when_its_assumptions_fail(plan, case):
    """Stress cases from home round 4: a clear-sky forecast on an overcast day, and an
    unannounced cut ending half an hour before the published night outage."""
    from lahore_twin.home import Outage
    # seeds with the shape each case needs: for the cut, the first two with a published
    # evening block to cut in front of (found, not hard-coded: outage draws differ by category)
    if case == "forecast_wrong":
        seeds = (2, 4)
    else:
        seeds = [k for k in range(1, 40)
                 if any(o.published and o.start >= hm("20:00") for o in build(plan, JUNE, seed=k).outages)][:2]
    for seed in seeds:
        sc = build(plan, JUNE, seed=seed)
        if case == "forecast_wrong":
            sc.day_factor, sc.forecast_factor = 0.45, 1.0
        else:
            night = next(o for o in sc.outages if o.published and o.start >= hm("20:00"))
            sc.outages = [o for o in sc.outages if not (night.start - 3 * 3600 < o.start < night.start)]
            sc.outages.append(Outage(night.start - 9000, night.start - 1800, False))
            sc.outages.sort(key=lambda o: o.start)
        for mode in ("gridsense_eco", "gridsense"):
            m = HomeSim(sc, mode).run().metrics()
            assert m["house_dark_min"] == 0 and m["no_fan_person_min"] == 0, (case, seed, mode)


def test_no_decisions_are_made_on_an_unknown_grid_state(plan):
    """The controller's first tick must already know whether the day starts in an outage."""
    sc = build(plan, JUNE, seed=7)
    assert not sc.grid_up(0)                     # seed 7 starts inside the 00:00 block
    s = HomeSim(sc, "gridsense").run()
    first = [m.text for m in s.bus.log if m.t == 0]
    assert not any("pre-cool" in x or "fill the tank" in x for x in first), first
