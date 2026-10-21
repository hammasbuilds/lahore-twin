"""Phase 6: smog, underpass flooding and streetlights on Lahore's real roads.

    python demo_city.py              # seed 7; writes viewer/city_replay.js (about 6 minutes)
    python demo_city.py --no-write
"""

from __future__ import annotations

import argparse
import time

from lahore_twin.export_city import run_all, write
from lahore_twin.summary import write as write_summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--per-hour", type=int, default=8000)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    t = time.perf_counter()
    r = run_all(seed=a.seed, per_hour=a.per_hour)
    print(f"three city systems on the same roads ({time.perf_counter() - t:.0f} s)\n")
    m = r["smog"]["metrics"]
    print("Smog, a November evening (PM2.5, µg/m³):")
    print(f"  area mean at the peak {m['area_mean_peak']}, worst street cell {m['worst_cell_peak']}")
    print(f"  map error near roads: one official monitor {m['map_error_today']}, 25 sensors + loop counts {m['map_error_sensors']}")
    print(f"  hotspot found {m['hotspot_found_m']} m from the true one; adaptive signals there: "
          f"{m['hotspot_before']} -> {m['hotspot_after']} ({m['adaptive_signals']} signals)")
    print("\nUnderpass flooding, a monsoon storm with an 18:25-19:05 power cut:")
    for mode, v in r["flood"]["modes"].items():
        print(f"  {mode:9} deepest {max(v['max_depth'].values())} m, stranded {v['stranded']}, gridlocked {v['gridlocked']}, "
              f"rerouted {v['rerouted']}, trips finished {v['completed']}, median delay {v['delay_median_s']} s")
    L = r["lights"]
    print(f"\nStreetlights, 23:00-05:00 ({L['lamp_count']:,} lamps, load-shedding 01:00-02:00 on the east feeder):")
    for mode, v in L["modes"].items():
        print(f"  {mode:9} {v['kwh']:,} kWh, busy road-minutes in the dark {v['busy_road_minutes_dark']:,}, "
              f"failed lamps known by morning {v['failures_known_by_morning']} of {len(L['fails'])}")
    if not a.no_write:
        p = write(r)
        write_summary()
        print(f"\nwrote {p} ({p.stat().st_size / 1e6:.2f} MB) - open viewer/index.html")


if __name__ == "__main__":
    main()
