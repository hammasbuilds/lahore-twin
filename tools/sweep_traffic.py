"""Traffic invariants over several mornings and demand levels (~10 min).

    python tools/sweep_traffic.py

For each seed and demand: nobody stands still at the end or never gets onto the map,
nobody drives faster than the road and vehicle allow, and adaptive signals are compared
with fixed ones. Prints one line per run and the problems found.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lahore_twin.roads import load  # noqa: E402
from lahore_twin.traffic_sim import KINDS, SAMPLE, TrafficSim, make_demand  # noqa: E402


def main() -> None:
    net = load()
    problems = []
    print("seed  per_hour  mode       trips  done  stuck  waiting  delay_med  stops  sig_vh  speed  secs")
    for seed in (11, 12, 13):
        for per_hour in (4000, 8000, 12000):
            trips = make_demand(net, seed=seed, minutes=45, per_hour=per_hour)
            res = {}
            for mode in ("fixed", "adaptive"):
                t = time.time()
                s = TrafficSim(net, trips, mode, minutes=45).run()
                m = s.metrics()
                stuck = m["gridlocked"]          # standing still for more than five minutes
                # fastest any vehicle covered between samples, against what its road allowed
                over = 0
                for v in s.vehicles:
                    cap = KINDS[v.kind][7]
                    for (t0, r0, p0, _), (t1, r1, p1, _) in zip(v.samples, v.samples[1:]):
                        d = sum(s.links[l].length for l in v.route[r0:r1]) + p1 - p0
                        if d / (t1 - t0) > min(cap, max(s.links[l].speed for l in v.route[r0:r1 + 1]) * 1.05) + 0.5:
                            over += 1
                            break
                res[mode] = m
                print(f"{seed:4}  {per_hour:8}  {mode:9}  {m['trips']:5}  {m['completed']:4}  {stuck:5}  "
                      f"{m['not_yet_entered']:7}  {m['delay_median_s']:9}  {m['stops_mean']:5}  "
                      f"{m['signal_delay_veh_h']:6}  {m['speed_mean_kmh']:5}  {time.time() - t:4.0f}", flush=True)
                if stuck:
                    problems.append((seed, per_hour, mode, f"{stuck} vehicles gridlocked (still for over 5 min)"))
                if m["not_yet_entered"]:
                    problems.append((seed, per_hour, mode, f"{m['not_yet_entered']} never got onto the map"))
                if over:
                    problems.append((seed, per_hour, mode, f"{over} vehicles faster than road or vehicle allow"))
            if res["adaptive"]["signal_delay_veh_h"] > res["fixed"]["signal_delay_veh_h"]:
                problems.append((seed, per_hour, "both", "adaptive signals held vehicles longer than fixed"))
    print(f"\nPROBLEMS: {len(problems)}")
    for p in problems:
        print("  ", p)


if __name__ == "__main__":
    main()
