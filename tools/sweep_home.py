"""Check the home's invariants over seasons, feeder categories and days.

    python tools/sweep_home.py          # 2 seasons x 3 categories x 5 days, ~10 minutes

GridSense (both profiles) must never be darker than the default setup, never trip
the inverter, never flap an AC, never let the roof tank run dry, and finish every
job by its deadline. Prints means per cell and every violation; exits 1 on any.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lahore_twin.climate import SEASONS
from lahore_twin.home import build
from lahore_twin.home_sim import HomeSim
from lahore_twin.plan import Plan

MODES = ("default", "ups", "gridsense_eco", "gridsense")


def flaps(sim) -> int:
    changes: dict[str, list[int]] = {}
    for t, aid, _, _ in sim.dev_changes:
        if aid.startswith("ac:"):
            changes.setdefault(aid, []).append(t)
    n = 0
    for ts in changes.values():
        for i in range(len(ts)):
            if len([x for x in ts[i:] if x - ts[i] <= 600]) > 3:
                n += 1
    return n


def main() -> int:
    plan = Plan.load("home.json")
    problems = []
    t0 = time.time()
    print(f"{'season':<8}{'cat':<5}" + "".join(f"{m:>26}" for m in MODES))
    print(f"{'':13}" + "".join(f"{'dark / hot-sleep / Rs':>26}" for _ in MODES))
    for season in ("june", "october"):
        for cat in ("III", "IV", "V"):
            sums = {m: [0, 0, 0] for m in MODES}
            for seed in range(1, 6):
                sc = build(plan, SEASONS[season], seed=seed, category=cat)
                runs = {m: HomeSim(sc, m).run() for m in MODES}
                ms = {m: r.metrics() for m, r in runs.items()}
                for m in MODES:
                    sums[m][0] += ms[m]["house_dark_min"] / 5
                    sums[m][1] += ms[m]["hot_sleep_person_min"] / 5
                    sums[m][2] += ms[m]["bill_rs"] / 5
                where = f"{season} {cat} seed {seed}"
                for m in ("gridsense_eco", "gridsense"):
                    if ms[m]["house_dark_min"] > ms["default"]["house_dark_min"]:
                        problems.append((where, m, "darker than default", ms[m]["house_dark_min"]))
                    if ms[m]["overload_trips"]:
                        problems.append((where, m, "overload trips", ms[m]["overload_trips"]))
                    if flaps(runs[m]):
                        problems.append((where, m, "AC flapping", flaps(runs[m])))
                    if ms[m]["tank_empty_min"]:
                        problems.append((where, m, "tank ran dry", ms[m]["tank_empty_min"]))
                    if ms[m]["jobs_late"]:
                        problems.append((where, m, "jobs late", ms[m]["jobs_late"]))
            print(f"{season:<8}{cat:<5}" + "".join(
                f"{sums[m][0]:>8.0f} /{sums[m][1]:>6.0f} /{sums[m][2]:>6.0f}  " for m in MODES))
    print(f"\n{time.time() - t0:.0f} s; PROBLEMS: {len(problems)}")
    for p in problems:
        print(" ", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
