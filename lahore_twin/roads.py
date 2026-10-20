"""Lahore's roads from OpenStreetMap as a network vehicles can drive.

The extract (plans/osm/lahore_gulberg_roads.json) is projected to metres around
its centre (x east, y south). Ways are split wherever two ways share a node, and
each piece becomes one directed link per direction it can be driven: lanes from
the OSM tag (two-way roads split them between directions) or a default by road
class, a speed by class, and the way's layer — bridges and flyovers +1, tunnels
and underpasses −1. Roads on different layers only meet where OSM joins them,
so a flyover passes over the junction below it.

OSM's maxspeed tags here are unreliable (a roundabout tagged 120 km/h), so speeds
come from the road class. Signals are barely mapped (2 nodes in the area), so
``signal_sites`` places them at at-grade junctions of tertiary-or-bigger roads
and says so.
"""

from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

OSM = Path(__file__).resolve().parent.parent / "plans" / "osm" / "lahore_gulberg_roads.json"

# class -> (lanes per direction when untagged, speed km/h, rank)
CLASSES = {
    "trunk": (3, 60, 6), "primary": (3, 50, 5), "secondary": (2, 45, 4), "tertiary": (1, 40, 3),
    "unclassified": (1, 30, 2), "residential": (1, 25, 1), "living_street": (1, 15, 0), "service": (1, 15, 0),
    "trunk_link": (1, 40, 5), "primary_link": (1, 35, 4), "secondary_link": (1, 30, 3), "tertiary_link": (1, 30, 2),
    "motorway": (3, 80, 7), "motorway_link": (1, 50, 6),
}
LANE_W = 3.2


@dataclass
class Link:
    id: int
    a: int                       # from node (OSM id)
    b: int                       # to node
    pts: list                    # polyline (x, y) metres, in driving direction
    length: float
    cls: str
    lanes: int
    speed: float                 # m/s
    rank: int
    layer: int
    name: str
    oneway: bool
    road: int                    # index of the drawn road this link belongs to
    roundabout: bool = False
    back: bool = False           # runs against the drawn road's point order
    out: list = field(default_factory=list, repr=False)     # links that leave node b (not the U-turn back)


@dataclass
class Network:
    links: list[Link]
    nodes: dict[int, tuple[float, float]]
    roads: list[dict]            # undirected pieces for drawing
    signals_osm: set
    bbox: tuple
    origin: tuple
    licence: str
    into: dict = field(default_factory=dict)    # node -> links arriving

    def node_xy(self, n: int) -> tuple[float, float]:
        return self.nodes[n]


def _project(lat0: float, lon0: float):
    k = 111320 * math.cos(math.radians(lat0))

    def xy(lat, lon):
        return (round((lon - lon0) * k, 2), round((lat0 - lat) * 110540, 2))
    return xy


def _polylen(pts) -> float:
    return sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))


@lru_cache(maxsize=2)
def load(path: str = str(OSM)) -> Network:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    ways = [w for w in raw["ways"] if w["tags"].get("highway") in CLASSES]
    lats = [g[0] for w in ways for g in w["geometry"]]
    lons = [g[1] for w in ways for g in w["geometry"]]
    lat0, lon0 = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    xy = _project(lat0, lon0)
    nodes: dict[int, tuple[float, float]] = {}
    use: dict[int, int] = {}
    for w in ways:
        for n, g in zip(w["nodes"], w["geometry"]):
            nodes[n] = xy(*g)
            use[n] = use.get(n, 0) + 1
        use[w["nodes"][0]] += 1          # way ends are always split points
        use[w["nodes"][-1]] += 1
    links: list[Link] = []
    roads: list[dict] = []
    for w in ways:
        t = w["tags"]
        cls = t["highway"]
        dl, kmh, rank = CLASSES[cls]
        oneway = t.get("oneway") in ("yes", "1", "true") or t.get("junction") == "roundabout"
        reverse = t.get("oneway") == "-1"
        try:
            total = int(str(t.get("lanes", "")).split(";")[0])
        except ValueError:
            total = 0
        per_dir = (total if oneway else max(1, total // 2)) if total else dl
        layer = int(t.get("layer", 1 if t.get("bridge") else -1 if t.get("tunnel") else 0) or 0)
        name = t.get("name:en") or t.get("name") or ""
        ns = w["nodes"]
        cut = [i for i, n in enumerate(ns) if i in (0, len(ns) - 1) or use[n] > 1]
        for i0, i1 in zip(cut, cut[1:]):
            seg = ns[i0:i1 + 1]
            pts = [nodes[n] for n in seg]
            length = _polylen(pts)
            if length < 0.5:
                continue
            road = len(roads)
            roads.append({"pts": [[round(x, 1), round(y, 1)] for x, y in pts], "cls": cls, "lanes": per_dir,
                          "oneway": oneway, "layer": layer, "name": name, "bridge": bool(t.get("bridge")),
                          "tunnel": bool(t.get("tunnel"))})
            dirs = [False] if oneway and not reverse else [True] if oneway and reverse else [False, True]
            for back in dirs:
                p = pts[::-1] if back else pts
                a, b = (seg[-1], seg[0]) if back else (seg[0], seg[-1])
                links.append(Link(len(links), a, b, p, length, cls, per_dir, kmh / 3.6, rank, layer, name,
                                  oneway, road, t.get("junction") == "roundabout", back))
    by_a: dict[int, list[Link]] = {}
    for lk in links:
        by_a.setdefault(lk.a, []).append(lk)
    net = Network(links, nodes, roads, {s["id"] for s in raw.get("signals", [])},
                  (min(x for x, _ in nodes.values()), min(y for _, y in nodes.values()),
                   max(x for x, _ in nodes.values()), max(y for _, y in nodes.values())),
                  (lat0, lon0), raw["licence"])
    # a node in the middle of a flyover or underpass (where its way carries on at the same layer)
    # is not a junction with whatever OSM joined to it at ground level
    raised_in = {lk.b for lk in links if lk.layer != 0}
    raised_out = {lk.a for lk in links if lk.layer != 0}
    mid_span = raised_in & raised_out
    for lk in links:
        cand = by_a.get(lk.b, [])
        if lk.b in mid_span:
            cand = [o for o in cand if o.layer == lk.layer]
        lk.out = [o for o in cand if not (o.b == lk.a and o.road == lk.road)] or cand   # a dead end may turn round
        net.into.setdefault(lk.b, []).append(lk)
    _keep_strongly_connected(net)
    return net


def _keep_strongly_connected(net: Network) -> None:
    """Drop links outside the biggest strongly connected part: a trip must be able to get back out."""
    fwd: dict[int, list[int]] = {}
    rev: dict[int, list[int]] = {}
    for lk in net.links:
        fwd.setdefault(lk.a, []).append(lk.b)
        rev.setdefault(lk.b, []).append(lk.a)
    # Kosaraju, iterative
    order, seen = [], set()
    for s in fwd:
        if s in seen:
            continue
        stack = [(s, iter(fwd.get(s, ())))]
        seen.add(s)
        while stack:
            n, it = stack[-1]
            nxt = next((m for m in it if m not in seen), None)
            if nxt is None:
                order.append(n)
                stack.pop()
            else:
                seen.add(nxt)
                stack.append((nxt, iter(fwd.get(nxt, ()))))
    comp, best, seen = {}, None, set()
    for s in reversed(order):
        if s in seen:
            continue
        group, stack = [], [s]
        seen.add(s)
        while stack:
            n = stack.pop()
            group.append(n)
            for m in rev.get(n, ()):
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        if best is None or len(group) > len(best):
            best = group
    keep = set(best or ())
    kept = [lk for lk in net.links if lk.a in keep and lk.b in keep]
    alive = {id(lk) for lk in kept}
    for i, lk in enumerate(kept):
        lk.id = i
    for lk in kept:
        lk.out = [o for o in lk.out if id(o) in alive]
    net.links = kept
    net.into = {}
    for lk in kept:
        net.into.setdefault(lk.b, []).append(lk)


def junctions(net: Network) -> dict[int, list[Link]]:
    """Nodes where three or more road pieces meet: node -> links arriving there."""
    deg: dict[int, set] = {}
    for lk in net.links:
        deg.setdefault(lk.a, set()).add(lk.road)
        deg.setdefault(lk.b, set()).add(lk.road)
    return {n: net.into.get(n, []) for n, r in deg.items() if len(r) >= 3}


def signal_sites(net: Network) -> list[list[int]]:
    """Signalised junctions as groups of nodes: mapped signals, plus at-grade crossings of
    two differently named roads, one secondary or bigger and the other at least tertiary
    (not roundabouts, not under a flyover).
    A divided road crossing another makes up to four OSM nodes a few metres apart; nodes
    within 45 m are one junction with one controller."""
    sites = []
    for n, arriving in junctions(net).items():
        big = [lk for lk in arriving if lk.rank >= 3 and not lk.roundabout and "_link" not in lk.cls and lk.name]
        crossing = (len({lk.name for lk in big}) >= 2 and len({lk.layer for lk in big}) == 1
                    and max((lk.rank for lk in big), default=0) >= 4)
        if n in net.signals_osm or crossing:
            sites.append(n)
    groups: list[list[int]] = []
    for n in sorted(sites):
        x, y = net.nodes[n]
        g = next((g for g in groups if any(math.dist((x, y), net.nodes[m]) < 45 for m in g)), None)
        if g is None:
            groups.append([n])
        else:
            g.append(n)
    return groups


def shortest(net: Network, src: int, dst: int, weight=None) -> list[int] | None:
    """Fastest link sequence from node src to node dst (free-flow time by default)."""
    if weight is None:
        weight = lambda lk: lk.length / lk.speed
    out_of: dict[int, list[Link]] = getattr(net, "_out_of", None)
    if out_of is None:
        out_of = {}
        for lk in net.links:
            out_of.setdefault(lk.a, []).append(lk)
        net._out_of = out_of
    dist = {src: 0.0}
    prev: dict[int, Link] = {}
    q = [(0.0, src)]
    while q:
        d, n = heapq.heappop(q)
        if n == dst:
            break
        if d > dist.get(n, math.inf):
            continue
        for lk in out_of.get(n, ()):
            nd = d + weight(lk)
            if nd < dist.get(lk.b, math.inf):
                dist[lk.b] = nd
                prev[lk.b] = lk
                heapq.heappush(q, (nd, lk.b))
    if dst not in prev:
        return None
    route, n = [], dst
    while n != src:
        lk = prev[n]
        route.append(lk.id)
        n = lk.a
    return route[::-1]
