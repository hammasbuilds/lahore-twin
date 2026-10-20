"""Vehicles driving Lahore's real roads for a morning peak, under two signal rule sets.

* ``fixed``    — what most Lahore signals do: a fixed cycle, the same split all day.
* ``adaptive`` — the same junctions with loop detectors 40 m back on every approach:
  hold the green while cars keep arriving, end it on a gap, never past a maximum.

Each vehicle follows the one ahead with the Intelligent Driver Model, changes lane
when the next lane is clearly better (a MOBIL-style check), gives way to the bigger
road at junctions without signals, and stops for red. A full downstream link holds
it back, so queues spill back through junctions as they do on the road. Demand is
drawn once, so both rule sets meet exactly the same vehicles at the same moments.
Driving parameters are urban assumptions; the published IDM values are for highways.
"""

from __future__ import annotations

import bisect
import heapq
import math
import random
from dataclasses import dataclass, field

from .roads import Link, Network, junctions, load, signal_sites

MODES = ("fixed", "adaptive")
DT = 1.0
SAMPLE = 4                      # seconds between replay samples
# kind: (share, length m, desired-speed factor, headway s, jam gap m, accel, comfortable decel, speed cap m/s)
KINDS = {
    "motorcycle": (0.65, 2.0, 1.05, 0.8, 1.0, 2.0, 2.5, 22.0),
    "car":        (0.25, 4.5, 1.00, 1.2, 2.0, 1.5, 2.0, 25.0),
    "rickshaw":   (0.05, 2.8, 0.85, 1.0, 1.5, 1.0, 2.0, 11.0),
    "bus":        (0.05, 11.0, 0.85, 1.5, 2.5, 0.9, 1.6, 16.0),
}
FIXED_GREEN, AMBER = 32, 3
MIN_GREEN, MAX_GREEN, GAP_OUT, DETECT = 8, 55, 3, 40.0


class Vehicle:
    __slots__ = ("id", "kind", "route", "ri", "lane", "pos", "v", "v0f", "T", "s0", "a", "b", "L", "cap",
                 "t0", "tin", "free", "stops", "stopped", "done", "samples", "next_lc", "acc", "wait", "still_since")

    def __init__(self, vid, kind, route, t0, free):
        _, L, v0f, T, s0, a, b, cap = KINDS[kind]
        self.id, self.kind, self.route, self.ri, self.lane = vid, kind, route, 0, 0
        self.pos, self.v, self.v0f, self.T, self.s0, self.a, self.b, self.L, self.cap = 0.0, 0.0, v0f, T, s0, a, b, L, cap
        self.t0, self.tin, self.free, self.stops, self.stopped, self.done = t0, None, free, 0, False, None
        self.samples, self.next_lc, self.acc, self.wait = [], 0, 0.0, 0
        self.still_since = None              # when it last came to a standstill (None while moving)


@dataclass
class Signal:
    id: int
    nodes: list
    name: str
    phases: list                  # [[link ids], [link ids]] approaches per phase
    phase: int = 0
    state: str = "green"          # green | amber
    since: int = 0
    log: list = field(default_factory=list)   # (t, phase, state)
    last_detect: dict = field(default_factory=dict)


@dataclass
class Trip:
    t: int
    kind: str
    route: list
    free: float


def _heading(lk: Link) -> float:
    (x0, y0), (x1, y1) = lk.pts[-2], lk.pts[-1]
    return math.atan2(y1 - y0, x1 - x0)


def build_signals(net: Network) -> list[Signal]:
    """One controller per junction; its approaches split into two phases by direction."""
    sigs = []
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
        sigs.append(Signal(i, group, " / ".join(names), [groups[0], groups[1]]))
    return sigs


def make_demand(net: Network, seed: int = 7, minutes: int = 60, per_hour: int = 3000) -> list[Trip]:
    """Trips for a morning peak: through traffic between the area's edges on the big roads,
    trips into and out of the residential streets, and local trips; routed by free-flow time."""
    rng = random.Random(seed * 31 + 7)
    outs: dict[int, list[Link]] = {}
    pieces: dict[int, set] = {}
    for lk in net.links:
        outs.setdefault(lk.a, []).append(lk)
        pieces.setdefault(lk.a, set()).add(lk.road)
        pieces.setdefault(lk.b, set()).add(lk.road)
    # where the extract cuts a big road off, traffic enters and leaves the area
    cut = {n for n, r in pieces.items() if len(r) == 1}
    edge_in = sorted(n for n in cut if any(l.rank >= 3 for l in outs.get(n, ())))
    edge_out = sorted(n for n in cut if any(l.rank >= 3 for l in net.into.get(n, ())))
    local = sorted({lk.a for lk in net.links if lk.cls in ("residential", "living_street", "unclassified")})
    zones = rng.sample(local, min(90, len(local)))
    origins = sorted(set(edge_in)) + zones
    dests = sorted(set(edge_out)) + zones
    trees: dict[int, tuple[dict, dict]] = {}

    def tree(src):
        if src not in trees:
            dist, prev = {src: 0.0}, {}
            q = [(0.0, src)]
            while q:
                d, n = heapq.heappop(q)
                if d > dist.get(n, math.inf):
                    continue
                for lk in outs.get(n, ()):
                    nd = d + lk.length / lk.speed
                    if nd < dist.get(lk.b, math.inf):
                        dist[lk.b], prev[lk.b] = nd, lk
                        heapq.heappush(q, (nd, lk.b))
            trees[src] = (dist, prev)
        return trees[src]

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
        elif u < 0.8:
            o, d = (rng.choice(edge_in), rng.choice(zones)) if rng.random() < 0.6 else (rng.choice(zones), rng.choice(edge_out))
        else:
            o, d = rng.choice(zones), rng.choice(zones)
        if o == d:
            continue
        dist, prev = tree(o)
        if d not in prev:
            continue
        route, n = [], d
        while n != o:
            lk = prev[n]
            route.append(lk.id)
            n = lk.a
        route.reverse()
        if len(route) < 2:
            continue
        kind = rng.choices(list(KINDS), [k[0] for k in KINDS.values()])[0]
        trips.append(Trip(int(t), kind, route, dist[d]))
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
        self.waiting: dict[int, list[Vehicle]] = {}           # origin link -> vehicles that could not enter yet
        self.t = 0
        self.junction_delay: dict[int, float] = {}            # signal id -> vehicle-seconds stopped on approaches
        self.node_delay: dict[int, float] = {}                # node -> vehicle-seconds stopped within 60 m
        self.queue_max: dict[int, int] = {}
        self.series: list = []                                # per minute: [t, on the road, mean speed km/h, waiting to enter]

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
                    s.phase, s.state, s.since = 1 - s.phase, "green", t
                    s.log.append((t, s.phase, "green"))
                continue
            if self.mode == "fixed":
                end = el >= FIXED_GREEN
            else:
                if self._detect(s, s.phase):
                    s.last_detect[s.phase] = t
                gap = t - s.last_detect.get(s.phase, s.since)
                other = self._detect(s, 1 - s.phase)
                end = el >= MAX_GREEN and other or (el >= MIN_GREEN and gap >= GAP_OUT and other)
            if end:
                s.state, s.since = "amber", t
                s.log.append((t, s.phase, "amber"))

    # -------------------------------------------------------------- driving
    def _idm(self, v: Vehicle, v0: float, gap: float, vl: float) -> float:
        sstar = v.s0 + max(0.0, v.v * v.T + v.v * (v.v - vl) / (2 * math.sqrt(v.a * v.b)))
        gap = max(gap, 0.1)
        return v.a * (1 - (v.v / max(v0, 0.1)) ** 4 - (sstar / gap) ** 2)

    def _ahead(self, v: Vehicle, lk: Link, lane: list, idx: int) -> tuple[float, float]:
        """Gap to, and speed of, whatever is in front: a vehicle, a stop line, or the queue on the next link."""
        if idx > 0:
            lead = lane[idx - 1]
            return lead.pos - lead.L - v.pos, lead.v
        to_end = lk.length - v.pos
        if v.ri + 1 >= len(v.route):
            return to_end + 50.0, v.v                       # the trip ends: drive off the map
        if to_end > 80:
            return to_end + 50.0, v.v
        nxt = self.links[v.route[v.ri + 1]]
        # red or amber at a signal: stop at the line (amber only if it can stop comfortably)
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

    def step(self, t: int) -> None:
        self.tick_signals(t)
        # spawn
        while self._next_trip < len(self.trips) and self.trips[self._next_trip].t <= t:
            tr = self.trips[self._next_trip]
            self._next_trip += 1
            veh = Vehicle(len(self.vehicles), tr.kind, tr.route, tr.t, tr.free)
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
        # accelerations (computed for everyone first, applied after)
        for lid, lanes in enumerate(self.lanes):
            lk = self.links[lid]
            v0l = lk.speed
            for lane in lanes:
                for idx, veh in enumerate(lane):
                    gap, vl = self._ahead(veh, lk, lane, idx)
                    veh.acc = self._idm(veh, min(v0l * veh.v0f, veh.cap), gap, vl)
        # move
        moved = []
        for veh in self.active:
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
            if nv < 0.5 and lk.length - veh.pos < 60:
                self.node_delay[lk.b] = self.node_delay.get(lk.b, 0) + 1
                s = self.sig_of.get(lk.id)
                if s:
                    self.junction_delay[s[0].id] = self.junction_delay.get(s[0].id, 0) + 1
            if veh.pos >= lk.length:
                moved.append(veh)
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
            ln = self.lanes[nxt.id][veh.lane]
            keys = [-x.pos for x in ln]
            ln.insert(bisect.bisect_left(keys, -veh.pos), veh)
        # lane changes, a few vehicles each second
        for veh in self.active:
            if t < veh.next_lc:
                continue
            veh.next_lc = t + 3
            lk = self.links[veh.route[veh.ri]]
            if lk.lanes < 2 or lk.length - veh.pos < 30:
                continue
            lane = self.lanes[lk.id][veh.lane]
            idx = lane.index(veh)
            cur = veh.acc
            best, gain = None, (0.1 if veh.kind == "motorcycle" else 0.3)
            for nl in (veh.lane - 1, veh.lane + 1):
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
            self.series.append([t, n, round(3.6 * sum(v.v for v in self.active) / n, 1) if n else 0.0,
                                sum(len(q) for q in self.waiting.values())])
        if t % SAMPLE == 0:
            for veh in self.active:
                veh.samples.append((t, veh.ri, round(veh.pos, 1), veh.lane))
            for s in self.signals:
                q = sum(1 for ph in s.phases for lid in ph for ln in self.lanes[lid] for v in ln if v.v < 0.5)
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
        tt = [v.done - v.t0 for v in done]
        delay = [v.done - v.t0 - v.free for v in done]
        dist = [sum(self.links[l].length for l in v.route) for v in done]
        def med(xs):
            xs = sorted(xs)
            return round(xs[len(xs) // 2], 1) if xs else None
        hot = sorted(((d, self.signals[i].name if i < len(self.signals) else str(i)) for i, d in self.junction_delay.items()), reverse=True)
        return {
            "trips": len(self.vehicles), "completed": len(done), "still_driving": len(self.active),
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
        }
