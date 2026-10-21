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
    # the hotspot: the worst cell at the peak, by truth and by each network
    last = minutes - 1
    true_hot = max(range(len(truth[last])), key=lambda k: truth[last][k])
    conn_hot = max(range(len(est_conn[last])), key=lambda k: est_conn[last][k])
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
            "hotspot_before": round(sum(truth[m][k] for m in peak for k in near_hot) / (len(peak) * len(near_hot)), 1),
            "hotspot_after": round(sum(after[m][k] for m in peak for k in near_hot) / (len(peak) * len(near_hot)), 1),
            # schools, colleges, hospitals and clinics within 800 m of the hotspot the sensors found
            "sensitive_sites_near_hotspot": len([q for q in sensitive if math.dist((q["x"], q["y"]), (hx, hy)) <= 800]),
            "sensitive_near_hotspot_before": exposure(truth, sensitive, hx, hy, 800),
            "sensitive_near_hotspot_after": exposure(after, sensitive, hx, hy, 800),
            "adaptive_signals": sum(1 for s in sim1.signals if s.adaptive),
        },
        "hotspot": [round(hx, 1), round(hy, 1)],
    }
