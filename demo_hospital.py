"""Simulate one day at the Lahore General Hospital ED and medical ward under two rule sets.

    python demo_hospital.py                 # seed 7, writes viewer/hospital_replay.js
    python demo_hospital.py --days 5        # also report five other days

Then open viewer/hospital.html (no server needed).
"""

from __future__ import annotations

import argparse
import statistics
import time

from lahore_twin.export_hospital import run_all, write
from lahore_twin.hospital import build, describe
from lahore_twin.hospital_sim import MODES, HospitalSim
from lahore_twin.plan import Plan

ROWS = [
    ("Door to triage, median (min)", "door_to_triage_min"),
    ("Door to doctor, median (min)", "door_to_doctor_all_min"),
    ("  red (min)", lambda m: m["door_to_doctor_min"]["red"]),
    ("  green (min)", lambda m: m["door_to_doctor_min"]["green"]),
    ("Length of stay, median (min)", "los_min"),
    ("Left without being seen", "left_unseen"),
    ("Admitted to the ward", "admitted"),
    ("Hours waiting for a ward bed", "boarding_hours"),
    ("Call button answered, median (min)", "call_response_min"),
    ("  90th percentile (min)", "call_response_p90_min"),
    ("HDU alarms that sounded", "alarms_sounded"),
    ("  per ward nurse-hour", "alarms_per_nurse_hour"),
    ("Walks to false alarms", "false_alarm_trips"),
    ("Real alarm reached, median (min)", "true_alarm_response_min"),
    ("Brief real events never sounded", "brief_true_events_not_sounded"),
    ("Critical alarms reached (s)", lambda m: " / ".join(map(str, m["critical_response_s"]))),
    ("Minutes searching for equipment", "equipment_search_min"),
    ("Drips run without a pump", "drips_without_pump"),
    ("Free ED pumps at midnight", "ed_free_pumps_at_end"),
    ("Hand hygiene, true (%)", "hand_hygiene_true_pct"),
    ("Hand hygiene, as reported (%)", "hand_hygiene_reported_pct"),
    ("  reported from (n)", "hand_hygiene_reported_n"),
    ("Fridge minutes above 8 °C", "fridge_minutes_over_8C"),
    ("Bed turnaround, median (min)", "bed_turnaround_min"),
    ("Ward nurses walked (km)", "ward_nurse_km"),
]


def val(m, key):
    return key(m) if callable(key) else m[key]


def table(ms: dict) -> None:
    print(f"{'':38}" + "".join(f"{k.title():>12}" for k in MODES))
    for label, key in ROWS:
        print(f"{label:38}" + "".join(f"{str(val(ms[k], key)):>12}" for k in MODES))


def spread(seed0: int, days: int) -> None:
    ed, ward = Plan.load("hospital_ed.json"), Plan.load("hospital_ward.json")
    keys = [("Door to doctor (min)", "door_to_doctor_all_min"), ("Left unseen", "left_unseen"),
            ("Hours waiting for a bed", "boarding_hours"), ("Call p90 (min)", "call_response_p90_min"),
            ("Alarms sounded", "alarms_sounded"), ("Brief real not sounded", "brief_true_events_not_sounded"),
            ("Search (min)", "equipment_search_min"), ("Drips without pump", "drips_without_pump"),
            ("Fridge min > 8 °C", "fridge_minutes_over_8C"), ("Bed turnaround (min)", "bed_turnaround_min")]
    rows = {k: {m: [] for m in MODES} for _, k in keys}
    for d in range(1, days + 1):
        sc = build(ed, ward, seed=seed0 + d)
        for m in MODES:
            mt = HospitalSim(sc, ed, ward, m).run().metrics()
            for _, k in keys:
                rows[k][m].append(mt[k])
    print(f"\nOver {days} other days (seeds {seed0 + 1}–{seed0 + days}): median [min–max]")
    print(f"{'':28}" + "".join(f"{m.title():>22}" for m in MODES))
    for label, k in keys:
        cells = []
        for m in MODES:
            xs = [x for x in rows[k][m] if x is not None]
            cells.append(f"{statistics.median(xs):g} [{min(xs):g}–{max(xs):g}]" if xs else "–")
        print(f"{label:28}" + "".join(f"{c:>22}" for c in cells))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    t = time.perf_counter()
    replay, sims = run_all(seed=a.seed)
    sc = sims[MODES[0]].sc
    print(f"Lahore General Hospital, seed {a.seed}: ED + 36-bed medical ward, {len(sc.staff)} staff shifts, "
          f"both rule sets in {time.perf_counter() - t:.1f} s")
    print(describe(sc))
    print(f"Campus path ED -> ward: {replay['site']['path_m']} m (OpenStreetMap footprints)\n")
    table({k: s.metrics() for k, s in sims.items()})
    if not a.no_write:
        p = write(replay)
        print(f"\nwrote {p} ({p.stat().st_size / 1e6:.2f} MB) - open viewer/hospital.html")
    if a.days:
        spread(a.seed, a.days)


if __name__ == "__main__":
    main()
