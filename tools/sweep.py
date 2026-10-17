"""Check invariants over many simulated days.

    python tools/sweep.py          # 20 days, about 5 minutes

Every arrival leaves, nobody is inside at 21:00, the register misses only
tailgaters, Motion + CO2 beats the schedule on energy and Motion on false-offs,
and the gate behaves identically under every rule set. Exits 1 on any problem.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lahore_twin.office import build, hm
from lahore_twin.plan import Plan
from lahore_twin.sim import Sim
plan = Plan.load("office.json")
problems = []
rows = []
t0 = time.time()
for seed in range(1, 21):
    try:
        sc = build(plan, seed=seed)
        sims = {m: Sim(sc, m).run() for m in ("schedule", "pir", "pir+co2")}
    except Exception as e:
        problems.append((seed, "crash", repr(e))); continue
    m = {k: s.metrics() for k, s in sims.items()}
    s = sims["pir+co2"]
    stuck = [p.id for p in s.people if p.on_site]
    if stuck: problems.append((seed, "still on site at 21:00", stuck))
    noleave = [p.id for p in s.people if p.arrive < hm("20:30") and not p.gone]
    if noleave: problems.append((seed, "never left", noleave))
    tg = {pid for _, pid in s.truth.tailgates}
    if not set(m["pir+co2"]["missing_from_register"]) <= tg:
        problems.append((seed, "missing from register, not a tailgater", m["pir+co2"]["missing_from_register"]))
    if not m["pir+co2"]["total_kwh"] < m["schedule"]["total_kwh"]:
        problems.append((seed, "co2 mode not cheaper", m["pir+co2"]["total_kwh"], m["schedule"]["total_kwh"]))
    if not m["pir+co2"]["false_offs"] <= m["pir"]["false_offs"]:
        problems.append((seed, "co2 mode more false-offs", m["pir+co2"]["false_offs"], m["pir"]["false_offs"]))
    g = [{k: x[k] for k in ("tailgates_true", "tailgates_caught", "beam_misses")} for x in m.values()]
    if not g[0] == g[1] == g[2]: problems.append((seed, "gate differs by mode", g))
    if s.series["roll_truth"][-1] != 0: problems.append((seed, "roll-call truth not 0 at end", s.series["roll_truth"][-1]))
    rows.append((seed, len(s.people), m["schedule"]["total_kwh"], m["pir+co2"]["total_kwh"], m["pir"]["false_offs"],
                 m["pir+co2"]["false_offs"], m["pir+co2"]["person_min_too_warm"], m["pir+co2"]["tailgates_true"],
                 m["pir+co2"]["tailgates_caught"], m["pir+co2"]["rollcall_estimate_mean_err"], len(sc.bookings)))
print(f"{len(rows)} days in {time.time() - t0:.0f} s")
for r in rows: print(r)
print("PROBLEMS:", len(problems))
for p in problems: print(p)
sys.exit(1 if problems else 0)
