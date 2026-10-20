"""Simulate a morning peak on real Lahore roads (Gulberg, Kalma Chowk, Canal Road) under
fixed and adaptive signals, and print what happened.

    python demo_traffic.py                    # seed 7, 8,000 trips an hour; writes viewer/traffic_replay.js
    python demo_traffic.py --per-hour 11000   # a heavier morning

Then open viewer/index.html (or viewer/traffic.html) — no server needed.
"""

from __future__ import annotations

import argparse
import time

from lahore_twin.export_traffic import run_all, write
from lahore_twin.roads import load
from lahore_twin.summary import write as write_summary
from lahore_twin.traffic_sim import MODES

ROWS = [("Trips", "trips"), ("Finished", "completed"), ("Median travel time (s)", "travel_time_median_s"),
        ("Median delay (s)", "delay_median_s"), ("Mean delay (s)", "delay_mean_s"),
        ("Total delay (vehicle-hours)", "delay_total_veh_h"), ("Stops per trip", "stops_mean"),
        ("Mean speed (km/h)", "speed_mean_kmh"), ("Stopped at signals (vehicle-hours)", "signal_delay_veh_h"),
        ("Still driving at the end", "still_driving"), ("Never got onto the road", "not_yet_entered")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--per-hour", type=int, default=8000)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    net = load()
    bridges = sum(1 for r in net.roads if r["layer"] > 0)
    tunnels = sum(1 for r in net.roads if r["layer"] < 0)
    t = time.perf_counter()
    replay, sims = run_all(seed=a.seed, per_hour=a.per_hour)
    print(f"Gulberg / Kalma Chowk / Canal Road from OpenStreetMap: {len(net.roads):,} road pieces, "
          f"{len(net.links):,} directed links, {bridges} flyover and {tunnels} underpass pieces, "
          f"{len(sims[MODES[0]].signals)} signals — both rule sets in {time.perf_counter() - t:.0f} s\n")
    ms = {m: s.metrics() for m, s in sims.items()}
    print(f"{'':38}" + "".join(f"{m.title():>12}" for m in MODES))
    for label, key in ROWS:
        print(f"{label:38}" + "".join(f"{str(ms[m][key]):>12}" for m in MODES))
    print("\nWorst junctions under fixed signals (vehicle-hours stopped within 60 m):")
    for name, vh in ms["fixed"]["worst_junctions"][:5]:
        print(f"  {vh:6.2f}  {name}")
    if not a.no_write:
        p = write(replay)
        write_summary()
        print(f"\nwrote {p} ({p.stat().st_size / 1e6:.2f} MB) - open viewer/index.html")


if __name__ == "__main__":
    main()
