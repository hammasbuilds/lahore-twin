"""Where every vehicle was, compactly, for pages that draw traffic without the whole road network.

The traffic module stores each vehicle as its route and its distance along it, and its page walks
the link polylines. The junction planner and the city systems carry only drawn roads, not links,
so they get each vehicle's point on the road instead: lane offset included, rounded to `quant`
metres, every `stride` samples (SAMPLE seconds each), delta-encoded. A vehicle that leaves the area
and comes back is two tracks.

    {"dt": 4, "q": 1, "kinds": [...], "v": [[kind, t_first, [x0, y0, dx1, dy1, ...], [[k, n], ...]], ...]}

Standing still costs nothing per sample: [k, n] says that after its k-th stored point the vehicle
stood where it was for n more samples (a queue, a red light, a stall in water). Without that, a
gridlocked evening stored every standing vehicle again every sample, and the files tripled.
"""

from __future__ import annotations

import math

from .traffic_sim import KINDS, SAMPLE, TrafficSim

LANE_W = 3.2                      # metres, as viewer/traffic.js draws lanes
KIND_LIST = list(KINDS)


def _point(lk, along: float, lane: int) -> tuple[float, float]:
    """The point `along` metres down the link's polyline, moved into its lane (Pakistan drives on the left)."""
    pts = lk.pts
    x, y, hx, hy = pts[0][0], pts[0][1], 1.0, 0.0
    for s in range(1, len(pts)):
        (ax, ay), (bx, by) = pts[s - 1], pts[s]
        seg = math.hypot(bx - ax, by - ay) or 1e-6
        hx, hy = (bx - ax) / seg, (by - ay) / seg
        if along <= seg or s == len(pts) - 1:
            u = min(along, seg)
            x, y = ax + hx * u, ay + hy * u
            break
        along -= seg
    ln = lk.lanes - 1 + 1.4 if lane < 0 else lane          # -1: pulled off beside the kerb
    off = (ln + 0.5 - lk.lanes / 2) * LANE_W if lk.oneway else (ln + 0.5) * LANE_W
    return x + hy * off, y - hx * off


def record(sim: TrafficSim, *, centre: tuple[float, float] | None = None, radius: float = math.inf,
           t_from: float = 0, t_to: float = math.inf, stride: int = 1, quant: float = 1.0,
           origin: tuple[float, float] = (0.0, 0.0), keep=None) -> dict:
    """Tracks of every vehicle while it was within `radius` of `centre` (all of them when no centre)
    and, when given, where keep(x, y) is true; between t_from and t_to (sim seconds). Coordinates are
    relative to `origin`."""
    links = sim.links
    runs: list[tuple[int, int, list]] = []                 # (kind, first t, [(qx, qy), ...]) per stretch inside

    def close(cur):
        if cur and len(cur[2]) >= 2:
            runs.append(cur)

    for v in sim.vehicles:
        cur, last_t = None, None
        for t, ri, pos, lane in v.samples[::stride]:
            if t < t_from or t > t_to:
                continue
            x, y = _point(links[v.route[ri]], pos, lane)
            inside = (centre is None or math.dist((x, y), centre) <= radius) and (keep is None or keep(x, y))
            if not inside or (last_t is not None and t - last_t > SAMPLE * stride):
                close(cur)
                cur = None
            if not inside:
                last_t = None
                continue
            q = (round((x - origin[0]) / quant), round((y - origin[1]) / quant))
            if cur is None:
                cur = (KIND_LIST.index(v.kind), t, [])
            cur[2].append(q)
            last_t = t
        close(cur)
    return {"dt": SAMPLE * stride, "q": quant, "kinds": KIND_LIST, "v": [_pack(k, t, pts) for k, t, pts in runs]}


def _pack(kind: int, t0: int, pts: list) -> list:
    """[kind, t0, deltas of the points where it moved, [[k, n] standing runs]]."""
    flat, still = [pts[0][0], pts[0][1]], []
    prev, k = pts[0], 0
    for p in pts[1:]:
        if p == prev:
            if still and still[-1][0] == k:
                still[-1][1] += 1
            else:
                still.append([k, 1])
            continue
        flat += [p[0] - prev[0], p[1] - prev[1]]
        prev, k = p, k + 1
    return [kind, t0, flat, still]


def corridor(lines, width: float, cell: float = 50.0):
    """keep(x, y) for points within about `width` metres of any of the polylines: a set of grid cells,
    so the test per sample is a lookup, not a distance to every segment."""
    cells, reach = set(), int(math.ceil(width / cell))
    for pts in lines:
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            steps = max(1, int(math.dist((ax, ay), (bx, by)) // (cell / 2)))
            for k in range(steps + 1):
                cx, cy = int((ax + (bx - ax) * k / steps) // cell), int((ay + (by - ay) * k / steps) // cell)
                for dx in range(-reach, reach + 1):
                    for dy in range(-reach, reach + 1):
                        if dx * dx + dy * dy <= reach * reach:
                            cells.add((cx + dx, cy + dy))
    return lambda x, y: (int(x // cell), int(y // cell)) in cells
