"""Phase 5: fix the evening's worst junctions, and get Rescue 1122 through the peak.

    python demo_junctions.py              # seed 7, 8,000 trips an hour, 30 minutes; writes viewer/junctions_replay.js
    python demo_junctions.py --no-write

Every fix and every way of running the signals meets exactly the same trips (about 4 minutes).
"""

from __future__ import annotations

import argparse
import time

from lahore_twin.export_junctions import run_all, write
from lahore_twin.junctions import FIX_NAMES
from lahore_twin.summary import write as write_summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--per-hour", type=int, default=8000)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    t = time.perf_counter()
    replay, R = run_all(seed=a.seed, per_hour=a.per_hour)
    print(f"{replay['meta']['trips']:,} trips in 30 minutes of evening peak, every scenario on the same trips "
          f"({time.perf_counter() - t:.0f} s)\n")
    for j in replay["junctions"]:
        print(f"{j['name']}  (main road: {', '.join(j['main'])})")
        print(f"  {'fix':22}{'lost here, veh-h':>17}{'queue peak':>12}{'median delay':>14}{'extra km':>10}  pedestrians")
        for f, r in j["fixes"].items():
            print(f"  {FIX_NAMES[f]:22}{r['junction_veh_h']:>17}{r['queue_peak']:>12}{r['delay_median_s']:>12} s"
                  f"{r['km_extra']:>10}  {r['pedestrian_crossing']}")
        print()
    print("Rescue 1122, calls from the station in Gulberg (mean seconds):")
    for mode, s in replay["ambulance"]["summary"].items():
        print(f"  {mode:10} to the call {s['response_mean_s']:>4}   to hospital {s['to_hospital_mean_s']:>4}   "
              f"reds faced {s['reds']:>3}   signals preempted {s['preemptions']:>3}   everyone else's median delay "
              f"{s['network_delay_median_s']} s")
    if not a.no_write:
        p = write(replay)
        write_summary()
        print(f"\nwrote {p} ({p.stat().st_size / 1e6:.2f} MB) - open viewer/index.html")


if __name__ == "__main__":
    main()
