"""Run a peak hour under both signal rule sets and write viewer/traffic_replay.js.

Compact on purpose: about 7,000 vehicles. Roads are stored once; each vehicle is its
route (link ids) plus how far along it it was every SAMPLE seconds, as small integer
deltas in whole metres, plus its lane changes (lane -1: pulled off the road) and the stops
it made. The viewer rebuilds positions from those.
"""

from __future__ import annotations

import json
from pathlib import Path

from .export import ROOT, source_digest
from .roads import CLASSES, load
from .traffic_sim import KINDS, MODES, PERIODS, SAMPLE, TrafficSim, make_demand, snap_pois

TILE = 400.0                         # metres: the viewer streams the map in tiles of this size
KIND_TITLE = {"fuel": "Fuel station", "place_of_worship": "Mosque", "fast_food": "Fast food", "marketplace": "Market",
              "bank": "Bank", "school": "School", "college": "College", "university": "University", "hospital": "Hospital",
              "clinic": "Clinic", "pharmacy": "Pharmacy", "restaurant": "Restaurant", "cafe": "Cafe", "shop": "Shop",
              "mall": "Mall", "bakery": "Bakery", "supermarket": "Supermarket"}


def place_name(p: dict) -> str:
    """OpenStreetMap leaves many fuel stations and mosques unnamed: call them after their street."""
    if p["name"]:
        return p["name"]
    kind = KIND_TITLE.get(p["kind"], p["kind"].replace("_", " ").title())
    return f"{kind} on {p['road']}" if p["road"] else kind


def _mode_replay(s: TrafficSim) -> dict:
    links = s.links
    vehicles = []
    for v in s.vehicles:
        if not v.samples:
            vehicles.append([list(KINDS).index(v.kind), v.t0, v.tin, v.done, [], [], []])
            continue
        prefix = [0.0]
        for lid in v.route:
            prefix.append(prefix[-1] + links[lid].length)
        cum = [int(round(prefix[ri] + pos)) for _, ri, pos, _ in v.samples]          # whole metres
        deltas = [cum[0]] + [b - a for a, b in zip(cum, cum[1:])]
        lanes, last = [], None
        for k, (_, _, _, lane) in enumerate(v.samples):
            if lane != last:
                lanes.append([k, lane])
                last = lane
        # stops made: [start, end (null: the trip ended there), what for, place index or -1]
        vehicles.append([list(KINDS).index(v.kind), v.t0, v.samples[0][0], v.done, deltas, lanes, v.stop_log])
    return {
        "vehicles": vehicles,
        "signals": {str(sg.id): sg.log for sg in s.signals},
        "series": s.series,
        "metrics": s.metrics(),
        "node_delay": sorted(([n, round(d / 3600, 2)] for n, d in s.node_delay.items() if d > 600),
                             key=lambda x: -x[1])[:40],
    }


def run_all(seed: int = 7, minutes: int = 60, per_hour: int = 8000,
            period: str = "evening") -> tuple[dict, dict[str, TrafficSim]]:
    net = load()
    trips = make_demand(net, seed=seed, minutes=minutes, per_hour=per_hour, period=period)
    sims = {m: TrafficSim(net, trips, m, minutes=minutes).run() for m in MODES}
    classes = list(CLASSES)
    names = sorted({r["name"] for r in net.roads if r["name"]})
    nidx = {n: i for i, n in enumerate(names)}
    roads = [[classes.index(r["cls"]), r["lanes"], int(r["oneway"]), r["layer"], nidx.get(r["name"], -1),
              int(r["bridge"]), int(r["tunnel"]), [c for p in r["pts"] for c in p]] for r in net.roads]
    tiles: dict[str, list[int]] = {}
    for i, r in enumerate(net.roads):
        keys = {f"{int(x // TILE)},{int(y // TILE)}" for x, y in r["pts"]}
        for k in keys:
            tiles.setdefault(k, []).append(i)
    first = sims[MODES[0]]
    replay = {
        "meta": {"seed": seed, "minutes": minutes, "per_hour": per_hour, "t1": first.T, "sample": SAMPLE,
                 "digest": source_digest("traffic"), "licence": net.licence, "bbox": [round(v, 1) for v in net.bbox],
                 "origin": list(net.origin), "tile": TILE, "trips": len(trips),
                 "period": period, "start": PERIODS[period]},
        "classes": classes,
        "kinds": list(KINDS),
        "names": names,
        "roads": roads,
        # directed links: [road index, 1 if it runs against the road's drawing order, lanes]
        "links": [[lk.road, int(lk.back), lk.lanes] for lk in net.links],
        "tiles": tiles,
        # vehicle i drives routes[i] in every rule set (same trips), so routes are stored once
        "routes": [tr.route for tr in trips],
        "purposes": sorted({tr.purpose for tr in trips}),
        "trip_purpose": [],
        # the shops and amenities from OpenStreetMap, at the street they open onto: [x, y, kind, name]
        "pois": [],
        "poi_kinds": [],
        "signal_sites": [{"id": sg.id, "name": sg.name,
                          "xy": [round(sum(net.nodes[n][0] for n in sg.nodes) / len(sg.nodes), 1),
                                 round(sum(net.nodes[n][1] for n in sg.nodes) / len(sg.nodes), 1)],
                          "phases": sg.phases, "greens": sg.greens} for sg in first.signals],
        "modes": {m: _mode_replay(s) for m, s in sims.items()},
    }
    pidx = {p: i for i, p in enumerate(replay["purposes"])}
    replay["trip_purpose"] = [pidx[tr.purpose] for tr in trips]
    pois = snap_pois(net)
    kinds = sorted({p["kind"] for p in pois})
    replay["poi_kinds"] = kinds
    # stop logs name places by their index in the source file; the viewer gets them in this list
    at = {p["i"]: k for k, p in enumerate(pois)}
    replay["pois"] = [[round(p["x"], 1), round(p["y"], 1), kinds.index(p["kind"]), place_name(p)] for p in pois]
    for m in replay["modes"].values():
        for v in m["vehicles"]:
            for e in v[6]:
                e[3] = at.get(e[3], -1)
    return replay, sims


def write(replay: dict, out: Path | None = None) -> Path:
    out = out or ROOT / "viewer" / "traffic_replay.js"
    out.write_bytes(("window.TRAFFIC = " + json.dumps(replay, separators=(",", ":"), ensure_ascii=False)
                     + ";\n").encode("utf-8"))
    return out


if __name__ == "__main__":
    r, _ = run_all()
    p = write(r)
    print(f"wrote {p} ({p.stat().st_size / 1e6:.2f} MB)")
