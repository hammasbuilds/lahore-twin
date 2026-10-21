"""Run phase 6 (smog, underpass flooding, streetlights) and write viewer/city_replay.js.

The area's roads once; smog as whole µg/m³ on the 100 m grid every 2 minutes (truth and each
network's map); flood depths every 30 s per underpass and rule set; streetlights as the minutes
each road piece changes level, per rule set.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import city
from .export import ROOT, source_digest
from .roads import CLASSES, load

EVERY = 2          # minutes between smog frames


def run_all(seed: int = 7, per_hour: int = 8000) -> dict:
    net = load()
    S = city.smog(seed=seed, per_hour=per_hour)
    F = city.flood(seed=seed, per_hour=max(2000, int(per_hour * 0.75)))
    # the night's traffic scales with the evening's: 900 trips an hour at night for 8,000 at the peak
    L = city.streetlights(seed=seed, per_hour=max(200, round(per_hour * 900 / 8000)))
    g = S["grid"]
    frames = list(range(0, S["minutes"], EVERY))
    peak = range(max(0, S["minutes"] - 15), S["minutes"])

    def avg(fieldset):
        return [round(sum(fieldset[m][k] for m in peak) / len(peak)) for k in range(g.nx * g.ny)]

    classes = list(CLASSES)
    roads = [[classes.index(r["cls"]), r["layer"], [round(c) for p in r["pts"] for c in p]] for r in net.roads]
    return {
        "meta": {"seed": seed, "per_hour": per_hour, "digest": source_digest("city"), "licence": net.licence,
                 "bbox": [round(v, 1) for v in net.bbox], "smog_start": 17.5 * 3600, "flood_start": 18 * 3600,
                 "night_start": city.NIGHT_START},
        "classes": classes,
        "roads": roads,
        "smog": {
            "grid": {"x0": round(g.x0, 1), "y0": round(g.y0, 1), "nx": g.nx, "ny": g.ny, "cell": city.CELL},
            "frames": [EVERY * i for i in range(len(frames))],
            "truth": [[round(v) for v in S["truth"][m]] for m in frames],
            "sensors_map": [[round(v) for v in S["est_conn"][m]] for m in frames],
            "official_map": [round(S["est_today"][m]) for m in frames],
            "after_peak": avg(S["after"]), "truth_peak": avg(S["truth"]),
            "sensors": [{"name": s["name"], "kind": s["kind"], "x": round(s["x"], 1), "y": round(s["y"], 1),
                         "gain": round(s["gain"], 2)} for s in S["sensors"]],
            "readings": [S["readings"][m] for m in frames],
            "official": {"name": S["official"]["name"], "x": round(S["official"]["x"], 1), "y": round(S["official"]["y"], 1)},
            "hotspot": S["hotspot"], "metrics": S["metrics"], "minutes": S["minutes"], "trips": S["trips"],
        },
        "flood": {k: F[k] for k in ("underpasses", "modes", "rain", "power_cut", "generator", "trips", "minutes")},
        "lights": {
            "roads": L["roads"], "lamps": [L["lamps"][i] for i in L["roads"]], "main": [int(L["main"][i]) for i in L["roads"]],
            "fails": L["fails"], "minutes": L["minutes"], "trips": L["trips"], "lamp_count": L["lamp_count"],
            "night_full_kwh": L["night_full_kwh"], "outage": list(city.OUTAGE), "dim": city.DIM,
            "modes": {m: {"kwh": v["kwh"], "busy_road_minutes_dark": v["busy_road_minutes_dark"],
                          "busy_road_minutes_lit": v["busy_road_minutes_lit"], "kw": v["kw"],
                          "failures_known_by_morning": v["failures_known_by_morning"],
                          "changes": [v["changes"][i] for i in L["roads"]]} for m, v in L["modes"].items()},
            "east_of": round((net.bbox[0] + net.bbox[2]) / 2, 1),
        },
    }


def write(replay: dict, out: Path | None = None) -> Path:
    out = out or ROOT / "viewer" / "city_replay.js"
    out.write_bytes(("window.CITY = " + json.dumps(replay, separators=(",", ":"), ensure_ascii=False) + ";\n").encode("utf-8"))
    return out
