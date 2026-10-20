"""Traffic: real roads from OSM, and what the signal rule sets change."""

import json
import math
from pathlib import Path

import pytest

from lahore_twin.export import source_digest
from lahore_twin.roads import load, shortest, signal_sites
from lahore_twin.traffic_sim import MODES, TrafficSim, make_demand

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def net():
    return load()


@pytest.fixture(scope="module")
def runs(net):
    trips = make_demand(net, seed=3, minutes=15, per_hour=6000)
    return trips, {m: TrafficSim(net, trips, m, minutes=15).run() for m in MODES}


def test_the_network_keeps_real_road_features(net):
    classes = {lk.cls for lk in net.links}
    assert {"trunk", "secondary", "tertiary", "residential", "living_street"} <= classes
    assert any(lk.layer > 0 for lk in net.links), "flyovers"
    assert any(lk.layer < 0 for lk in net.links), "underpasses"
    assert any(lk.lanes >= 3 for lk in net.links) and any(lk.lanes == 1 for lk in net.links)
    one = [lk for lk in net.links if lk.oneway]
    two = [lk for lk in net.links if not lk.oneway]
    assert one and two


def test_a_flyover_never_meets_the_road_it_crosses(net):
    """Ground roads touch a flyover only where it begins or ends, never in the middle of it."""
    flyover_nodes = {n for lk in net.links if lk.layer > 0 for n in (lk.a, lk.b)}
    starts = {lk.a for lk in net.links if lk.layer > 0}
    finishes = {lk.b for lk in net.links if lk.layer > 0}
    middle = starts & finishes                      # a node a flyover passes through
    assert flyover_nodes
    # OSM joins two streets to the middle of a flyover here; a vehicle on them must not drive onto it
    touching = [lk for lk in net.links if lk.layer == 0 and lk.b in middle]
    assert all(o.layer == 0 for lk in touching for o in lk.out), [(lk.name, lk.cls) for lk in touching][:5]
    raised = [lk for lk in net.links if lk.layer > 0 and lk.b in middle]
    assert raised and all(o.layer == lk.layer for lk in raised for o in lk.out)


def test_every_link_can_be_reached_and_left(net):
    out = {}
    for lk in net.links:
        out.setdefault(lk.a, []).append(lk)
    assert all(lk.b in out for lk in net.links), "a link that leads nowhere"
    nodes = sorted({lk.a for lk in net.links})
    assert shortest(net, nodes[0], nodes[-1]) is not None
    assert shortest(net, nodes[-1], nodes[0]) is not None


def test_signals_sit_on_crossings_of_named_roads(net):
    groups = signal_sites(net)
    assert 15 <= len(groups) <= 80
    for g in groups:
        for n in g:
            assert any(math.dist(net.nodes[n], net.nodes[m]) < 45 for m in g)


def test_both_rule_sets_drive_the_same_vehicles(runs):
    trips, sims = runs
    a, b = (sims[m] for m in MODES)
    assert [v.t0 for v in a.vehicles] == [v.t0 for v in b.vehicles]
    assert [v.route for v in a.vehicles] == [v.route for v in b.vehicles]


def test_vehicles_obey_physics_and_red_lights(runs):
    _, sims = runs
    for s in sims.values():
        for v in s.vehicles:
            for (t0, r0, p0, _), (t1, r1, p1, _) in zip(v.samples, v.samples[1:]):
                d = (sum(s.links[l].length for l in v.route[r0:r1]) + p1 - p0)
                assert -0.5 <= d <= 30 * (t1 - t0) + 1, (v.id, d)          # never backwards, never above 108 km/h
        m = s.metrics()
        assert m["completed"] > 0.7 * m["trips"]


def test_adaptive_signals_cut_signal_delay(runs):
    _, sims = runs
    f, a = sims["fixed"].metrics(), sims["adaptive"].metrics()
    assert a["signal_delay_veh_h"] < f["signal_delay_veh_h"]
    assert a["stops_mean"] < f["stops_mean"]


def test_committed_traffic_replay_matches_the_current_code():
    text = (ROOT / "viewer" / "traffic_replay.js").read_text(encoding="utf-8")
    meta = json.loads(text[len("window.TRAFFIC = "):].rstrip().rstrip(";"))["meta"]
    assert meta["digest"] == source_digest("traffic"), "run python demo_traffic.py to refresh the replay"


def test_a_metre_long_stub_does_not_freeze_the_road(net):
    """OSM splits roads into stubs a metre long. Looking only one link ahead, a car at the end
    of a link saw 1.3 m of road (the stub) and stopped for good; 318 vehicles froze behind it
    on North Avenue and 227 never got onto the map."""
    trips = make_demand(net, seed=7, minutes=20, per_hour=8000)
    s = TrafficSim(net, trips, "fixed", minutes=20).run()
    m = s.metrics()
    # a late long trip may still be on its way and a car may be at a red light; a gridlock
    # is a vehicle that has not moved for five minutes
    assert m["not_yet_entered"] == 0, m
    assert m["gridlocked"] == 0, m


def test_fixed_signals_run_the_real_plan(runs):
    """The bigger road gets 60 s of green, the side road 30 s, then 3 s amber and 2 s all-red."""
    _, sims = runs
    s = sims["fixed"]
    timed = 0
    for sg in s.signals:
        assert sorted(sg.greens) in ([30, 60], [45, 45])
        for (t0, ph0, st0), (t1, ph1, st1) in zip(sg.log, sg.log[1:]):
            if st0 == "green":
                assert t1 - t0 == sg.greens[ph0] and st1 == "amber"
                timed += 1
            elif st0 == "amber":
                assert t1 - t0 == 3 and st1 == "allred"
            else:
                assert t1 - t0 == 2 and st1 == "green" and ph1 != ph0
    assert timed > 50
    # not one synchronised city: junctions change at different moments
    assert len({sg.log[0][0] for sg in s.signals if sg.log}) > 10


def test_people_stop_at_real_places_and_pull_off_to_park(runs):
    trips, sims = runs
    s = sims["adaptive"]
    shops = [v for v in s.vehicles if any(e[3] >= 0 for e in v.stop_log)]
    assert len(shops) > 0.05 * len(s.vehicles)
    parked = 0
    for v in shops:
        for (t, ri, pos, lane), nxt in zip(v.samples, v.samples[1:]):
            if lane == -1 and nxt[3] == -1:        # off the road: it does not move until it pulls out
                parked += 1
                assert (nxt[1], nxt[2]) == (ri, pos)
        for start, end, label, poi in v.stop_log:
            assert end is None or end - start >= 15
    assert parked > 0
    # the time at the shop is not counted as traffic delay
    m = s.metrics()
    assert m["errand_stops"] > 0 and m["delay_median_s"] < 600
    # a trip that ends at a place (the mall, a restaurant) is finished there, not driven off the map
    ended = [v for v in s.vehicles if v.stop_log and v.stop_log[-1][1] is None]
    assert ended and all(v.done == v.stop_log[-1][0] for v in ended)


def test_the_evening_has_shopping_and_the_morning_the_school_run(net):
    eve = make_demand(net, seed=5, minutes=10, per_hour=6000, period="evening")
    morn = make_demand(net, seed=5, minutes=10, per_hour=6000, period="morning")
    pe = {t.purpose for t in eve}
    pm = {t.purpose for t in morn}
    assert {"shopping", "pharmacy", "home"} <= pe and "school run" not in pe
    assert {"school run", "work"} <= pm and "shopping" not in pm
