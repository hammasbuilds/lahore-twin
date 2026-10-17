"""Run the home day under every controller and write viewer/home_replay.js."""

from __future__ import annotations

import json
from pathlib import Path

from .climate import SEASONS
from .export import ROOT, source_digest
from .home import CATEGORIES, build
from .home_sim import HOME_COLOURS, TARIFF, HomeSim
from .plan import Plan

MODES = ("default", "ups", "gridsense")


def run_all(seed: int = 7, season: str = "june", category: str = "IV") -> tuple[dict, dict[str, HomeSim]]:
    plan = Plan.load("home.json")
    sc = build(plan, SEASONS[season], seed=seed, category=category)
    sims = {m: HomeSim(sc, m).run() for m in MODES}
    first = sims[MODES[0]]
    replay = {
        "meta": {"seed": seed, "season": SEASONS[season].name, "category": category,
                 "category_hours": CATEGORIES[category], "t0": 0, "t1": 86400, "title": plan.name,
                 "sunrise": sc.season.sunrise, "sunset": sc.season.sunset, "peak": list(sc.season.peak),
                 "tariff": TARIFF, "day_factor": sc.day_factor, "forecast_factor": sc.forecast_factor,
                 "digest": source_digest("home")},
        "plan": plan.to_json() | {"ac_rooms": plan.ac_rooms, "fan_rooms": plan.raw.get("fan_rooms", [])},
        "appliances": [{"id": a.id, "kind": a.kind, "room": a.room, "watts": a.watts, "essential": a.essential}
                       for a in first.apps.values()],
        "wiring": {m: sorted(s.ctrl.on_inverter) for m, s in sims.items()},
        "outages": [{"start": o.start, "end": o.end, "published": o.published} for o in sc.outages],
        "requests": [{"id": r.id, "t": r.t, "appliance": r.appliance, "deadline": r.deadline,
                      "duration": r.duration, "label": r.label} for r in sc.requests],
        "people": [{"id": p.id, "name": p.name, "role": p.role, "colour": HOME_COLOURS[p.role],
                    "arrive": p.arrive, "leave": p.leave} for p in first.people],
        "trips": first.trips_log,
        "labels": first.labels,
        "modes": {m: s.replay() for m, s in sims.items()},
    }
    return replay, sims


def write(replay: dict, out: Path | None = None) -> Path:
    out = out or ROOT / "viewer" / "home_replay.js"
    out.write_bytes(("window.HOME = " + json.dumps(replay, separators=(",", ":"), ensure_ascii=False)
                     + ";\n").encode("utf-8"))
    return out


if __name__ == "__main__":
    r, _ = run_all()
    p = write(r)
    print(f"wrote {p} ({p.stat().st_size / 1e6:.2f} MB)")
