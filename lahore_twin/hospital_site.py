"""The Lahore General Hospital campus from OpenStreetMap, and where the two
simulated floors sit on it.

The OSM extract (plans/osm/lgh_campus.json) is projected to metres around the
campus, then rotated 17.5° so the buildings, which are built square to each
other but not to north, line up with the axes. The Emergency Department plan is
the ED footprint itself; the ward plan sits in the main block's south wing,
turned a quarter so its lift lobby meets the corridor that joins the wing to the
rest of the block. People who move between the two buildings walk a campus path
found once by A* on a 2 m grid that avoids every building footprint.
"""

from __future__ import annotations

import heapq
import json
import math
from functools import lru_cache
from pathlib import Path

OSM = Path(__file__).resolve().parent.parent / "plans" / "osm" / "lgh_campus.json"
ROT_DEG = 17.5
ED_WAY, MAIN_WAY = 706568994, 447968942
GRID = 2.0


def _project(raw: dict):
    camp = raw["elements"][0]["geometry"]
    lat0 = camp[0][0]
    k = 111320 * math.cos(math.radians(lat0))
    lon0 = min(p[1] for p in camp)
    lat1 = max(p[0] for p in camp)
    th = math.radians(ROT_DEG)

    def xy(p):
        x, y = (p[1] - lon0) * k, (lat1 - p[0]) * 110540
        return (x * math.cos(th) - y * math.sin(th), x * math.sin(th) + y * math.cos(th))
    return xy


def _inside(pt, poly) -> bool:
    x, y, hit = pt[0], pt[1], False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


@lru_cache(maxsize=1)
def site() -> dict:
    raw = json.loads(OSM.read_text(encoding="utf-8"))
    xy = _project(raw)
    polys = {e["id"]: [xy(p) for p in e["geometry"]][:-1] for e in raw["elements"]}
    camp_id = raw["elements"][0]["id"]
    allpts = polys[camp_id]
    ox, oy = min(p[0] for p in allpts) - 6, min(p[1] for p in allpts) - 6
    polys = {i: [(round(x - ox, 2), round(y - oy, 2)) for x, y in pts] for i, pts in polys.items()}
    names = {e["id"]: e["tags"].get("name", "") for e in raw["elements"]}

    ed = polys[ED_WAY]
    ed_origin = (min(p[0] for p in ed), min(p[1] for p in ed))
    main = polys[MAIN_WAY]
    main_origin = (min(p[0] for p in main), min(p[1] for p in main))
    # ward plan (x, y) -> campus: X = main_x0 + 30 + y, Y = main_y0 + 123.5 - x
    ward = {"origin": main_origin, "dx": 30.0, "dy": 123.5}

    width = max(p[0] for p in allpts) - ox + 6
    height = max(p[1] for p in allpts) - oy + 6
    out = {
        "rotation_deg": ROT_DEG,
        "size": [round(width, 1), round(height, 1)],
        "campus": polys[camp_id],
        "buildings": [{"id": i, "name": names[i], "poly": p, "sim": i in (ED_WAY, MAIN_WAY)}
                      for i, p in polys.items() if i != camp_id],
        "ed_origin": ed_origin,
        "ward": ward,
        "licence": raw["licence"],
        "source": raw["source"],
    }
    out["ed_exit"] = ed_to_site(out, 15.5, 57.5)
    out["ward_entry"] = ward_to_site(out, 37, 20)
    out["path"] = _campus_path(out, out["ed_exit"], out["ward_entry"])
    out["path_m"] = round(sum(math.dist(a, b) for a, b in zip(out["path"], out["path"][1:])), 1)
    return out


def ed_to_site(s: dict, x: float, y: float) -> tuple[float, float]:
    return (round(s["ed_origin"][0] + x, 2), round(s["ed_origin"][1] + y, 2))


def ward_to_site(s: dict, x: float, y: float) -> tuple[float, float]:
    w = s["ward"]
    return (round(w["origin"][0] + w["dx"] + y, 2), round(w["origin"][1] + w["dy"] - x, 2))


def _campus_path(s: dict, a, b) -> list[tuple[float, float]]:
    """Shortest 8-connected walk on a 2 m grid that keeps 1 m clear of every
    building, from the open ground nearest each end, then straightened."""
    cols, rows = int(s["size"][0] / GRID) + 1, int(s["size"][1] / GRID) + 1
    blocked = set()
    for bld in s["buildings"]:
        p = bld["poly"]
        xs, ys = [q[0] for q in p], [q[1] for q in p]
        for c in range(int(min(xs) / GRID) - 1, int(max(xs) / GRID) + 2):
            for r in range(int(min(ys) / GRID) - 1, int(max(ys) / GRID) + 2):
                cx, cy = (c + 0.5) * GRID, (r + 0.5) * GRID
                if any(_inside((cx + dx, cy + dy), p) for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                    blocked.add((c, r))
    camp = s["campus"]
    cell = lambda pt: (int(pt[0] / GRID), int(pt[1] / GRID))
    open_ = lambda c: c not in blocked and _inside(((c[0] + .5) * GRID, (c[1] + .5) * GRID), camp)

    def nearest_open(pt):
        # an end inside a building (the ward's lifts) walks out through that building first
        c0 = cell(pt)
        for rad in range(0, 60):
            ring = [(c0[0] + dc, c0[1] + dr) for dc in range(-rad, rad + 1) for dr in range(-rad, rad + 1)
                    if max(abs(dc), abs(dr)) == rad and open_((c0[0] + dc, c0[1] + dr))]
            if ring:
                return min(ring, key=lambda c: math.dist(((c[0] + .5) * GRID, (c[1] + .5) * GRID), pt))
        raise ValueError(f"no open ground near {pt}")
    sa, sb = nearest_open(a), nearest_open(b)
    free = open_
    openq, came, cost = [(0.0, sa)], {sa: None}, {sa: 0.0}
    while openq:
        _, cur = heapq.heappop(openq)
        if cur == sb:
            break
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                n = (cur[0] + dc, cur[1] + dr)
                if n == cur or not (0 <= n[0] < cols and 0 <= n[1] < rows) or not free(n):
                    continue
                if dc and dr and not (free((cur[0] + dc, cur[1])) and free((cur[0], cur[1] + dr))):
                    continue
                ng = cost[cur] + math.hypot(dc, dr)
                if ng < cost.get(n, math.inf):
                    cost[n], came[n] = ng, cur
                    heapq.heappush(openq, (ng + math.dist(n, sb), n))
    if sb not in came:
        raise ValueError("no campus path between the ED and the ward")
    cells, cur = [], sb
    while cur is not None:
        cells.append(cur)
        cur = came[cur]
    pts = [((c + .5) * GRID, (r + .5) * GRID) for c, r in cells[::-1]]
    # string-pull: drop a point when the straight line to the next kept point stays on free cells
    def clear(p, q):
        n = int(math.dist(p, q) / (GRID / 2)) + 1
        return all(free(cell((p[0] + (q[0] - p[0]) * i / n, p[1] + (q[1] - p[1]) * i / n))) for i in range(n + 1))
    out, i = [pts[0]], 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not clear(pts[i], pts[j]):
            j -= 1
        out.append(pts[j])
        i = j
    out = [a] + out + [b]
    return [(round(x, 2), round(y, 2)) for x, y in out]
