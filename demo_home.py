"""Simulate one day in a Lahore house under three controllers and print what happened.

    python demo_home.py                         # June, feeder category IV, seed 7
    python demo_home.py --season october --category V --seed 3
    python demo_home.py --days 10               # also report ten different days

Then open viewer/home.html (no server needed).
"""

from __future__ import annotations

import argparse
import time

from lahore_twin.export_home import MODES, run_all, write
from lahore_twin.home import describe

NAMES = {"default": "Inverter default", "ups": "UPS circuit", "gridsense": "GridSense"}
ROWS = [("House dark (min)", "house_dark_min"), ("No fan when wanted (person-min)", "no_fan_person_min"),
        ("Too hot to sleep (person-min)", "hot_sleep_person_min"),
        ("Too hot awake (person-min)", "hot_awake_person_min"), ("Roof tank empty (min)", "tank_empty_min"),
        ("Grid at peak price (kWh)", "grid_peak_kwh"), ("Grid off-peak (kWh)", "grid_offpeak_kwh"),
        ("Exported (kWh)", "export_kwh"), ("Solar used at home (%)", "solar_used_pct"),
        ("Solar wasted (kWh)", "solar_wasted_kwh"), ("Day's bill (Rs)", "bill_rs"),
        ("Inverter overload trips", "overload_trips"), ("AC/fridge below 190 V (min)", "low_voltage_stress_min")]


def table(m: dict) -> None:
    w = 34
    print(f"{'':{w}}" + "".join(f"{NAMES[k]:>18}" for k in MODES))
    for label, key in ROWS:
        print(f"{label:{w}}" + "".join(f"{m[k][key]:>18}" for k in MODES))
    print(f"{'Jobs finished late':{w}}" + "".join(f"{len(m[k]['jobs_late']):>18}" for k in MODES))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--season", default="june", choices=("june", "october"))
    ap.add_argument("--category", default="IV", choices=("I", "III", "IV", "V"))
    ap.add_argument("--days", type=int, default=0, help="also run this many other days and report the spread")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()

    t = time.perf_counter()
    replay, sims = run_all(seed=a.seed, season=a.season, category=a.category)
    sc = sims[MODES[0]].sc
    print(f"{sc.season.name}, seed {a.seed}, {len(sc.people)} people, 6 kWp solar, 10 kWh battery, "
          f"6 kW inverter — three controllers in {time.perf_counter() - t:.1f} s")
    print(describe(sc))
    print(f"Solar: {'clear' if sc.day_factor >= 0.95 else 'hazy' if sc.day_factor >= 0.7 else 'overcast'} day\n")
    table({k: s.metrics() for k, s in sims.items()})
    print("\nGridSense decisions:")
    for m in sims["gridsense"].bus.log:
        if m.topic == "home/inverter/settings" or "pre-cool" in m.text or "fill the tank" in m.text \
                or "outage: battery" in m.text or "solar surplus" in m.text and "washer" in m.topic:
            print(f"  {m.t // 3600:02d}:{m.t % 3600 // 60:02d}  {m.text}")
    if a.days:
        spread(a)
    if not a.no_write:
        p = write(replay)
        print(f"\nwrote {p} ({p.stat().st_size / 1e6:.2f} MB) - open viewer/home.html")


def spread(a) -> None:
    from lahore_twin.climate import SEASONS
    from lahore_twin.home import build
    from lahore_twin.home_sim import HomeSim
    from lahore_twin.plan import Plan
    plan = Plan.load("home.json")
    rows = []
    for seed in range(1, a.days + 1):
        sc = build(plan, SEASONS[a.season], seed=seed, category=a.category)
        rows.append({k: HomeSim(sc, k).run().metrics() for k in MODES})
    print(f"\n{a.days} days, {SEASONS[a.season].name}, category {a.category} (mean, worst day)")
    for label, key in ROWS:
        cells = []
        for k in MODES:
            v = [r[k][key] for r in rows]
            cells.append(f"{sum(v) / len(v):.1f} / {max(v):g}")
        print(f"  {label:<34}" + "".join(f"{c:>18}" for c in cells))


if __name__ == "__main__":
    main()
