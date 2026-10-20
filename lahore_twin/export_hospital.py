"""Run the hospital day under both rule sets and write viewer/hospital_replay.js."""

from __future__ import annotations

import json
from pathlib import Path

from .export import ROOT, source_digest
from .hospital import COLOURS, ROLE_COLOURS, build, describe
from .hospital_site import site
from .hospital_sim import MODES, HospitalSim
from .plan import Plan

TRIAGE_HEX = {"red": "#ef4444", "orange": "#f97316", "yellow": "#eab308", "green": "#22c55e", "blue": "#3b82f6"}


def mode_replay(s: HospitalSim) -> dict:
    metrics = s.metrics()             # first: it fills in when each call and alarm was answered
    agents = {}
    for a in s.agents.values():
        rec = s.records.get(a.id)
        agents[a.id] = {"name": a.name, "role": a.role, "unit": a.unit,
                        "colour": TRIAGE_HEX[rec["colour"]] if rec else ROLE_COLOURS[a.role],
                        "triage": rec["colour"] if rec else None}
    log = [{"id": m.id, "t": m.t, "topic": m.topic, "text": m.text, "cause": m.cause}
           for m in s.bus.log if m.text]
    alarms = [{k: v for k, v in r.items() if k in ("t", "bed", "kind", "annunciated", "arrived", "hidden")}
              for r in s.alarm_log]
    calls = [{k: v for k, v in c.items() if k in ("t", "bed", "noticed", "arrived", "how")} for c in s.call_log]
    return {
        "agents": agents,
        "trips": s.trips,
        "presence": s.presence,
        "labels": s.labels,
        "assets": s.asset_ev,
        "beds": s.bed_ev,
        "records": list(s.records.values()),
        "census": s.census,
        "fridge": s.fridge_series,
        "fridge_events": [{k: v for k, v in e.items() if k != "alert_id"} for e in s.fridge_events],
        "alarms": alarms,
        "calls": calls,
        "fetches": s.fetch_log,
        "log": log,
        "metrics": metrics,
    }


def run_all(seed: int = 7, arrivals_pct: float = 100, ward_nurses: int | None = None,
            alarm_delay: int = 15) -> tuple[dict, dict[str, HospitalSim]]:
    ed, ward = Plan.load("hospital_ed.json"), Plan.load("hospital_ward.json")
    sc = build(ed, ward, seed=seed, arrivals_pct=arrivals_pct, ward_nurses=ward_nurses, alarm_delay=alarm_delay)
    sims = {m: HospitalSim(sc, ed, ward, m).run() for m in MODES}
    st = site()
    replay = {
        "meta": {"seed": seed, "t0": 0, "t1": 86400, "digest": source_digest("hospital"), "describe": describe(sc),
                 "arrivals_pct": arrivals_pct, "alarm_delay": sc.alarm_delay,
                 "audit": list(sc.audit), "true_hand_hygiene": sc.true_hand_hygiene},
        "plans": {"ed": ed.to_json() | {"outline": ed.raw["outline"]},
                  "ward": ward.to_json() | {"outline": ward.raw["outline"]}},
        "site": {k: st[k] for k in ("size", "campus", "buildings", "path", "path_m", "ed_origin", "ward",
                                    "rotation_deg", "licence", "ed_exit", "ward_entry")},
        "assets": [{"id": a.id, "kind": a.kind} for a in sc.assets],
        "beds": {b.id: {"unit": b.unit, "room": b.room, "spot": list(b.spot)} for b in sims[MODES[0]].beds.values()},
        "triage": {c: TRIAGE_HEX[c] for c in COLOURS},
        "roles": ROLE_COLOURS,
        "modes": {m: mode_replay(s) for m, s in sims.items()},
    }
    return replay, sims


def write(replay: dict, out: Path | None = None) -> Path:
    out = out or ROOT / "viewer" / "hospital_replay.js"
    out.write_bytes(("window.HOSPITAL = " + json.dumps(replay, separators=(",", ":"), ensure_ascii=False)
                     + ";\n").encode("utf-8"))
    return out


if __name__ == "__main__":
    r, _ = run_all()
    p = write(r)
    print(f"wrote {p} ({p.stat().st_size / 1e6:.2f} MB)")
