"""Phase 5: the junction fixes and the ambulance's green wave."""

import json
from pathlib import Path
from statistics import median

import pytest

from lahore_twin import junctions as J
from lahore_twin.export import source_digest
from lahore_twin.roads import load
from lahore_twin.traffic_sim import AMBER, ALL_RED, TrafficSim, build_signals, make_demand

ROOT = Path(__file__).resolve().parent.parent
WORST = "Firozpur Road / Wahdat Road"


@pytest.fixture(scope="module")
def net():
    return load()


@pytest.fixture(scope="module")
def trips(net):
    return make_demand(net, seed=7, minutes=12, per_hour=8000, period="evening")


def test_a_uturn_conversion_reroutes_everyone_who_crossed(net, trips):
    sig = next(s for s in build_signals(net) if s.name == WORST)
    mv, gaps, main = J.uturn_conversion(net, sig)
    assert len(gaps) == 2
    before = [tr for tr in trips if mv.banned_at(tr.route) is not None]
    out, changed = J.reroute(trips, mv, net)
    assert before and changed >= 0.95 * len(before)
    assert sum(1 for tr in out if mv.banned_at(tr.route) is not None) <= 0.05 * len(before)
    # they turn back at the gap, not round the block: a divided road's U-turn crosses its median
    extra = [sum(net.links[l].length for l in b.route) - sum(net.links[l].length for l in a.route)
             for a, b in zip(trips, out) if a.route is not b.route]
    assert 0 < median(extra) < 1000
    via_gap = sum(1 for tr in out for i in range(len(tr.route) - 1)
                  if tr.route[i] in mv.uturn_ok and tr.route[i + 1] == mv.median.get(tr.route[i], -1))
    assert via_gap > 0.5 * changed
    # a rerouted route is still a chain of links (except the median crossing itself)
    for tr in out:
        for a, b in zip(tr.route, tr.route[1:]):
            la, lb = net.links[a], net.links[b]
            assert la.b == lb.a or mv.median.get(a) == b


def test_the_main_road_still_goes_straight_through_a_conversion(net):
    """Banning one internal step of a divided junction once banned the main road's own
    straight-on movement and trapped every car on the approach."""
    sig = next(s for s in build_signals(net) if s.name == WORST)
    mv, _, main = J.uturn_conversion(net, sig)
    for a in main:
        names = {net.links[e].name for e in mv.macro[a]}
        assert net.links[a].name in names or not net.links[a].name


def test_webster_splits_the_cycle_by_demand(net, trips):
    sig = next(s for s in build_signals(net) if s.name == WORST)
    g = J.webster(trips, net, sig, 12)
    assert 60 <= sum(g) + 2 * (AMBER + ALL_RED) <= 140 + 10
    # Firozpur's through traffic rides the flyover above, so Wahdat Road carries more per lane here
    main_ph = 0 if sig.greens[0] >= sig.greens[1] else 1
    assert g[1 - main_ph] > g[main_ph]


def test_every_fix_helps_the_worst_junction_on_the_same_trips(net, trips):
    res = {f: J.run_fix(net, trips, WORST, f, 12) for f in J.FIXES}
    base = res["baseline"]["junction_veh_h"]
    for f in ("retime", "adaptive", "uturn", "underpass"):
        assert res[f]["junction_veh_h"] < base, (f, res[f]["junction_veh_h"], base)
    assert res["uturn"]["km"] > res["baseline"]["km"]            # the conversion costs driving
    assert res["baseline"]["km"] == res["retime"]["km"] == res["underpass"]["km"]


def test_the_green_wave_never_skips_amber_or_all_red(net, trips):
    calls = J.ambulance_calls(net, 7, 12, n=3)
    assert calls and all(tr.kind == "ambulance" for tr in calls)
    allt = sorted(trips + calls, key=lambda tr: tr.t)
    sim = TrafficSim(net, allt, "fixed", minutes=12, amb_mode="greenwave").run()
    assert sim.preempt_log
    for s in sim.signals:
        for (t0, _, st0), (t1, _, st1) in zip(s.log, s.log[1:]):
            if st0 == "amber":
                assert st1 == "allred" and t1 - t0 == AMBER
            elif st0 == "allred":
                assert st1 == "green" and t1 - t0 == ALL_RED
    amb = [v for v in sim.vehicles if v.kind == "ambulance"]
    assert sum(len(sim.amb_reds.get(v.id, ())) for v in amb) == 0


def test_a_green_wave_gets_the_ambulance_there_sooner(net, trips):
    calls = J.ambulance_calls(net, 7, 12, n=3)
    res = {m: J.run_ambulance(net, trips, calls, m, 12) for m in ("none", "greenwave")}
    common = [c["t0"] for c in res["none"]["calls"] if c["response_s"] is not None]
    r = {m: sum(c["response_s"] for c in res[m]["calls"] if c["t0"] in common) for m in res}
    assert r["greenwave"] < r["none"]
    assert res["none"]["preemptions"] == 0 < res["greenwave"]["preemptions"]


def test_committed_junctions_replay_matches_the_current_code():
    text = (ROOT / "viewer" / "junctions_replay.js").read_text(encoding="utf-8")
    meta = json.loads(text[len("window.JUNCTIONS = "):].rstrip().rstrip(";"))["meta"]
    assert meta["digest"] == source_digest("junctions"), "run python demo_junctions.py to refresh the replay"
