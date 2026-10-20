"""Phase 5: fix a jammed junction, and get an ambulance through the evening peak.

Junction planner. For one signalised junction it tries the fixes Lahore actually uses, each on
exactly the same trips:

* ``retime``   — split the cycle by measured demand (Webster's method)
* ``adaptive`` — loop detectors at this junction only
* ``uturn``    — the crossing closes. Side roads may only turn left onto the main road;
                 through and right movements turn left and U-turn at the nearest gap
                 150-400 m along the main road (the "signal-free corridor" conversion)
* ``underpass``— the main road's through traffic goes under the crossing; turning traffic
                 and the side road keep a surface signal, retimed for what is left

Ambulance. Rescue 1122 calls during the peak: from the real station in OpenStreetMap to the
call, ten minutes there, then to the nearest hospital with an emergency department. Three
ways: no priority, siren (others pull over, it crosses a red slowly), and a green wave (each
signal on its route turns green ~25 s before it arrives).
"""

from __future__ import annotations

import heapq
import json
import math
import random
from pathlib import Path

from .roads import Network, _project, load
from .traffic_sim import (AMBER, ALL_RED, Signal, TrafficSim, Trip, build_signals, expected_wait, make_demand,
                          snap_pois)

ROOT = Path(__file__).resolve().parent.parent
FIXES = ("baseline", "retime", "adaptive", "uturn", "underpass")
FIX_NAMES = {"baseline": "As today", "retime": "Retime the signal", "adaptive": "Adaptive signal",
             "uturn": "U-turn conversion", "underpass": "Underpass"}
PCU = {"motorcycle": 0.4, "car": 1.0, "rickshaw": 0.8, "bus": 3.0, "ambulance": 1.0}   # assumption
SATURATION = 1800                # pcu per lane per hour of green
LOST = 2 * (AMBER + ALL_RED)     # seconds of each cycle no one moves
EMERGENCY = ("Shaikh Zayed Medical Complex", "Hameed Latif Hospital", "United Christian Hospital", "Naseer Hospital",
             "Hijaz Hospital Lahore", "Lahore Speciality Hospital", "Nobel Hospital", "Fazal Cardiac Hospital")
NEAR_M = 350                     # delay "at the junction" counts stops within this of its centre (covers U-turn gaps)


def _centre(net: Network, sig: Signal) -> tuple[float, float]:
    return (sum(net.nodes[n][0] for n in sig.nodes) / len(sig.nodes),
            sum(net.nodes[n][1] for n in sig.nodes) / len(sig.nodes))


def _turn(a, b) -> float:
    """Signed turn from link a into link b, radians; positive = left (map frame, y down -> flip)."""
    (x0, y0), (x1, y1) = a.pts[-2], a.pts[-1]
    (x2, y2), (x3, y3) = b.pts[0], b.pts[1]
    h1 = math.atan2(-(y1 - y0), x1 - x0)
    h2 = math.atan2(-(y3 - y2), x3 - x2)
    return (h2 - h1 + math.pi) % (2 * math.pi) - math.pi


# ------------------------------------------------------------------ movements and routing
class Movements:
    """Link-to-link moves for rerouting around a converted junction. A movement through a
    junction is judged whole, approach link to exit link: a divided road's internal links are
    shared by several movements, so banning one internal step would ban the main road too."""

    def __init__(self, net: Network):
        self.net = net
        self.out: dict[int, list] = {}
        for lk in net.links:
            self.out.setdefault(lk.a, []).append(lk)
        self.macro: dict[int, dict[int, list[int]]] = {}   # approach -> {allowed exit: internal links}
        self.internal: set[int] = set()
        self.uturn_ok: set[int] = set()            # links whose end may be used to U-turn
        self.median: dict[int, int] = {}           # divided road: link -> opposite carriageway across a median gap
        self.uturn_cost = 20.0                     # seconds: slowing, waiting for a gap, turning
        self.wait = expected_wait(build_signals(net))

    def cost(self, lk) -> float:
        return lk.length / lk.speed + self.wait.get(lk.id, 0.0)

    def nexts(self, lk):
        """(next link, extra seconds, internal links passed on the way)."""
        if lk.id in self.macro:
            for ex, via in self.macro[lk.id].items():
                yield self.net.links[ex], sum(self.cost(self.net.links[v]) for v in via), via
            return
        if lk.id in self.median:
            yield self.net.links[self.median[lk.id]], self.uturn_cost, ()
        for o in self.out.get(lk.b, ()):
            if o.id in self.internal:
                continue
            if o.road == lk.road and o.b == lk.a:                     # a U-turn
                if lk.id not in self.uturn_ok and len(self.out.get(lk.b, ())) > 1:
                    continue
                yield o, self.uturn_cost, ()
            else:
                yield o, 0.0, ()

    def banned_at(self, route: list[int], start: int = 0) -> int | None:
        """Index of the first approach link in route whose movement is not allowed."""
        for i in range(start, len(route) - 1):
            allowed = self.macro.get(route[i])
            if allowed is None:
                continue
            j = i + 1
            while j < len(route) and route[j] in self.internal:
                j += 1
            if j < len(route) and route[j] not in allowed:
                return i
        return None

    def route(self, start: int, goal: int) -> list[int] | None:
        """Fastest link sequence from link start (exclusive) to link goal (inclusive)."""
        links = self.net.links
        dist = {start: 0.0}
        prev: dict[int, tuple] = {}
        q = [(0.0, start)]
        while q:
            d, lid = heapq.heappop(q)
            if lid == goal:
                out = []
                while lid != start:
                    p, via = prev[lid]
                    out.append(lid)
                    out.extend(reversed(via))
                    lid = p
                return out[::-1]
            if d > dist.get(lid, math.inf):
                continue
            for o, extra, via in self.nexts(links[lid]):
                nd = d + self.cost(o) + extra
                if nd < dist.get(o.id, math.inf):
                    dist[o.id], prev[o.id] = nd, (lid, tuple(via))
                    heapq.heappush(q, (nd, o.id))
        return None


def uturn_conversion(net: Network, sig: Signal) -> tuple[Movements, list, list[int]]:
    """Allow only the main road straight on and left turns through the junction.
    Returns the movements, the U-turn gaps [(link id, x, y)], and the main road's approaches."""
    mv = Movements(net)
    group = set(sig.nodes)
    main_ph = 0 if sig.greens[0] >= sig.greens[1] else 1
    main_links = set(sig.phases[main_ph])
    top = max(net.links[l].rank for l in main_links)
    # the main road itself: named, the biggest class (a nameless slip road is not it)
    main_names = {net.links[l].name for l in main_links if net.links[l].name and net.links[l].rank == top}
    mv.internal = {lk.id for lk in net.links if lk.a in group and lk.b in group}
    for a in (l for ph in sig.phases for l in ph):
        lk = net.links[a]
        allowed: dict[int, list[int]] = {}
        stack, seen = [(lk, [])], set()
        while stack:
            cur, via = stack.pop()
            for o in mv.out.get(cur.b, ()):
                if o.id in seen or o.id == a:
                    continue
                seen.add(o.id)
                if o.id in mv.internal:
                    stack.append((o, via + [o.id]))
                    continue
                if o.road == lk.road and o.b == lk.a:
                    continue                                          # no U-turn in the junction
                straight_main = a in main_links and o.name in main_names and abs(_turn(lk, o)) < 0.7
                if straight_main or 0.5 < _turn(lk, o) < 2.6:          # a left turn, not a U-turn
                    allowed.setdefault(o.id, via)
        mv.macro[a] = allowed
    # gaps: the first node 150-400 m downstream on the main road, each direction
    cx, cy = _centre(net, sig)
    cands = []
    for lk in net.links:
        if lk.name in main_names and lk.layer == 0 and lk.a not in group and lk.b not in group:
            d0, d1 = math.dist((cx, cy), net.nodes[lk.a]), math.dist((cx, cy), net.nodes[lk.b])
            if 150 <= d1 <= 400 and d1 > d0 and any(o.road == lk.road and o.b == lk.a for o in mv.out.get(lk.b, ())):
                cands.append((d1, lk))
    # a divided road has no way to turn back on itself: open a gap in the median to the
    # opposite carriageway (within 35 m, heading back), as Lahore's U-turn conversions do
    for lk in net.links:
        if not (lk.name in main_names and lk.layer == 0 and lk.oneway and lk.a not in group and lk.b not in group):
            continue
        d0, d1 = math.dist((cx, cy), net.nodes[lk.a]), math.dist((cx, cy), net.nodes[lk.b])
        if not (150 <= d1 <= 400 and d1 > d0):
            continue
        back = [o for o in net.links if o.name in main_names and o.oneway and o.layer == 0 and o.road != lk.road
                and math.dist(net.nodes[lk.b], o.pts[0]) < 35 and abs(_turn(lk, o)) > 2.4]
        if back:
            o = min(back, key=lambda o: math.dist(net.nodes[lk.b], o.pts[0]))
            mv.median[lk.id] = o.id
            cands.append((d1, lk))
    chosen = []
    for d1, lk in sorted(cands, key=lambda c: c[0]):
        if all(math.dist(net.nodes[lk.b], net.nodes[c.b]) > 120 for c in chosen):   # one gap per direction
            chosen.append(lk)
        if len(chosen) == 2:
            break
    mv.uturn_ok = {c.id for c in chosen}
    mv.median = {k: v for k, v in mv.median.items() if k in mv.uturn_ok}
    return mv, [(c.id, *net.nodes[c.b]) for c in chosen], sorted(main_links)


def reroute(trips: list[Trip], mv: Movements, net: Network) -> tuple[list[Trip], int]:
    """Trips whose route makes a banned move are rerouted from there to their next fixed point
    (their next stop's link, or their last link), keeping the stops' positions."""
    out, changed = [], 0
    for tr in trips:
        route, stops = list(tr.route), list(tr.stops)
        bad = mv.banned_at(route)
        if bad is None:
            out.append(tr)
            continue
        ok = True
        while bad is not None:
            nxt = [s for s in stops if s[0] > bad]
            k = min(s[0] for s in nxt) if nxt else len(route) - 1
            mid = mv.route(route[bad], route[k])
            if mid is None:
                ok = False
                break
            new = route[:bad + 1] + mid + route[k + 1:]
            shift = len(new) - len(route)
            stops = [(s[0] + shift if s[0] > bad else s[0],) + tuple(s[1:]) for s in stops]
            route = new
            bad = mv.banned_at(route, bad + 1)
        if not ok:
            out.append(tr)                       # nowhere legal to go: keeps its old route
            continue
        changed += 1
        free = sum(net.links[l].length / net.links[l].speed for l in route)
        if stops and stops[-1][2] < 0:
            lk = net.links[route[-1]]
            free -= (lk.length - stops[-1][1]) / lk.speed
        out.append(Trip(tr.t, tr.kind, route, free, stops, tr.purpose))
    return out, changed


# ------------------------------------------------------------------ retiming
def webster(trips: list[Trip], net: Network, sig: Signal, minutes: int, skip_through: set[int] = frozenset()) -> list[int]:
    """Green split by Webster's method from the demand on each phase's critical lane.
    skip_through: approach links whose straight-on traffic no longer uses the signal."""
    flow = {}
    for tr in trips:
        for i, lid in enumerate(tr.route[:-1]):
            if lid in skip_through and net.links[tr.route[i + 1]].name == net.links[lid].name:
                continue
            flow[lid] = flow.get(lid, 0.0) + PCU[tr.kind]
    per_hour = 60 / minutes
    y = []
    for ids in sig.phases:
        y.append(max((flow.get(l, 0.0) * per_hour / net.links[l].lanes for l in ids), default=0.0) / SATURATION)
    Y = sum(y)
    cycle = 140 if Y >= 0.9 else min(140, max(60, (1.5 * LOST + 5) / (1 - Y)))
    green = cycle - LOST
    if Y <= 0:
        return [green // 2, green - green // 2]
    g = [max(15, round(green * yi / Y)) for yi in y]
    return g


# ------------------------------------------------------------------ one scenario
def _watch(sim: TrafficSim, sig: Signal, centre, every: int = 30):
    """Record, every `every` s, how many vehicles stand within NEAR_M of the junction."""
    net = sim.net
    near = {lk.id for lk in net.links if min(math.dist(centre, p) for p in (lk.pts[0], lk.pts[-1])) < NEAR_M}
    series = []
    step = sim.step

    def watched(t):
        step(t)
        if t % every == 0:
            q = sum(1 for lid in near for ln in sim.lanes[lid] for v in ln if v.v < 0.5 and v.hold_until is None)
            series.append(q)
    sim.step = watched
    return series, near


def run_fix(net: Network, trips: list[Trip], sig_name: str, fix: str, minutes: int) -> dict:
    sim_trips, extra = trips, {}
    base_sigs = {s.name: s for s in build_signals(net)}
    sig = base_sigs[sig_name]
    centre = _centre(net, sig)
    if fix == "uturn":
        mv, gaps, main_links = uturn_conversion(net, sig)
        sim_trips, changed = reroute(trips, mv, net)
        extra = {"rerouted": changed, "gaps": [[round(x, 1), round(y, 1)] for _, x, y in gaps]}
    sim = TrafficSim(net, sim_trips, "fixed", minutes=minutes)
    s = next(x for x in sim.signals if x.name == sig_name)
    if fix == "retime":
        s.greens = webster(trips, net, s, minutes)
    elif fix == "adaptive":
        s.adaptive = True
    elif fix == "underpass":
        main_ph = 0 if s.greens[0] >= s.greens[1] else 1
        sim.underpass = set(s.phases[main_ph])
        s.greens = webster(trips, net, s, minutes, skip_through=sim.underpass)
    elif fix == "uturn":
        # the crossing is gone: no controller here any more
        sim.signals = [x for x in sim.signals if x is not s]
        for lid in [l for ph in s.phases for l in ph]:
            sim.sig_of.pop(lid, None)
    series, near = _watch(sim, s, centre)
    sim.run()
    m = sim.metrics()
    nodes = {n for lid in near for n in (net.links[lid].a, net.links[lid].b)}
    km = sum(net.links[l].length for v in sim.vehicles for l in v.route) / 1000
    return {
        "fix": fix, "greens": list(s.greens) if fix != "uturn" else None,
        "junction_veh_h": round(sum(d for n, d in sim.node_delay.items() if n in nodes) / 3600, 1),
        "queue_peak": max(series, default=0),
        "queue": series,
        "delay_median_s": m["delay_median_s"], "delay_mean_s": m["delay_mean_s"],
        "completed": m["completed"], "gridlocked": m["gridlocked"], "still_driving": m["still_driving"],
        "km": round(km, 1), "speed_mean_kmh": m["speed_mean_kmh"],
        "pedestrian_crossing": {"baseline": "signal", "retime": "signal", "adaptive": "signal",
                                "uturn": "none: the signal-protected crossing is gone",
                                "underpass": "signal (surface)"}[fix],
        **extra,
    }


def plan_junction(net: Network, trips: list[Trip], sig_name: str, minutes: int) -> dict:
    res = {f: run_fix(net, trips, sig_name, f, minutes) for f in FIXES}
    b = res["baseline"]
    for f, r in res.items():
        r["km_extra"] = round(r["km"] - b["km"], 1)
    return res


# ------------------------------------------------------------------ ambulance
def station(net: Network) -> tuple[float, float]:
    raw = json.loads((ROOT / "plans" / "osm" / "rescue_1122.json").read_text(encoding="utf-8"))
    st = raw["stations"][0]
    return _project(*net.origin)(st["lat"], st["lon"])


def _nearest_node(net: Network, xy, ok=lambda lk: True) -> int:
    best = min((lk for lk in net.links if lk.layer == 0 and ok(lk)),
               key=lambda lk: min(math.dist(xy, p) for p in (lk.pts[0], lk.pts[-1])))
    return best.a if math.dist(xy, best.pts[0]) <= math.dist(xy, best.pts[-1]) else best.b


def ambulance_calls(net: Network, seed: int, minutes: int, n: int = 10) -> list[Trip]:
    """n Rescue 1122 calls in the hour: station -> the call (10 min there) -> nearest emergency
    department. Calls land on residential streets (assumption)."""
    rng = random.Random(seed * 101 + 1122)
    mv = Movements(net)
    sxy = station(net)
    # the station opens onto both carriageways of Firozpur Road (a divided road): an ambulance
    # leaves by whichever road within 200 m is quickest for the call, not round a 5 km loop
    near_st = [lk for lk in net.links if lk.rank >= 2 and lk.layer == 0 and math.dist(sxy, lk.pts[0]) < 200]
    hosp = [p for p in snap_pois(net) if p["kind"] == "hospital" and p["name"] in EMERGENCY]
    homes = [lk for lk in net.links if lk.cls in ("residential", "living_street") and lk.length >= 40 and lk.layer == 0]
    trips = []
    for k in range(n):
        t = int((k + 0.5) * minutes * 60 / n + rng.uniform(-60, 60))
        scene = rng.choice(homes)
        # out of the station whichever way is quicker (by time, not by how many road pieces)
        leg1, best1 = None, math.inf
        for first in near_st:
            r = mv.route(first.id, scene.id)
            if r is not None:
                tt = math.dist(sxy, first.pts[0]) / 5 + mv.cost(first) + sum(mv.cost(net.links[l]) for l in r)
                if tt < best1:
                    leg1, best1 = [first.id] + r, tt
        if leg1 is None:
            continue
        best = None
        for h in hosp:
            for lid, pos in h["access"]:
                r = mv.route(scene.id, lid)
                if r is None:
                    continue
                tt = sum(mv.cost(net.links[l]) for l in r)
                if best is None or tt < best[0]:
                    best = (tt, r, pos, h)
        if best is None:
            continue
        _, leg2, pos, h = best
        route = leg1 + leg2
        stops = [(len(leg1) - 1, round(min(max(scene.length / 2, 15), scene.length - 10), 1), 600, "patient pickup", False, -1),
                 (len(route) - 1, pos, -1, f"to {h['name']}", True, h["i"])]
        free = sum(net.links[l].length / net.links[l].speed for l in route)
        trips.append(Trip(t, "ambulance", route, free, stops, "Rescue 1122 call"))
    return trips


def run_ambulance(net: Network, trips: list[Trip], calls: list[Trip], amb_mode: str, minutes: int) -> dict:
    allt = sorted(trips + calls, key=lambda tr: tr.t)
    sim = TrafficSim(net, allt, "fixed", minutes=minutes, amb_mode=amb_mode)
    sim.run()
    out = []
    for v in sim.vehicles:
        if v.kind != "ambulance":
            continue
        log = v.stop_log
        scene = log[0] if log else None
        hosp = log[1] if len(log) > 1 else None
        # distance along the route against time, for the time-distance diagram
        prefix = [0.0]
        for lid in v.route:
            prefix.append(prefix[-1] + net.links[lid].length)
        trace = [[t, round(prefix[ri] + pos)] for t, ri, pos, _ in v.samples]
        out.append({"id": v.id, "t0": v.t0, "route": v.route,
                    "response_s": scene[0] - v.t0 if scene else None,
                    "to_hospital_s": hosp[0] - scene[1] if hosp and scene and scene[1] else None,
                    "reds": len(sim.amb_reds.get(v.id, ())), "stops": v.stops, "trace": trace,
                    "scene_at": [scene[0], scene[1]] if scene else None, "hospital": hosp[2] if hosp else None})
    m = sim.metrics()
    return {"mode": amb_mode, "calls": out, "delay_median_s": m["delay_median_s"], "completed": m["completed"],
            "preemptions": len(sim.preempt_log), "signal_delay_veh_h": m["signal_delay_veh_h"],
            "signal_logs": {str(s.id): s.log for s in sim.signals}}


def run_all(seed: int = 7, per_hour: int = 8000, minutes: int = 30, junctions: int = 3) -> dict:
    net = load()
    trips = make_demand(net, seed=seed, minutes=minutes, per_hour=per_hour, period="evening")
    base = TrafficSim(net, trips, "fixed", minutes=minutes).run()
    worst = [name for name, _ in base.metrics()["worst_junctions"][:junctions]]
    plans = {name: plan_junction(net, trips, name, minutes) for name in worst}
    calls = ambulance_calls(net, seed, minutes)
    amb = {mode: run_ambulance(net, trips, calls, mode, minutes) for mode in ("none", "siren", "greenwave")}
    return {"worst": worst, "plans": plans, "ambulance": amb, "trips": len(trips)}
