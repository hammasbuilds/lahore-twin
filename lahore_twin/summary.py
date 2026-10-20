"""Headline numbers for the shell's overview cards, read from the committed replays.

    python -m lahore_twin.summary        # writes viewer/summary.js

Each demo calls ``write()`` after it writes its replay, so the cards always show
the day the module will open on.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"


def _load(name: str):
    p = VIEWER / name
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    first = text.split("\n", 1)[0]
    return json.loads(first[first.index("{"):].rstrip().rstrip(";"))


def build() -> dict:
    out = {}
    office = _load("replay.js")
    if office:
        m = {k: v["metrics"] for k, v in office["modes"].items()}
        base, best = m["schedule"]["total_kwh"], m["pir+co2"]["total_kwh"]
        out["office"] = {"stats": [
            [f"{(1 - best / base) * 100:.0f}%", "less light + AC energy (motion + CO₂)"],
            [str(len(office["people"])), "people on three floors"],
            [f"{m['pir+co2']['tailgates_caught']}/{m['pir+co2']['tailgates_true']}", "tailgates caught"],
        ]}
    home = _load("home_replay.js")
    home = home.get("june", home) if home else None          # the replay holds every season
    if home:
        m = {k: v["metrics"] for k, v in home["modes"].items()}
        out["home"] = {"stats": [
            [f"{m['default']['house_dark_min']} → {m['gridsense']['house_dark_min']}", "minutes dark (default → GridSense)"],
            [f"Rs {m['gridsense_eco']['bill_rs']:.0f}", "eco bill for the day"],
            [f"{m['gridsense']['hot_sleep_person_min']}", "too-hot sleep, person-min"],
        ]}
    hosp = _load("hospital_replay.js")
    if hosp:
        t, c = hosp["modes"]["today"]["metrics"], hosp["modes"]["connected"]["metrics"]
        out["hospital"] = {"stats": [
            [f"{t['alarms_sounded']} → {c['alarms_sounded']}", "alarms that sounded"],
            [f"{t['equipment_search_min']:.0f} → {c['equipment_search_min']:.0f}", "minutes searching for kit"],
            [f"{t['bed_turnaround_min']:.0f} → {c['bed_turnaround_min']:.0f}", "bed turnaround, min"],
        ]}
    traffic = _load("traffic_replay.js")
    if traffic:
        f, a = traffic["modes"]["fixed"]["metrics"], traffic["modes"]["adaptive"]["metrics"]
        out["traffic"] = {"stats": [
            [f"{f['delay_median_s']:.0f} → {a['delay_median_s']:.0f} s", "median delay (fixed → adaptive)"],
            [f"{traffic['meta']['trips']:,}", f"trips in the {traffic['meta'].get('period', 'morning')} peak"],
            [f"{f.get('errand_stops', 0):,}", "stops at real shops and amenities"],
        ]}
    return out


def write() -> Path:
    p = VIEWER / "summary.js"
    p.write_bytes(("window.TWIN_SUMMARY = " + json.dumps(build(), ensure_ascii=False, indent=1) + ";\n").encode("utf-8"))
    return p


if __name__ == "__main__":
    print(write())
