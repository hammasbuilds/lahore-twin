"""Vehicles driving Lahore's real roads for a peak hour, under two signal rule sets.

* ``fixed``    — what most Lahore signals do: a fixed cycle, the main road 60 s green and
  the side road 30 s, 3 s amber and 2 s all-red between them, the same all day.
* ``adaptive`` — the same junctions with loop detectors 40 m back on every approach:
  hold the green while cars keep arriving, end it on a gap, never past one and a half
  times the fixed green.

Trips are what people actually drive for. In the morning: to work and university, the
school run (stop at the school gate, then on to the office), fuel, breakfast, the
pharmacy. In the evening: home from work, shopping on Liberty and MM Alam Road, the mall,
food, the bank, the clinic, prayers at the mosque, tuition pick-ups. The places are real
shops and amenities from OpenStreetMap. A short stop is made in the kerb lane, blocking
it, as it is on Lahore's roads; a long one pulls off the road to park. Rickshaws stop
for passengers and wagons at their stops anywhere along the kerb.

Each vehicle follows the one ahead with the Intelligent Driver Model, changes lane
when the next lane is clearly better (a MOBIL-style check), gives way to the bigger
road at junctions without signals, and stops for red. A full downstream link holds
it back, so queues spill back through junctions as they do on the road. Demand is
drawn once, so both rule sets meet exactly the same vehicles at the same moments.
Driving parameters, trip purposes and stop times are labelled urban assumptions.
"""

from __future__ import annotations

import bisect
import heapq
import json
import math
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .roads import Link, Network, _project, signal_sites

POIS = Path(__file__).resolve().parent.parent / "plans" / "osm" / "lahore_gulberg_pois.json"
MODES = ("fixed", "adaptive")
PERIODS = {"morning": 7.5 * 3600, "evening": 17.5 * 3600}       # when the simulated hour starts
DT = 1.0
SAMPLE = 4                      # seconds between replay samples
# kind: (share, length m, desired-speed factor, headway s, jam gap m, accel, comfortable decel, speed cap m/s)
KINDS = {
    "motorcycle": (0.65, 2.0, 1.05, 0.8, 1.0, 2.0, 2.5, 22.0),
    "car":        (0.25, 4.5, 1.00, 1.2, 2.0, 1.5, 2.0, 25.0),
    "rickshaw":   (0.05, 2.8, 0.85, 1.0, 1.5, 1.0, 2.0, 11.0),
    "bus":        (0.05, 11.0, 0.85, 1.5, 2.5, 0.9, 1.6, 16.0),
}
MAIN_GREEN, SIDE_GREEN, EVEN_GREEN = 60, 30, 45     # fixed plan: main road, side road, two equal roads
AMBER, ALL_RED = 3, 2
MIN_GREEN, MAX_STRETCH, GAP_OUT, DETECT = 10, 1.5, 3, 40.0

# why people drive: purpose -> (POI kinds, stop seconds (low, high), trip ends there)
# Assumptions, labelled: no published trip-purpose split for Gulberg was found.
PURPOSES = {
    "school run":      (("school", "college"), (60, 150), False),
    "university":      (("university", "college"), (0, 0), True),
    "fuel":            (("fuel",), (180, 360), False),
    "breakfast":       (("fast_food", "cafe", "bakery"), (240, 600), False),
    "pharmacy":        (("pharmacy", "clinic"), (120, 300), False),
    "hospital visit":  (("hospital", "clinic"), (0, 0), True),
    "shopping":        (("shop", "marketplace", "supermarket"), (600, 1500), False),
    "mall":            (("mall",), (0, 0), True),
    "takeaway":        (("fast_food", "restaurant", "cafe", "bakery"), (300, 720), False),
    "dinner out":      (("restaurant",), (0, 0), True),
    "bank":            (("bank",), (360, 720), False),
    "prayers":         (("place_of_worship",), (600, 900), False),
    "tuition pick-up": (("school", "college"), (90, 240), False),
}
# share of the trips that start or end inside the area which make each kind of stop
MIX = {
    "morning": {"school run": 0.18, "university": 0.04, "fuel": 0.04, "breakfast": 0.04, "pharmacy": 0.02,
                "hospital visit": 0.03, "bank": 0.01},
    "evening": {"shopping": 0.12, "mall": 0.05, "takeaway": 0.07, "dinner out": 0.03, "pharmacy": 0.05,
                "hospital visit": 0.02, "bank": 0.03, "fuel": 0.05, "prayers": 0.04, "tuition pick-up": 0.05},
}
THROUGH_FUEL = 0.03             # through traffic that stops for fuel on the way
# the stops made from the kerb lane; a fuel station, a bank or a shop has a forecourt or parking
KERB = {"school run", "tuition pick-up", "pharmacy", "takeaway"}


class Vehicle:
    __slots__ = ("id", "kind", "route", "ri", "lane", "pos", "v", "v0f", "T", "s0", "a", "b", "L", "cap",
                 "t0", "tin", "free", "stops", "stopped", "done", "samples", "next_lc", "acc", "wait", "still_since",
                 "errands", "ei", "hold_until", "parked", "dwell", "purpose", "stop_log")

    def __init__(self, vid, kind, route, t0, free, errands=(), purpose=""):
        _, L, v0f, T, s0, a, b, cap = KINDS[kind]
        self.id, self.kind, self.route, self.ri, self.lane = vid, kind, route, 0, 0
        self.pos, self.v, self.v0f, self.T, self.s0, self.a, self.b, self.L, self.cap = 0.0, 0.0, v0f, T, s0, a, b, L, cap
        self.t0, self.tin, self.free, self.stops, self.stopped, self.done = t0, None, free, 0, False, None
        self.samples, self.next_lc, self.acc, self.wait = [], 0, 0.0, 0
        self.still_since = None              # when it last came to a standstill (None while moving)
        self.errands, self.ei = list(errands), 0
        self.hold_until = None               # stopped for an errand until then
        self.parked = False                  # pulled off the road
        self.dwell, self.purpose = 0, purpose
        self.stop_log: list = []             # [start, end, label, poi]


@dataclass
class Signal:
    id: int
    nodes: list
    name: str
    phases: list                  # [[link ids], [link ids]] approaches per phase
    greens: list = field(default_factory=lambda: [EVEN_GREEN, EVEN_GREEN])
    phase: int = 0
    state: str = "green"          # green | amber | allred
    since: int = 0
    log: list = field(default_factory=list)   # (t, phase, state)
    last_detect: dict = field(default_factory=dict)

    @property
    def cycle(self) -> int:
        return sum(self.greens) + 2 * (AMBER + ALL_RED)


@dataclass
class Trip:
    t: int
    kind: str
    route: list
    free: float
    stops: list = field(default_factory=list)     # (route index, metres along that link, seconds | -1 = trip ends, label, off road, poi)
    purpose: str = ""


def _heading(lk: Link) -> float:
    (x0, y0), (x1, y1) = lk.pts[-2], lk.pts[-1]
    return math.atan2(y1 - y0, x1 - x0)


def build_signals(net: Network) -> list[Signal]:
    """One controller per junction; its approaches split into two phases by direction.
    The phase carrying the bigger road gets the long green."""
    sigs = []
    seen: dict[str, int] = {}
    for i, group in enumerate(signal_sites(net)):
        gset = set(group)
        appr = [lk for n in group for lk in net.into.get(n, []) if lk.a not in gset]
        if len(appr) < 2:
            continue
        # double the angle so opposite approaches (north/south) land together
        ang = [(_heading(lk) * 2) % (2 * math.pi) for lk in appr]
        ref = ang[0]
        groups = ([], [])
        for lk, a in zip(appr, ang):
            d = abs((a - ref + math.pi) % (2 * math.pi) - math.pi)
            groups[0 if d < math.pi / 2 else 1].append(lk.id)
        if not groups[1]:
            continue
        names = sorted({lk.name for lk in appr if lk.name})[:2]
        if not names:                     # unnamed approaches: name it after the nearest named road
            gx = sum(net.nodes[n][0] for n in group) / len(group)
            gy = sum(net.nodes[n][1] for n in group) / len(group)
            near = min((lk for lk in net.links if lk.name and lk.rank >= 3),       # a main road, not a back street
                       key=lambda lk: min(math.dist((gx, gy), p) for p in lk.pts))
            names = [f"near {near.name}"]
        name = " / ".join(names)
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:                # a divided road meets the same road twice, far enough apart
            name = f"{name} ({seen[name]})"
        r0 = max(net.links[l].rank for l in groups[0])
        r1 = max(net.links[l].rank for l in groups[1])
        greens = [MAIN_GREEN, SIDE_GREEN] if r0 > r1 else [SIDE_GREEN, MAIN_GREEN] if r1 > r0 else [EVEN_GREEN, EVEN_GREEN]
        sg = Signal(i, group, name, [groups[0], groups[1]], greens)
        # the signals are not coordinated: each one is somewhere in its cycle when the hour starts
        sg.since = -((i * 37) % greens[0])
        sigs.append(sg)
    return sigs


def expected_wait(sigs: list[Signal]) -> dict[int, float]:
    """Mean wait at a fixed signal for a driver arriving at random: red² / (2 × cycle)."""
    out = {}
    for s in sigs:
        for ph, ids in enumerate(s.phases):
            red = s.cycle - s.greens[ph]
            for lid in ids:
                out[lid] = red * red / (2 * s.cycle)
    return out


@lru_cache(maxsize=2)
def load_pois(path: str = str(POIS)) -> list[dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return raw["pois"]


def snap_pois(net: Network) -> list[dict]:
    """Each shop or amenity at the nearest point of a ground-level street within 150 m
    (not a flyover, an underpass, a slip road or a roundabout), in both directions of a
    two-way street."""
    xy = _project(*net.origin)
    cell = 100.0
    grid: dict[tuple, list] = {}
    for lk in net.links:
        if lk.layer != 0 or lk.roundabout or "_link" in lk.cls or lk.length < 30:
            continue
        for k, (p, q) in enumerate(zip(lk.pts, lk.pts[1:])):
            for gx in range(int(min(p[0], q[0]) // cell), int(max(p[0], q[0]) // cell) + 1):
                for gy in range(int(min(p[1], q[1]) // cell), int(max(p[1], q[1]) // cell) + 1):
                    grid.setdefault((gx, gy), []).append((lk, k))
    out = []
    for i, poi in enumerate(load_pois()):
        x, y = xy(poi["lat"], poi["lon"])
        best = None
        gx, gy = int(x // cell), int(y // cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for lk, k in grid.get((gx + dx, gy + dy), ()):
                    (ax, ay), (bx, by) = lk.pts[k], lk.pts[k + 1]
                    L2 = (bx - ax) ** 2 + (by - ay) ** 2 or 1e-9
                    u = max(0.0, min(1.0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L2))
                    d = math.dist((x, y), (ax + u * (bx - ax), ay + u * (by - ay)))
                    if best is None or d < best[0]:
                        along = sum(math.dist(p, q) for p, q in zip(lk.pts[:k + 1], lk.pts[1:k + 1])) + u * math.sqrt(L2)
                        best = (d, lk, along)
        if best is None or best[0] > 150:
            continue
        _, lk, along = best
        access = []
        twins = [o for o in _by_road(net).get(lk.road, ()) if o.length >= 30]
        for o in twins:
            pos = along if o.back == lk.back else o.length - along
            access.append((o.id, round(min(max(pos, 15.0), o.length - 10.0), 1)))
        kind = poi["shop"] if poi["shop"] in ("bakery", "supermarket") else poi["kind"]
        out.append({"i": i, "kind": kind, "name": poi["name"], "road": lk.name, "x": x, "y": y, "access": access})
    return out


def _by_road(net: Network) -> dict[int, list[Link]]:
    m = getattr(net, "_by_road", None)
    if m is None:
        m = {}
        for lk in net.links:
            m.setdefault(lk.road, []).append(lk)
        net._by_road = m
    return m


def make_demand(net: Network, seed: int = 7, minutes: int = 60, per_hour: int = 3000,
                period: str = "morning") -> list[Trip]:
    """Trips for a peak hour: through traffic between the area's edges on the big roads,
    trips into and out of the residential streets, and local trips, with the stops people
    make on the way. Drivers choose by free-flow time plus the expected wait at every
    signal, so a flyover or underpass that skips the lights is worth its detour, as it is
    to a Lahore driver; for an errand they pick the nearest of a few places that sell it."""
    assert period in PERIODS
    rng = random.Random(seed * 31 + 7 + (0 if period == "morning" else 1000))
    sigs = build_signals(net)
    wait = expected_wait(sigs)
    outs: dict[int, list[Link]] = {}
    ins: dict[int, list[Link]] = {}
    pieces: dict[int, set] = {}
    for lk in net.links:
        outs.setdefault(lk.a, []).append(lk)
        ins.setdefault(lk.b, []).append(lk)
        pieces.setdefault(lk.a, set()).add(lk.road)
        pieces.setdefault(lk.b, set()).add(lk.road)
    cost = lambda lk: lk.length / lk.speed + wait.get(lk.id, 0.0)
    # where the extract cuts a big road off, traffic enters and leaves the area
    cut = {n for n, r in pieces.items() if len(r) == 1}
    edge_in = sorted(n for n in cut if any(l.rank >= 3 for l in outs.get(n, ())))
    edge_out = sorted(n for n in cut if any(l.rank >= 3 for l in ins.get(n, ())))
    local = sorted({lk.a for lk in net.links if lk.cls in ("residential", "living_street", "unclassified")})
    zones = rng.sample(local, min(90, len(local)))
    pois = snap_pois(net)
    by_kind: dict[str, list[dict]] = {}
    for p in pois:
        by_kind.setdefault(p["kind"], []).append(p)
        if p["kind"] in ("bakery", "supermarket"):
            by_kind.setdefault("shop", []).append(p)
    fwd: dict[int, tuple[dict, dict]] = {}
    rev: dict[int, tuple[dict, dict]] = {}

    def tree(src, reverse=False):
        cache = rev if reverse else fwd
        if src not in cache:
            dist, step = {src: 0.0}, {}
            q = [(0.0, src)]
            while q:
                d, n = heapq.heappop(q)
                if d > dist.get(n, math.inf):
                    continue
                for lk in (ins if reverse else outs).get(n, ()):
                    m = lk.a if reverse else lk.b
                    nd = d + cost(lk)
                    if nd < dist.get(m, math.inf):
                        dist[m], step[m] = nd, lk
                        heapq.heappush(q, (nd, m))
            cache[src] = (dist, step)
        return cache[src]

    def path(o, d):
        """Link ids from node o to node d, or None."""
        if o == d:
            return []
        if o in fwd or d not in rev:
            dist, prev = tree(o)
            if d not in prev:
                return None
            route, n = [], d
            while n != o:
                lk = prev[n]
                route.append(lk.id)
                n = lk.a
            return route[::-1]
        dist, nxt = tree(d, reverse=True)
        if o not in nxt:
            return None
        route, n = [], o
        while n != d:
            lk = nxt[n]
            route.append(lk.id)
            n = lk.b
        return route

    def errand(o, d, purpose):
        """Route o -> a place for this purpose (-> d), the stop, or None."""
        kinds, (lo, hi), ends = PURPOSES[purpose]
        cands = [p for k in kinds for p in by_kind.get(k, ())]
        if not cands:
            return None
        best = None
        for p in rng.sample(cands, min(4, len(cands))):
            lid, pos = rng.choice(p["access"])
            lk = net.links[lid]
            a, b = tree(o)[0].get(lk.a), 0.0 if ends else tree(d, reverse=True)[0].get(lk.b)
            if a is None or b is None:
                continue
            if best is None or a + b < best[0]:
                best = (a + b, p, lk, pos)
        if best is None:
            return None
        _, p, lk, pos = best
        first = path(o, lk.a)
        rest = [] if ends else path(lk.b, d)
        if first is None or rest is None:
            return None
        route = first + [lk.id] + rest
        dwell = -1 if ends else rng.randint(lo, hi)
        off = ends or purpose not in KERB or dwell > 300 or lk.lanes == 1   # park off the road
        return route, (len(first), pos, dwell, purpose, off, p["i"])

    mix = MIX[period]
    trips: list[Trip] = []
    t = 0.0
    while True:
        # the peak builds: 70% of the hourly rate at the start, 115% at the end
        rate = per_hour * (0.7 + 0.45 * t / (minutes * 60)) / 3600
        t += rng.expovariate(rate)
        if t >= minutes * 60:
            break
        u = rng.random()
        if u < 0.5:
            o, d = rng.choice(edge_in), rng.choice(edge_out)
            through = True
        else:
            through = False
            if u < 0.8:
                o, d = (rng.choice(edge_in), rng.choice(zones)) if rng.random() < 0.6 else (rng.choice(zones), rng.choice(edge_out))
            else:
                o, d = rng.choice(zones), rng.choice(zones)
        if o == d:
            continue
        kind = rng.choices(list(KINDS), [k[0] for k in KINDS.values()])[0]
        purpose, stops, route = ("through" if through else "home" if period == "evening" else "work"), [], None
        x = rng.random()
        if through:
            want = "fuel" if kind != "bus" and x < THROUGH_FUEL else None
        else:
            want = None
            acc = 0.0
            for name, share in mix.items():
                acc += share
                if x < acc:
                    want = name
                    break
            if kind == "bus":                       # wagons and buses run their route
                want = None
        if want:
            got = errand(o, d, want)
            if got:
                route, stop = got
                stops.append(stop)
                purpose = want
        if route is None:
            route = path(o, d)
            if route is None:
                continue
        if len(route) < 2:
            continue
        # rickshaws drop and pick up passengers anywhere; wagons stop every 700-1,000 m
        if kind in ("rickshaw", "bus"):
            gap = rng.uniform(700, 1000) if kind == "bus" else rng.uniform(900, 2500)
            run = 0.0
            for ri, lid in enumerate(route):
                lk = net.links[lid]
                run += lk.length
                if run >= gap and lk.layer == 0 and lk.length >= 40 and lk.rank <= 5 and ri not in {s[0] for s in stops}:
                    stops.append((ri, round(rng.uniform(15, lk.length - 15), 1),
                                  rng.randint(20, 45) if kind == "bus" else rng.randint(15, 40),
                                  "passenger stop" if kind == "bus" else "passengers", False, -1))
                    run, gap = 0.0, (rng.uniform(700, 1000) if kind == "bus" else rng.uniform(900, 2500))
            if kind == "bus":
                purpose = "wagon route"
        stops.sort(key=lambda s: (s[0], s[1]))
        if any(s[2] < 0 for s in stops):           # the trip ends at the place: nothing after it
            end = next(s for s in stops if s[2] < 0)
            stops = [s for s in stops if (s[0], s[1]) <= (end[0], end[1])]
            route = route[:end[0] + 1]
        free = sum(net.links[lid].length / net.links[lid].speed for lid in route)   # the delay baseline: no waits
        if stops and stops[-1][2] < 0:
            lk = net.links[route[-1]]
            free -= (lk.length - stops[-1][1]) / lk.speed
        trips.append(Trip(int(t), kind, route, free, stops, purpose))
    return trips


class TrafficSim:
    def __init__(self, net: Network, trips: list[Trip], mode: str, minutes: int = 60):
        assert mode in MODES
        self.net, self.trips, self.mode, self.T = net, trips, mode, minutes * 60 + 900   # 15 min to clear
        self.links = net.links
        self.lanes = [[[] for _ in range(lk.lanes)] for lk in self.links]
        self.signals = build_signals(net)
        self.sig_of: dict[int, tuple[Signal, int]] = {}       # approach link -> (signal, phase)
        for s in self.signals:
            for ph, ids in enumerate(s.phases):
                for lid in ids:
                    self.sig_of[lid] = (s, ph)
        self.max_rank_into = {n: max(l.rank for l in ls) for n, ls in net.into.items()}
        self.vehicles: list[Vehicle] = []
        self.active: list[Vehicle] = []
        self.parked: list[Vehicle] = []                       # pulled off the road for an errand
        self.waiting: dict[int, list[Vehicle]] = {}           # origin link -> vehicles that could not enter yet
        self.t = 0
        self.junction_delay: dict[int, float] = {}            # signal id -> vehicle-seconds stopped on approaches
        self.node_delay: dict[int, float] = {}                # node -> vehicle-seconds stopped within 60 m
        self.queue_max: dict[int, int] = {}
        # per minute: [t, on the road, mean speed km/h, waiting to enter, stopped or parked for an errand]
        self.series: list = []

    # -------------------------------------------------------------- signals
    def green(self, lid: int) -> bool:
        s = self.sig_of.get(lid)
        if s is None:
            return True
        sig, ph = s
        return sig.phase == ph and sig.state == "green"

    def _detect(self, sig: Signal, ph: int) -> bool:
        """A loop detector DETECT m upstream on any approach of phase ph sees a vehicle."""
        for lid in sig.phases[ph]:
            lk = self.links[lid]
            for lane in self.lanes[lid]:
                for v in lane:
                    if lk.length - v.pos <= DETECT:
                        return True
                    break                                    # lanes are front-first: the rest are further back
        return False

    def tick_signals(self, t: int) -> None:
        for s in self.signals:
            el = t - s.since
            if s.state == "amber":
                if el >= AMBER:
                    s.state, s.since = "allred", t
                    s.log.append((t, s.phase, "allred"))
                continue
            if s.state == "allred":
                if el >= ALL_RED:
                    s.phase, s.state, s.since = 1 - s.phase, "green", t
                    s.log.append((t, s.phase, "green"))
                continue
            if self.mode == "fixed":
                end = el >= s.greens[s.phase]
            else:
                if self._detect(s, s.phase):
                    s.last_detect[s.phase] = t
                gap = t - s.last_detect.get(s.phase, s.since)
                other = self._detect(s, 1 - s.phase)
                cap = round(s.greens[s.phase] * MAX_STRETCH)
                end = el >= cap and other or (el >= MIN_GREEN and gap >= GAP_OUT and other)
            if end:
                s.state, s.since = "amber", t
                s.log.append((t, s.phase, "amber"))

    # -------------------------------------------------------------- driving
    def _idm(self, v: Vehicle, v0: float, gap: float, vl: float) -> float:
        sstar = v.s0 + max(0.0, v.v * v.T + v.v * (v.v - vl) / (2 * math.sqrt(v.a * v.b)))
        gap = max(gap, 0.1)
        return v.a * (1 - (v.v / max(v0, 0.1)) ** 4 - (sstar / gap) ** 2)

    def _ahead(self, v: Vehicle, lk: Link, lane: list, idx: int) -> tuple[float, float]:
        gap, vl = self._ahead_road(v, lk, lane, idx)
        # an errand: brake for the place as if for a stop line
        if v.ei < len(v.errands):
            ri, pos = v.errands[v.ei][0], v.errands[v.ei][1]
            if ri == v.ri:
                g = pos - v.pos
            elif ri == v.ri + 1:
                g = lk.length - v.pos + pos
            else:
                g = math.inf
            if g < gap:
                return max(g, 0.1), 0.0
        return gap, vl

    def _ahead_road(self, v: Vehicle, lk: Link, lane: list, idx: int) -> tuple[float, float]:
        """Gap to, and speed of, whatever is in front: a vehicle, a stop line, or the queue on the next link."""
        if idx > 0:
            lead = lane[idx - 1]
            return lead.pos - lead.L - v.pos, lead.v
        to_end = lk.length - v.pos
        if v.ri + 1 >= len(v.route):
            return to_end + 50.0, v.v                       # the trip ends: drive off the map
        if to_end > 80:
            return to_end + 50.0, v.v
        # red, amber or all-red at a signal: stop at the line (amber only if it can stop comfortably)
        if not self.green(lk.id):
            sig = self.sig_of[lk.id][0]
            if sig.state != "amber" or v.v * v.v / (2 * v.b) < to_end:
                return to_end - 1.0, 0.0
        elif lk.id not in self.sig_of and lk.rank < self.max_rank_into.get(lk.b, 0) and not lk.roundabout:
            # no signal: give way to the bigger road if something is coming on it
            for other in self.net.into.get(lk.b, ()):
                if other.rank > lk.rank and other.id != lk.id:
                    for ln in self.lanes[other.id]:
                        if ln and other.length - ln[0].pos < 25 and ln[0].v > 1.0:
                            return to_end - 1.0, 0.0
        # the queue ahead, looking along the route past short links: OSM splits roads into
        # stubs a metre long, and stopping at the end of an empty stub froze a whole avenue
        dist, lane, ri = to_end, v.lane, v.ri + 1
        while ri < len(v.route) and dist < 100:
            nl = self.links[v.route[ri]]
            lane = min(lane, nl.lanes - 1)
            lane2 = self.lanes[nl.id][lane]
            if lane2:
                rear = lane2[-1]
                return dist + rear.pos - rear.L, rear.v
            if ri > v.ri + 1 and not self.green(self.links[v.route[ri - 1]].id):
                return dist - 1.0, 0.0              # a red light at the end of a stub ahead
            dist += nl.length
            ri += 1
        return dist + 50.0, v.v

    def _insert(self, veh: Vehicle, lid: int, lane: int) -> None:
        ln = self.lanes[lid][lane]
        keys = [-x.pos for x in ln]
        ln.insert(bisect.bisect_left(keys, -veh.pos), veh)

    def _start_errand(self, veh: Vehicle, t: int) -> None:
        ri, pos, dwell, label, off, poi = veh.errands[veh.ei]
        lk = self.links[veh.route[veh.ri]]
        veh.v, veh.acc, veh.still_since = 0.0, 0.0, None
        if dwell < 0:                                  # arrived: parks at the mall, the hospital, the restaurant
            self.lanes[lk.id][veh.lane].remove(veh)
            self.active.remove(veh)
            veh.stop_log.append([t, None, label, poi])
            veh.done, veh.ei = t, veh.ei + 1
            return
        veh.hold_until = t + dwell
        veh.stop_log.append([t, t + dwell, label, poi])
        if off:
            self.lanes[lk.id][veh.lane].remove(veh)
            self.active.remove(veh)
            veh.parked = True
            self.parked.append(veh)

    def _release(self, t: int) -> None:
        for veh in self.active:
            if veh.hold_until is not None and t >= veh.hold_until:
                veh.hold_until, veh.ei = None, veh.ei + 1
                veh.dwell += t - veh.stop_log[-1][0]
        back = []
        for veh in self.parked:
            if t < veh.hold_until:
                continue
            # pull back out into the kerb lane when there is room
            lk = self.links[veh.route[veh.ri]]
            lane = lk.lanes - 1
            ln = self.lanes[lk.id][lane]
            keys = [-x.pos for x in ln]
            k = bisect.bisect_left(keys, -veh.pos)
            lead = ln[k - 1] if k > 0 else None
            foll = ln[k] if k < len(ln) else None
            if lead and lead.pos - lead.L - veh.pos < veh.s0 + 1:
                continue
            if foll and veh.pos - veh.L - foll.pos < foll.s0 + 2 + foll.v * 1.5:
                continue
            veh.lane, veh.parked = lane, False
            ln.insert(k, veh)
            veh.stop_log[-1][1] = t
            veh.dwell += t - veh.stop_log[-1][0]
            veh.hold_until, veh.ei = None, veh.ei + 1
            back.append(veh)
        for veh in back:
            self.parked.remove(veh)
            self.active.append(veh)

    def step(self, t: int) -> None:
        self.tick_signals(t)
        self._release(t)
        # spawn
        while self._next_trip < len(self.trips) and self.trips[self._next_trip].t <= t:
            tr = self.trips[self._next_trip]
            self._next_trip += 1
            veh = Vehicle(len(self.vehicles), tr.kind, tr.route, tr.t, tr.free, tr.stops, tr.purpose)
            self.vehicles.append(veh)
            self.waiting.setdefault(tr.route[0], []).append(veh)
        for lid, q in list(self.waiting.items()):
            lk = self.links[lid]
            while q:
                veh = q[0]
                best = max(range(lk.lanes), key=lambda i: (self.lanes[lid][i][-1].pos - self.lanes[lid][i][-1].L) if self.lanes[lid][i] else 1e9)
                ln = self.lanes[lid][best]
                if ln and ln[-1].pos - ln[-1].L < veh.L + veh.s0 + 1:
                    break
                q.pop(0)
                veh.lane, veh.tin, veh.v = best, t, min(lk.speed * 0.5, 6.0)
                ln.append(veh)
                self.active.append(veh)
            if not q:
                del self.waiting[lid]
        # accelerations (computed for everyone first, applied after), on the links that have anyone on them
        for lid in {veh.route[veh.ri] for veh in self.active}:
            lanes = self.lanes[lid]
            lk = self.links[lid]
            v0l = lk.speed
            for lane in lanes:
                for idx, veh in enumerate(lane):
                    if veh.hold_until is not None:
                        veh.acc = 0.0
                        continue
                    gap, vl = self._ahead(veh, lk, lane, idx)
                    veh.acc = self._idm(veh, min(v0l * veh.v0f, veh.cap), gap, vl)
        # move
        moved, arrived = [], []
        for veh in self.active:
            if veh.hold_until is not None:              # stopped at the kerb for an errand
                veh.v = 0.0
                continue
            nv = max(0.0, veh.v + veh.acc * DT)
            veh.pos += (veh.v + nv) / 2 * DT
            if nv < 0.5:
                if veh.still_since is None:
                    veh.still_since = t
                veh.wait += 1
                if not veh.stopped and veh.v >= 0.5:
                    veh.stops += 1
                veh.stopped = True
            elif nv > 2.0:
                veh.stopped = False
            if nv >= 0.5:
                veh.still_since = None
            veh.v = nv
            lk = self.links[veh.route[veh.ri]]
            if veh.ei < len(veh.errands):
                ri, pos = veh.errands[veh.ei][0], veh.errands[veh.ei][1]
                # there, or stuck within 25 m of it (behind someone else's stop): stop here
                if ri == veh.ri and (pos - veh.pos < veh.s0 + 6 and (nv < 0.5 or veh.pos > pos)
                                     or pos - veh.pos < 25 and nv < 0.5):
                    arrived.append(veh)
                    continue
            if nv < 0.5 and lk.length - veh.pos < 60:
                self.node_delay[lk.b] = self.node_delay.get(lk.b, 0) + 1
                s = self.sig_of.get(lk.id)
                if s:
                    self.junction_delay[s[0].id] = self.junction_delay.get(s[0].id, 0) + 1
            if veh.pos >= lk.length:
                moved.append(veh)
        for veh in arrived:
            self._start_errand(veh, t)
        for veh in moved:
            lk = self.links[veh.route[veh.ri]]
            lane = self.lanes[lk.id][veh.lane]
            lane.remove(veh)
            over = veh.pos - lk.length
            veh.ri += 1
            if veh.ri >= len(veh.route):
                veh.done = t
                self.active.remove(veh)
                continue
            nxt = self.links[veh.route[veh.ri]]
            veh.lane = min(veh.lane, nxt.lanes - 1)
            veh.pos = min(over, nxt.length - 0.1)
            self._insert(veh, nxt.id, veh.lane)
            while veh.ei < len(veh.errands) and veh.errands[veh.ei][0] < veh.ri:
                veh.ei += 1                       # drove past it (rare): carry on
        # lane changes, a few vehicles each second
        for veh in self.active:
            if t < veh.next_lc or veh.hold_until is not None:
                continue
            veh.next_lc = t + 3
            lk = self.links[veh.route[veh.ri]]
            if lk.lanes < 2 or lk.length - veh.pos < 30:
                continue
            # heading for a stop on this link: move over to the kerb lane, whatever it costs
            seeking = (veh.ei < len(veh.errands) and veh.errands[veh.ei][0] == veh.ri
                       and veh.errands[veh.ei][1] - veh.pos < 200 and veh.lane < lk.lanes - 1)
            lane = self.lanes[lk.id][veh.lane]
            idx = lane.index(veh)
            cur = veh.acc
            best, gain = None, (-math.inf if seeking else 0.1 if veh.kind == "motorcycle" else 0.3)
            for nl in ((veh.lane + 1,) if seeking else (veh.lane - 1, veh.lane + 1)):
                if not 0 <= nl < lk.lanes:
                    continue
                other = self.lanes[lk.id][nl]
                keys = [-x.pos for x in other]
                k = bisect.bisect_left(keys, -veh.pos)
                lead = other[k - 1] if k > 0 else None
                foll = other[k] if k < len(other) else None
                if lead and lead.pos - lead.L - veh.pos < veh.s0:
                    continue
                if foll and veh.pos - veh.L - foll.pos < foll.s0:
                    continue
                if foll:
                    fgap = veh.pos - veh.L - foll.pos
                    if self._idm(foll, lk.speed, fgap, veh.v) < -3.0:
                        continue
                gap, vl = ((lead.pos - lead.L - veh.pos, lead.v) if lead else (lk.length - veh.pos + 50, veh.v))
                a_new = self._idm(veh, min(lk.speed * veh.v0f, veh.cap), gap, vl)
                if a_new - cur > gain:
                    best, gain = (nl, k), a_new - cur
            if best:
                nl, k = best
                lane.pop(idx)
                veh.lane = nl
                self.lanes[lk.id][nl].insert(k, veh)
        if t % 60 == 0:
            n = len(self.active)
            held = sum(1 for v in self.active if v.hold_until is not None) + len(self.parked)
            self.series.append([t, n, round(3.6 * sum(v.v for v in self.active) / n, 1) if n else 0.0,
                                sum(len(q) for q in self.waiting.values()), held])
        if t % SAMPLE == 0:
            for veh in self.active:
                veh.samples.append((t, veh.ri, round(veh.pos, 1), veh.lane))
            for veh in self.parked:
                veh.samples.append((t, veh.ri, round(veh.pos, 1), -1))     # lane -1: off the road
            for s in self.signals:
                q = sum(1 for ph in s.phases for lid in ph for ln in self.lanes[lid] for v in ln
                        if v.v < 0.5 and v.hold_until is None)
                if q > self.queue_max.get(s.id, 0):
                    self.queue_max[s.id] = q

    def run(self) -> "TrafficSim":
        self._next_trip = 0
        for t in range(self.T):
            self.t = t
            self.step(t)
        return self

    def metrics(self) -> dict:
        done = [v for v in self.vehicles if v.done is not None]
        tt = [v.done - v.t0 - v.dwell for v in done]          # driving time: the errand itself is not delay
        delay = [v.done - v.t0 - v.dwell - v.free for v in done]
        dist = [sum(self.links[l].length for l in v.route) for v in done]

        def med(xs):
            xs = sorted(xs)
            return round(xs[len(xs) // 2], 1) if xs else None
        sid = {s.id: s for s in self.signals}
        hot = sorted(((d, sid[i].name) for i, d in self.junction_delay.items() if i in sid), reverse=True)
        purposes: dict[str, int] = {}
        for v in self.vehicles:
            purposes[v.purpose] = purposes.get(v.purpose, 0) + 1
        logs = [e for v in self.vehicles for e in v.stop_log]
        return {
            "trips": len(self.vehicles), "completed": len(done), "still_driving": len(self.active) + len(self.parked),
            # a red light holds a vehicle for a minute or so; five minutes without moving is a gridlock
            "gridlocked": sum(1 for v in self.active if v.still_since is not None and self.t - v.still_since > 300),
            "not_yet_entered": sum(len(q) for q in self.waiting.values()),
            "travel_time_median_s": med(tt), "delay_median_s": med(delay),
            "delay_mean_s": round(sum(delay) / len(delay), 1) if delay else None,
            "delay_total_veh_h": round(sum(delay) / 3600, 1),
            "stops_mean": round(sum(v.stops for v in done) / len(done), 2) if done else None,
            "speed_mean_kmh": round(3.6 * sum(dist) / sum(tt), 1) if tt else None,
            "signals": len(self.signals),
            "signal_delay_veh_h": round(sum(self.junction_delay.values()) / 3600, 1),
            "worst_junctions": [[n, round(d / 3600, 2)] for d, n in hot[:8]],
            "errand_stops": sum(1 for e in logs if e[3] >= 0),
            "passenger_stops": sum(1 for e in logs if e[3] < 0),
            "ended_at_a_place": sum(1 for e in logs if e[1] is None),
            "purposes": dict(sorted(purposes.items(), key=lambda kv: -kv[1])),
        }
