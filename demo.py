"""Simulate one office day under three rule sets and print what happened.

    python demo.py            # print the comparison, write viewer/replay.js
    python demo.py --seed 3   # a different day

Then open viewer/index.html in a browser (no server needed).
"""

from __future__ import annotations

import argparse
import time

from lahore_twin.export import run_all, write
from lahore_twin.office import clock
from lahore_twin.rules import MODES

NAMES = {"schedule": "Fixed schedule", "pir": "Motion", "pir+co2": "Motion + CO2"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-write", action="store_true", help="do not write viewer/replay.js")
    args = ap.parse_args()

    t = time.perf_counter()
    replay, sims = run_all(seed=args.seed)
    took = time.perf_counter() - t
    m = {k: s.metrics() for k, s in sims.items()}
    first = sims[MODES[0]]
    people = first.people
    roles: dict[str, int] = {}
    for p in people:
        roles[p.role] = roles.get(p.role, 0) + 1

    print(f"Office day, seed {args.seed}: {len(people)} people "
          f"({', '.join(f'{v} {k}' for k, v in roles.items())}), "
          f"{len(replay['bookings'])} bookings, 07:00-21:00, three rule sets in {took:.1f} s\n")

    rows = [("Lights + AC (kWh)", "total_kwh"), ("  lights", "light_kwh"), ("  AC", "ac_kwh"),
            ("Person-minutes in the dark", "person_min_in_dark"),
            ("Person-minutes too warm (>26 C)", "person_min_too_warm"),
            ("Person-minutes stuffy (CO2 >1000)", "person_min_stuffy"),
            ("Lights switched off on someone", "false_offs"),
            ("Room-minutes lit while empty", "room_min_lit_empty")]
    w = 36
    print(f"{'':{w}}" + "".join(f"{NAMES[k]:>16}" for k in MODES))
    for label, key in rows:
        print(f"{label:{w}}" + "".join(f"{m[k][key]:>16}" for k in MODES))
    base = m["schedule"]["total_kwh"]
    for k in MODES[1:]:
        print(f"  {NAMES[k]}: {100 * (1 - m[k]['total_kwh'] / base):.1f}% less energy than the fixed schedule")

    a = m["pir+co2"]
    print("\nGate and attendance (identical in every rule set)")
    print(f"  people on site                 {a['people_on_site']}")
    print(f"  in the register by day's end   {a['register_count']}"
          + (f"  (missing: {', '.join(a['missing_from_register'])})" if a['missing_from_register'] else ""))
    print(f"  tailgates                      {a['tailgates_true']} happened, {a['tailgates_caught']} caught, "
          f"{a['tailgate_false_alarms']} false alarms")
    print(f"  door-counter misses            {a['beam_misses']}")

    print("\nAlerts under Motion + CO2")
    for msg in sims["pir+co2"].bus.log:
        if msg.topic.startswith("office/alert/"):
            print(f"  {clock(msg.t)}  {msg.text}")

    if not args.no_write:
        path = write(replay)
        print(f"\nwrote {path} ({path.stat().st_size / 1e6:.2f} MB) - open viewer/index.html")


if __name__ == "__main__":
    main()
