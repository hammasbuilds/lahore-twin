"""Phase 6: city systems on the real roads - smog first.

Smog (a November evening). PM2.5 at street level on a 100 m grid, every minute:

    C(cell, t) = background(t) + traffic(cell, t)

* ``background`` - the regional haze (crop burning, industry, dust) with the evening inversion
  pressing it down: it climbs from 17:30 as the mixed layer collapses.
* ``traffic`` - what the traffic module's own vehicles emit on each link that minute (exhaust per
  vehicle-km by kind, plus idling in queues), spread from the road with a Gaussian of 250 m and
  scaled so that, across the cells near roads at the peak, traffic is 36% of the total - the last published
  source apportionment for Lahore (2010 data; dated, and labelled so).

Sensing. Today: one official monitor. Connected: 25 low-cost sensors - 15 at real schools,
hospitals and colleges (OpenStreetMap), 10 on poles at signalised junctions of the main roads -
each with its own gain error and noise, corrected network-wide against the sensor beside the
official monitor. Today's map is the monitor's one number everywhere; Connected's is a land-use
regression - the readings against the traffic the signals' loop detectors count - with its
residuals interpolated. Acting: where the low-cost network finds the worst hotspot, the signals within 400 m
switch to adaptive control to cut idling, and the same trips are run again.

Emission factors, the background curve and the sensor errors are assumptions, labelled.
"""

from __future__ import annotations

import math
import random

from .junctions import Movements
from .roads import Network, load
from .traffic_sim import TrafficSim, build_signals, make_demand, snap_pois

CELL = 100.0
SIGMA = 250.0                   # street-level mixing; 150 m gave peaks twice the highest hourly readings reported
REACH = 3 * SIGMA
TRAFFIC_SHARE = 0.36
# PM2.5 exhaust, g per vehicle-km, and idling, g per vehicle-minute (assumptions; relative sizes matter)
EF_KM = {"motorcycle": 0.06, "car": 0.03, "rickshaw": 0.20, "bus": 0.60, "ambulance": 0.10}
EF_IDLE = {"motorcycle": 0.02, "car": 0.01, "rickshaw": 0.06, "bus": 0.20, "ambulance": 0.03}


def background(minute: int, minutes: int) -> float:
    """Regional PM2.5, µg/m³: 95 at 17:30, rising as the inversion sets in, to 150 by the end."""
    f = min(1.0, minute / max(1, minutes))
    return 95 + 55 * f * f * (3 - 2 * f)


class Emissions:
    """Hooks a TrafficSim: grams of PM2.5 per link per minute."""

    def __init__(self, sim: TrafficSim):
        self.sim = sim
        self.g: dict[int, dict[int, float]] = {}       # minute -> link -> grams
        self.counts: dict[int, dict[int, float]] = {}  # minute -> approach link -> vehicle-seconds (loop detectors)
        step = sim.step

        def watched(t):
            step(t)
            m = t // 60
            bucket = self.g.setdefault(m, {})
            for v in sim.active:
                if v.hold_until is not None:
                    continue
                lid = v.route[v.ri]
                grams = (EF_KM[v.kind] * v.v / 1000) if v.v >= 0.5 else EF_IDLE[v.kind] / 60
                bucket[lid] = bucket.get(lid, 0.0) + grams
                if lid in sim.sig_of:          # only signal approaches have detectors
                    cnt = self.counts.setdefault(m, {})
                    cnt[lid] = cnt.get(lid, 0.0) + 1.0
        sim.step = watched


class Grid:
    """The area on a 100 m grid, and each link's spread onto the cells near it."""

    def __init__(self, net: Network):
        x0, y0, x1, y1 = net.bbox
        self.x0, self.y0 = x0, y0
        self.nx, self.ny = int((x1 - x0) // CELL) + 1, int((y1 - y0) // CELL) + 1
        self.kernel: dict[int, list[tuple[int, float]]] = {}
        net_links = net.links
        for lk in net_links:
            pts = self._points(lk.pts)
            w: dict[int, float] = {}
            for px, py in pts:
                ci0, ci1 = int((px - REACH - x0) // CELL), int((px + REACH - x0) // CELL)
                cj0, cj1 = int((py - REACH - y0) // CELL), int((py + REACH - y0) // CELL)
                for i in range(max(0, ci0), min(self.nx - 1, ci1) + 1):
                    for j in range(max(0, cj0), min(self.ny - 1, cj1) + 1):
                        cx, cy = x0 + (i + 0.5) * CELL, y0 + (j + 0.5) * CELL
                        d2 = (cx - px) ** 2 + (cy - py) ** 2
                        if d2 <= REACH * REACH:
                            k = j * self.nx + i
                            w[k] = w.get(k, 0.0) + math.exp(-d2 / (2 * SIGMA * SIGMA)) / len(pts)
            self.kernel[lk.id] = list(w.items())

    @staticmethod
    def _points(pts, every: float = 50.0):
        out = [pts[0]]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            n = max(1, int(math.dist((ax, ay), (bx, by)) // every))
            out += [(ax + (bx - ax) * k / n, ay + (by - ay) * k / n) for k in range(1, n + 1)]
        return out

    def cell_of(self, x: float, y: float) -> int:
        i = min(self.nx - 1, max(0, int((x - self.x0) // CELL)))
        j = min(self.ny - 1, max(0, int((y - self.y0) // CELL)))
        return j * self.nx + i

    def centre(self, k: int) -> tuple[float, float]:
        return self.x0 + (k % self.nx + 0.5) * CELL, self.y0 + (k // self.nx + 0.5) * CELL

    def spread(self, grams: dict[int, float]) -> list[float]:
        raw = [0.0] * (self.nx * self.ny)
        for lid, g in grams.items():
            for k, w in self.kernel.get(lid, ()):
                raw[k] += g * w
        return raw


def idw(points: list[tuple[float, float, float]], x: float, y: float) -> float:
    """Inverse-distance (power 2) interpolation of point readings."""
    num = den = 0.0
    for px, py, v in points:
        d2 = (px - x) ** 2 + (py - y) ** 2
        if d2 < 1:
            return v
        num += v / d2
        den += 1 / d2
    return num / den if den else float("nan")


def sensor_sites(net: Network, n: int = 25, seed: int = 7) -> tuple[dict, list[dict]]:
    """The official monitor and n low-cost sensors at real schools, hospitals and colleges."""
    rng = random.Random(seed * 13 + 25)
    pois = [p for p in snap_pois(net) if p["kind"] in ("school", "hospital", "college", "university", "clinic")]
    pois.sort(key=lambda p: p["i"])
    official = next(p for p in pois if p["kind"] == "hospital")            # monitors usually sit at a public building
    # 10 on junction poles where the main roads cross (that is where the queues are)
    junc = []
    for sg in build_signals(net):
        if max(net.links[l].rank for ph in sg.phases for l in ph) >= 4:
            junc.append({"name": sg.name, "kind": "junction",
                         "x": sum(net.nodes[n][0] for n in sg.nodes) / len(sg.nodes),
                         "y": sum(net.nodes[n][1] for n in sg.nodes) / len(sg.nodes)})

    def spread_pick(pool, k, chosen):
        pool = list(pool)
        while k and pool:          # farthest-point picking, so the sensors cover the area
            best = max(pool, key=lambda p: min(math.dist((p["x"], p["y"]), (c["x"], c["y"])) for c in chosen))
            chosen.append(best)
            pool.remove(best)
            k -= 1
        return chosen
    chosen = spread_pick([p for p in pois if p is not official], 15, [official])
    chosen = spread_pick(junc, n - 15, chosen)
    sensors = [{"name": p["name"] or p["kind"], "kind": p["kind"], "x": p["x"], "y": p["y"],
                "gain": rng.uniform(0.75, 1.35), "noise": rng.uniform(0.06, 0.14)} for p in chosen]
    sensors[0]["gain"], sensors[0]["noise"] = 1.0, 0.02             # the co-located one reads like the monitor
    return {"name": official["name"], "x": official["x"], "y": official["y"]}, sensors


def smog(seed: int = 7, per_hour: int = 8000, minutes: int = 60) -> dict:
    net = load()
    grid = Grid(net)
    trips = make_demand(net, seed=seed, minutes=minutes, per_hour=per_hour, period="evening")

    def run(adaptive_near=None):
        sim = TrafficSim(net, trips, "fixed", minutes=minutes)
        if adaptive_near:
            cx, cy, r = adaptive_near
            for s in sim.signals:
                sx = sum(net.nodes[n][0] for n in s.nodes) / len(s.nodes)
                sy = sum(net.nodes[n][1] for n in s.nodes) / len(s.nodes)
                if math.dist((sx, sy), (cx, cy)) <= r:
                    s.adaptive = True
        em = Emissions(sim)
        sim.run()
        return sim, em

    sim0, em0 = run()
    raws = {m: grid.spread(em0.g.get(m, {})) for m in range(minutes)}
    # scale traffic so it is TRAFFIC_SHARE of the area mean at the peak (last 15 minutes)
    peak = range(max(0, minutes - 15), minutes)
    # calibrate over the cells people live and travel in: within 250 m of a road with traffic
    near = [k for k in range(grid.nx * grid.ny) if any(raws[m][k] > 0 for m in peak)]
    mean_raw = sum(sum(raws[m][k] for k in near) / len(near) for m in peak) / len(peak)
    mean_bg = sum(background(m, minutes) for m in peak) / len(peak)
    scale = (TRAFFIC_SHARE / (1 - TRAFFIC_SHARE)) * mean_bg / mean_raw

    def field(r, m):
        b = background(m, minutes)
        return [b + scale * v for v in r]

    truth = {m: field(raws[m], m) for m in range(minutes)}
    official, sensors = sensor_sites(net, seed=seed)
    rng = random.Random(seed * 17 + 3)
    cell_s = [grid.cell_of(s["x"], s["y"]) for s in sensors]
    cell_o = grid.cell_of(official["x"], official["y"])
    readings, est_today, est_conn = {}, {}, {}
    for m in range(minutes):
        tru = truth[m]
        raw = [tru[c] * s["gain"] * (1 + rng.gauss(0, s["noise"])) for s, c in zip(sensors, cell_s)]
        off = tru[cell_o] * (1 + rng.gauss(0, 0.02))
        # each sensor's own gain is unknown; what a city can apply is one network-wide correction,
        # from the sensor that stands beside the official monitor
        corr = off / raw[0] if raw[0] else 1.0
        cal = [v * corr for v in raw]
        readings[m] = [round(v, 1) for v in cal]
        est_today[m] = off
        # Connected: a land-use regression refitted every minute - the 25 readings against the
        # traffic the signals' loop detectors counted, spread like the smoke - then the residuals
        # interpolated. Detectors sit only on signal approaches, so this is no copy of the truth.
        proxy = grid.spread(em0.counts.get(m, {}))
        xs_, ys_ = [proxy[c] for c in cell_s], cal
        n_ = len(xs_)
        mx, my = sum(xs_) / n_, sum(ys_) / n_
        vx = sum((x - mx) ** 2 for x in xs_)
        b = max(0.0, sum((x - mx) * (y - my) for x, y in zip(xs_, ys_)) / vx) if vx > 0 else 0.0
        a = my - b * mx
        res = [(s["x"], s["y"], y - (a + b * x)) for s, x, y in zip(sensors, xs_, ys_)]
        est_conn[m] = [a + b * proxy[k] + idw(res, *grid.centre(k)) for k in range(grid.nx * grid.ny)]
    # the hotspot: the worst cell over the peak quarter-hour, by truth and by the network. One
    # minute's worst cell jumps between junctions as queues come and go; a city acts on a mean
    def worst(fields):
        return max(range(grid.nx * grid.ny), key=lambda k: sum(fields[m][k] for m in peak))
    true_hot, conn_hot = worst(truth), worst(est_conn)
    last = minutes - 1
    hx, hy = grid.centre(conn_hot)
    # act: adaptive signals within 400 m of the hotspot the sensors found; same trips again
    sim1, em1 = run(adaptive_near=(hx, hy, 400.0))
    after = {m: field(grid.spread(em1.g.get(m, {})), m) for m in range(minutes)}
    schools = [p for p in snap_pois(net) if p["kind"] in ("school", "college")]
    hosp = [p for p in snap_pois(net) if p["kind"] == "hospital"]
    sensitive = [p for p in snap_pois(net) if p["kind"] in ("school", "college", "hospital", "clinic")]

    def exposure(fieldset, places, cx=None, cy=None, r=None):
        cells = [grid.cell_of(p["x"], p["y"]) for p in places
                 if r is None or math.dist((p["x"], p["y"]), (cx, cy)) <= r]
        if not cells:
            return None
        return round(sum(fieldset[m][c] for m in peak for c in cells) / (len(cells) * len(peak)), 1)

    def err(est):
        """Mean absolute error, µg/m³, over the cells near roads - where people are - at the peak."""
        return round(sum(abs(est[m][k] - truth[m][k]) if isinstance(est[m], list) else abs(est[m] - truth[m][k])
                         for m in peak for k in near) / (len(peak) * len(near)), 1)

    near_hot = [k for k in range(len(truth[last])) if math.dist(grid.centre(k), (hx, hy)) <= 400]
    tx, ty = grid.centre(true_hot)
    true_cells = [k for k in range(len(truth[last])) if math.dist(grid.centre(k), (tx, ty)) <= 400]

    def mean_at(f, cells):
        return round(sum(f[m][k] for m in peak for k in cells) / (len(peak) * len(cells)), 1)
    return {
        "grid": grid, "truth": truth, "after": after, "est_conn": est_conn, "est_today": est_today, "readings": readings,
        "sensors": sensors, "official": official, "scale": scale, "trips": len(trips), "minutes": minutes,
        "metrics": {
            "area_mean_peak": round(sum(sum(truth[m]) / len(truth[m]) for m in peak) / len(peak), 1),
            "worst_cell_peak": round(max(truth[last]), 1),
            "official_reads_peak": round(sum(est_today[m] for m in peak) / len(peak), 1),
            "map_error_today": err(est_today), "map_error_sensors": err(est_conn),
            "hotspot_found_m": round(math.dist(grid.centre(true_hot), (hx, hy))),
            "schools_peak": exposure(truth, schools), "hospitals_peak": exposure(truth, hosp),
            "hotspot_before": mean_at(truth, near_hot), "hotspot_after": mean_at(after, near_hot),
            # the action is taken where the network thinks the hotspot is; this is what it does at the real one
            "true_hotspot_before": mean_at(truth, true_cells), "true_hotspot_after": mean_at(after, true_cells),
            # schools, colleges, hospitals and clinics within 800 m of the hotspot the sensors found
            "sensitive_sites_near_hotspot": len([q for q in sensitive if math.dist((q["x"], q["y"]), (hx, hy)) <= 800]),
            "sensitive_near_hotspot_before": exposure(truth, sensitive, hx, hy, 800),
            "sensitive_near_hotspot_after": exposure(after, sensitive, hx, hy, 800),
            "adaptive_signals": sum(1 for s in sim1.signals if s.adaptive),
        },
        "hotspot": [round(hx, 1), round(hy, 1)],
    }


# ------------------------------------------------------------------ underpass flooding
# Assumptions, labelled: the storm, the catchment that drains into each dip, pump capacity, the
# feeder trip, how long it takes someone to start a generator by hand, and stall depths.
STORM_START, STORM_PEAK_MMH = 0, 60.0          # minutes after 18:00; mm per hour at the peak
PUMP_M3S = 0.25                                # per underpass
CATCHMENT_M2 = 20000.0                         # streets around the dip that drain into it
MIN_DIP_M2 = 1200.0                            # OSM may map only part of a dip; with its ramps it is at least this
POWER_CUT = (25 * 60, 65 * 60)                 # LESCO feeder trips, 18:25-19:05 (seconds)
GEN_TODAY, GEN_CONNECTED = 30 * 60, 2 * 60     # time to get the generator running after the cut
STALL = {"motorcycle": 0.30, "rickshaw": 0.30, "car": 0.45, "bus": 0.70, "ambulance": 0.60}
CLOSE_AT, OPEN_AT = 0.15, 0.05                 # Connected: gate closes / reopens at these depths (m)


def rain_mmh(t: float) -> float:
    """Storm intensity at t seconds after 18:00: up for 20 min, 20 min at the peak, down over 40."""
    m = t / 60 - STORM_START
    if m < 0 or m > 80:
        return 0.0
    if m < 20:
        return STORM_PEAK_MMH * m / 20
    if m < 40:
        return STORM_PEAK_MMH
    return STORM_PEAK_MMH * (80 - m) / 40


def underpasses(net: Network) -> list[dict]:
    """The real underpasses: tunnel links (layer -1) grouped where they lie within 200 m."""
    tun = [lk for lk in net.links if lk.layer < 0]
    groups: list[list] = []
    for lk in tun:
        c = ((lk.pts[0][0] + lk.pts[-1][0]) / 2, (lk.pts[0][1] + lk.pts[-1][1]) / 2)
        g = next((g for g in groups if any(math.dist(c, ((o.pts[0][0] + o.pts[-1][0]) / 2, (o.pts[0][1] + o.pts[-1][1]) / 2)) < 200 for o in g)), None)
        (g.append(lk) if g else groups.append([lk]))
    out = []
    for g in groups:
        names = [lk.name for lk in g if lk.name]
        name = max(set(names), key=names.count) if names else "Underpass"
        if "nderpass" not in name:
            name += " underpass"
        roads = {lk.road for lk in g}
        area = sum(net.links[next(l.id for l in g if l.road == r)].length * max(l.lanes for l in g if l.road == r) * 3.2
                   * (1 if any(l.oneway for l in g if l.road == r) else 2) for r in roads)
        xs = [p for lk in g for p in (lk.pts[0], lk.pts[-1])]
        n = sum(1 for o in out if o["name"].startswith(name))
        if n:
            name = f"{name} ({n + 1})"          # two separate underpasses on one road
        area = max(area, MIN_DIP_M2)
        out.append({"name": name, "links": [lk.id for lk in g], "dip_m2": round(area, 1),
                    "catchment_m2": CATCHMENT_M2,
                    "x": sum(p[0] for p in xs) / len(xs), "y": sum(p[1] for p in xs) / len(xs)})
    return out


def depth_series(up: dict, generator_after: int, seconds: int) -> list[float]:
    """Water depth (m) in the dip, every second: rain on dip + catchment in, pumps out while powered."""
    v, out = 0.0, []
    for t in range(seconds):
        q_in = rain_mmh(t) / 1000 / 3600 * (up["dip_m2"] + up["catchment_m2"])
        powered = not (POWER_CUT[0] <= t < POWER_CUT[1]) or t >= POWER_CUT[0] + generator_after
        q_out = PUMP_M3S if powered else 0.0
        v = max(0.0, v + q_in - q_out)
        out.append(v / up["dip_m2"])
    return out


def flood(seed: int = 7, per_hour: int = 6000, minutes: int = 60) -> dict:
    net = load()
    ups = underpasses(net)
    T = minutes * 60 + 900
    trips = make_demand(net, seed=seed, minutes=minutes, per_hour=per_hour, period="evening")
    res = {}
    for mode, gen in (("today", GEN_TODAY), ("connected", GEN_CONNECTED)):
        depth = {u["name"]: depth_series(u, gen, T) for u in ups}
        link_up = {lid: u["name"] for u in ups for lid in u["links"]}
        sim = TrafficSim(net, trips, "fixed", minutes=minutes)
        stranded: dict[int, tuple[int, str]] = {}
        closed: dict[str, list] = {u["name"]: [] for u in ups}
        is_closed = {u["name"]: False for u in ups}
        rerouted = set()
        mv = Movements(net)
        step = sim.step

        def reroute(v, t):
            """From where it is to its next fixed point, avoiding the closed underpasses."""
            nxt = [e for e in v.errands[v.ei:] if e[0] > v.ri]
            k = min(e[0] for e in nxt) if nxt else len(v.route) - 1
            if not any(lid in mv.closed for lid in v.route[v.ri + 1:k + 1]):
                return
            mid = mv.route(v.route[v.ri], v.route[k])
            if mid is None:
                return
            new = v.route[:v.ri + 1] + mid + v.route[k + 1:]
            shift = len(new) - len(v.route)
            v.errands = [((e[0] + shift,) + tuple(e[1:])) if e[0] > v.ri else e for e in v.errands]
            v.route = new
            rerouted.add(v.id)

        def watched(t):
            if mode == "connected":
                changed = False
                for u in ups:
                    d = depth[u["name"]][t]
                    if not is_closed[u["name"]] and d >= CLOSE_AT:
                        is_closed[u["name"]] = changed = True
                        closed[u["name"]].append([t, None])
                    elif is_closed[u["name"]] and d <= OPEN_AT:
                        is_closed[u["name"]] = False
                        closed[u["name"]][-1][1] = t
                        changed = True
                if changed:
                    mv.closed = {lid for u in ups if is_closed[u["name"]] for lid in u["links"]}
                if mv.closed and (changed or t % 30 == 0):
                    for v in sim.active + [w for q in sim.waiting.values() for w in q]:
                        reroute(v, t)
            step(t)
            # water deeper than a vehicle can take: it stalls where it is
            for v in sim.active:
                lid = v.route[v.ri]
                if lid in link_up and v.id not in stranded and depth[link_up[lid]][t] >= STALL[v.kind]:
                    stranded[v.id] = (t, link_up[lid])
                    v.hold_until = 10 ** 9
        mv.closed = set()
        sim.step = watched
        sim.run()
        m = sim.metrics()
        # where the gridlock is: at an underpass (stranded, or queued behind one), or on the surface
        stuck = [v for v in sim.active if v.still_since is not None and sim.t - v.still_since > 300 and v.id not in stranded]

        def near_up(v):
            lk = net.links[v.route[v.ri]]
            return min(math.dist(lk.pts[-1], (u["x"], u["y"])) for u in ups) < 400
        res[mode] = {"gridlocked_near_underpass": sum(1 for v in stuck if near_up(v)),
                     "gridlocked_elsewhere": sum(1 for v in stuck if not near_up(v)),
                     "depth": {k: [round(d, 3) for d in v[::30]] for k, v in depth.items()},
                     "max_depth": {k: round(max(v), 2) for k, v in depth.items()},
                     "stranded": len(stranded),
                     "stranded_events": sorted([t, u] for t, u in stranded.values()),
                     "stranded_at": {k: sum(1 for _, (_, u) in stranded.items() if u == k) for k in depth},
                     "closed": closed, "closed_min": {k: round(sum(((b or T) - a) for a, b in v) / 60) for k, v in closed.items()},
                     "rerouted": len(rerouted), "delay_median_s": m["delay_median_s"], "completed": m["completed"],
                     "gridlocked": m["gridlocked"], "trips": m["trips"]}
    return {"underpasses": [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in u.items()} for u in ups],
            "modes": res, "rain": [round(rain_mmh(t), 1) for t in range(0, T, 30)], "power_cut": list(POWER_CUT),
            "generator": {"today": GEN_TODAY, "connected": GEN_CONNECTED}, "trips": len(trips), "minutes": minutes}


# ------------------------------------------------------------------ streetlights
# Assumptions, labelled: spacing and wattage, the dim level, the night's demand, the load-shedding
# hour and which feeders it hits, the lamp failure rate.
NIGHT_START = 23 * 3600
SPACING = {True: 35.0, False: 40.0}            # main road (tertiary or bigger) / smaller street, metres
WATTS = {True: 150.0, False: 70.0}             # LED luminaire
DIM = 0.30                                     # Connected: share of full power with nobody near
OUTAGE = (2 * 3600, 3 * 3600)                  # 01:00-02:00, seconds after 23:00
FAIL_RATE = 0.004                              # lamps that fail during a night


def streetlights(seed: int = 7, per_hour: int = 900, minutes: int = 360) -> dict:
    net = load()
    rng = random.Random(seed * 41 + 5)
    trips = make_demand(net, seed=seed, minutes=minutes, per_hour=per_hour, period="evening")
    sim = TrafficSim(net, trips, "adaptive", minutes=minutes)      # at night the signals are adaptive or flashing
    seen: dict[int, set] = {}                                      # minute -> road pieces with a vehicle on them
    step = sim.step

    def watched(t):
        step(t)
        if t % 10 == 0:
            bucket = seen.setdefault(t // 60, set())
            for v in sim.active:
                bucket.add(net.links[v.route[v.ri]].road)
    sim.step = watched
    sim.run()
    roads = [i for i, r in enumerate(net.roads) if CLASSES_RANK(r["cls"]) >= 1]
    main = {i: CLASSES_RANK(net.roads[i]["cls"]) >= 3 for i in roads}
    lamps = {i: max(1, int(_len(net.roads[i]["pts"]) // SPACING[main[i]])) for i in roads}
    # neighbours: road pieces sharing an end, so a light brightens before a car arrives
    ends: dict[tuple, list] = {}
    for i in roads:
        pts = net.roads[i]["pts"]
        for e in (tuple(pts[0]), tuple(pts[-1])):
            ends.setdefault(e, []).append(i)
    nbr = {i: {j for e in (tuple(net.roads[i]["pts"][0]), tuple(net.roads[i]["pts"][-1])) for j in ends[e]} for i in roads}
    xmid = (net.bbox[0] + net.bbox[2]) / 2
    east = {i: (net.roads[i]["pts"][0][0] + net.roads[i]["pts"][-1][0]) / 2 > xmid for i in roads}    # the feeder that is shed
    # failures: lamps that go out at a random minute
    fails = []
    for i in roads:
        for _ in range(lamps[i]):
            if rng.random() < FAIL_RATE:
                fails.append((i, rng.randrange(minutes)))
    failed_from: dict[int, list[int]] = {}
    for i, m in fails:
        failed_from.setdefault(i, []).append(m)
    out = {}
    for mode in ("today", "connected"):
        kwh, dark_vm, lit_vm, changes = 0.0, 0, 0, {}
        kw = [0.0] * minutes
        for i in roads:
            last, ch = None, []
            for m in range(minutes):
                shed = east[i] and OUTAGE[0] <= m * 60 < OUTAGE[1]
                busy = any(j in seen.get(m, ()) or j in seen.get(m - 1, ()) for j in nbr[i])
                if mode == "today":
                    level = 0.0 if shed else 1.0
                else:
                    if shed and not main[i]:
                        level = 0.0                        # minor streets have no battery
                    else:
                        level = 1.0 if busy else DIM
                n_ok = lamps[i] - sum(1 for f in failed_from.get(i, ()) if f <= m)
                kwh += level * n_ok * WATTS[main[i]] / 1000 / 60
                kw[m] += level * n_ok * WATTS[main[i]] / 1000
                if i in seen.get(m, ()):
                    if level == 0.0:
                        dark_vm += 1
                    else:
                        lit_vm += 1
                if level != last:
                    ch.append([m, level])
                    last = level
            changes[i] = ch
        # road-minutes with traffic on them: in the dark, and lit
        out[mode] = {"kwh": round(kwh, 1), "busy_road_minutes_dark": dark_vm, "busy_road_minutes_lit": lit_vm,
                     "kw": [round(x, 1) for x in kw],
                     "failures_known_by_morning": len(fails) if mode == "connected" else 0,
                     "changes": changes}
    return {"roads": roads, "lamps": lamps, "main": main, "fails": fails, "modes": out, "minutes": minutes,
            "trips": len(trips), "lamp_count": sum(lamps.values()),
            "night_full_kwh": round(sum(lamps[i] * WATTS[main[i]] for i in roads) / 1000 * minutes / 60, 1)}


def _len(pts) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def CLASSES_RANK(cls: str) -> int:      # noqa: N802
    from .roads import CLASSES
    return CLASSES[cls][2]
