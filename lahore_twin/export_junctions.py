"""Run phase 5 (junction planner + ambulance green wave) and write viewer/junctions_replay.js.

For each of the evening's worst junctions: the roads around it, and every fix's results on
the same trips. For each Rescue 1122 call: its route, the signals on it, and the ambulance's
distance along the route against time under each way of running the signals.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from . import junctions as J
from .export import ROOT, source_digest
from .roads import CLASSES, load
from .traffic_sim import build_signals, snap_pois

AROUND_M = 450                    # the close map shows the roads this far from the junction


def _route_line(net, route) -> list[float]:
    pts = []
    for lid in route:
        for x, y in net.links[lid].pts[(1 if pts else 0):]:
            pts += [round(x, 1), round(y, 1)]
    return pts


def _greens(log, phase: int, t1: int) -> list[list[int]]:
    """[start, end] intervals in which `phase` showed green."""
    out, start = [], None
    if not log or log[0][0] > 0:
        start = 0 if phase == 0 else None          # every controller starts on phase 0, green
    for t, ph, st in log:
        if st == "green" and ph == phase:
            start = t
        elif start is not None and not (st == "green" and ph == phase):
            out.append([start, t])
            start = None
    if start is not None:
        out.append([start, t1])
    return out


def run_all(seed: int = 7, per_hour: int = 8000, minutes: int = 30, junctions: int = 3) -> tuple[dict, dict]:
    net = load()
    R = J.run_all(seed=seed, per_hour=per_hour, minutes=minutes, junctions=junctions)
    sigs = {s.name: s for s in build_signals(net)}
    t1 = minutes * 60 + 900
    out_j = []
    for name in R["worst"]:
        sig = sigs[name]
        cx, cy = J._centre(net, sig)
        roads = []
        for r in net.roads:
            if min(math.dist((cx, cy), p) for p in r["pts"]) < AROUND_M:
                roads.append([list(CLASSES).index(r["cls"]), r["lanes"], int(r["oneway"]), r["layer"],
                              r["name"], [round(c - o, 1) for p in r["pts"] for c, o in zip(p, (cx, cy))]])
        main_ph = 0 if sig.greens[0] >= sig.greens[1] else 1
        mv, gaps, main_links = J.uturn_conversion(net, sig)
        plan = R["plans"][name]
        out_j.append({
            "name": name, "centre": [round(cx, 1), round(cy, 1)], "roads": roads,
            "main": sorted({net.links[l].name for l in sig.phases[main_ph] if net.links[l].name}),
            "side": sorted({net.links[l].name for l in sig.phases[1 - main_ph] if net.links[l].name}),
            # each approach's stop line, relative to the centre, and its phase
            "approaches": [[ph, round(net.links[l].pts[-1][0] - cx, 1), round(net.links[l].pts[-1][1] - cy, 1),
                            round(net.links[l].pts[-2][0] - cx, 1), round(net.links[l].pts[-2][1] - cy, 1)]
                           for ph, ids in enumerate(sig.phases) for l in ids],
            "main_phase": main_ph,
            "gaps": [[round(x - cx, 1), round(y - cy, 1)] for _, x, y in gaps],
            "fixes": {f: {k: v for k, v in r.items()} for f, r in plan.items()},
        })
    # the ambulance: routes, signals along them, and traces per way
    pois = {p["i"]: p for p in snap_pois(net)}
    st = J.station(net)
    amb = R["ambulance"]
    calls = []
    base_calls = amb["none"]["calls"]
    sig_of = {}
    for s in build_signals(net):
        for ph, ids in enumerate(s.phases):
            for lid in ids:
                sig_of[lid] = (s, ph)
    for k, c in enumerate(base_calls):
        route = c["route"]
        prefix = [0.0]
        for lid in route:
            prefix.append(prefix[-1] + net.links[lid].length)
        on_route = []
        for i, lid in enumerate(route):
            if lid in sig_of:
                s, ph = sig_of[lid]
                on_route.append([round(prefix[i + 1]), s.id, ph, s.name])
        per_mode = {}
        for mode, A in amb.items():
            cc = next((x for x in A["calls"] if x["t0"] == c["t0"]), None)
            if cc is None:
                continue
            per_mode[mode] = {"response_s": cc["response_s"], "to_hospital_s": cc["to_hospital_s"], "reds": cc["reds"],
                              "trace": cc["trace"], "scene_at": cc["scene_at"],
                              "greens": [_greens(A["signal_logs"].get(str(sid), []), ph, t1) for _, sid, ph, _ in on_route]}
        # the hospital it was going to, from whichever way got there before the run ended
        hosp = next((x["hospital"] for A in amb.values() for x in A["calls"] if x["t0"] == c["t0"] and x["hospital"]), None)
        calls.append({"t0": c["t0"], "line": _route_line(net, route), "length": round(prefix[-1]),
                      "hospital": hosp, "signals": on_route, "modes": per_mode})
    summary = {}
    # compare like with like: only the calls every way got through before the run ended
    both = lambda key: {x["t0"] for x in amb["none"]["calls"]
                        if all(any(y["t0"] == x["t0"] and y[key] is not None for y in A["calls"]) for A in amb.values())}
    ok_r, ok_h = both("response_s"), both("to_hospital_s")
    for mode, A in amb.items():
        rs = [x["response_s"] for x in A["calls"] if x["t0"] in ok_r]
        hs = [x["to_hospital_s"] for x in A["calls"] if x["t0"] in ok_h]
        summary[mode] = {"response_mean_s": round(sum(rs) / len(rs)) if rs else None,
                         "to_hospital_mean_s": round(sum(hs) / len(hs)) if hs else None,
                         "reds": sum(x["reds"] for x in A["calls"]), "preemptions": A["preemptions"],
                         "network_delay_median_s": A["delay_median_s"], "signal_delay_veh_h": A["signal_delay_veh_h"],
                         "calls": len(A["calls"]), "compared_response": len(ok_r), "compared_hospital": len(ok_h)}
    replay = {
        "meta": {"seed": seed, "per_hour": per_hour, "minutes": minutes, "t1": t1, "start": 17.5 * 3600,
                 "trips": R["trips"], "digest": source_digest("junctions"), "licence": net.licence,
                 "bbox": [round(v, 1) for v in net.bbox]},
        "classes": list(CLASSES),
        "fix_names": J.FIX_NAMES,
        "junctions": out_j,
        "ambulance": {"station": [round(st[0], 1), round(st[1], 1)], "calls": calls, "summary": summary,
                      "hospitals": [[round(p["x"], 1), round(p["y"], 1), p["name"]] for p in pois.values()
                                    if p["kind"] == "hospital" and p["name"] in J.EMERGENCY]},
        # the whole area, thin, so the ambulance's route has a city around it
        "area": [[r["layer"], int(CLASSES[r["cls"]][2] >= 3), [round(c, 0) for p in r["pts"] for c in p]]
                 for r in net.roads if CLASSES[r["cls"]][2] >= 1],
    }
    return replay, R


def write(replay: dict, out: Path | None = None) -> Path:
    out = out or ROOT / "viewer" / "junctions_replay.js"
    out.write_bytes(("window.JUNCTIONS = " + json.dumps(replay, separators=(",", ":"), ensure_ascii=False)
                     + ";\n").encode("utf-8"))
    return out
