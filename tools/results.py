"""The README's numbers, read from the replays the app shows, so none is typed by hand.

    python tools/results.py write   # rewrite the module table and the Results section of README.md
    python tools/results.py check   # exit 1 if README.md differs from what the replays say now

The two README parts sit between <!-- modules:start/end --> and <!-- results:start/end --> markers.
tests/test_readme_numbers.py runs the check, so a replay regenerated without its README fails the
suite. Each table names its source: the replay file, its seed and inputs, and the digest of the
simulation code that wrote it (export.source_digest).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"
README = ROOT / "README.md"
MARKS = {"modules": ("<!-- modules:start -->", "<!-- modules:end -->"),
         "results": ("<!-- results:start -->", "<!-- results:end -->")}


def replay(name: str, viewer: Path = VIEWER) -> dict:
    text = (viewer / name).read_text(encoding="utf-8")
    m = re.match(r"window\.(\w+) = ", text)
    return json.loads(text[m.end():].split(";\nwindow.")[0].rstrip().rstrip(";"))


def extract(viewer: Path = VIEWER) -> dict:
    keep = lambda d, ks: {k: d[k] for k in ks}  # noqa: E731
    o = replay("replay.js", viewer)
    om = {k: v["metrics"] for k, v in o["modes"].items()}
    h = replay("home_replay.js", viewer)["june"]
    hm = {k: v["metrics"] for k, v in h["modes"].items()}
    p = replay("hospital_replay.js", viewer)
    pm = {k: v["metrics"] for k, v in p["modes"].items()}
    t = replay("traffic_replay.js", viewer)
    tm = {k: v["metrics"] for k, v in t["modes"].items()}
    j = replay("junctions_replay.js", viewer)
    c = replay("city_replay.js", viewer)
    src = lambda name, meta, **inp: {"file": f"viewer/{name}", "code_digest": meta["digest"], **inp}  # noqa: E731
    greens = sorted({tuple(sorted(s["greens"])) for s in t["signal_sites"] if s.get("greens")})
    return {
        "office": {
            "source": src("replay.js", o["meta"], seed=o["meta"]["seed"], staff=o["meta"]["staff"], visitors=o["meta"]["visitors"]),
            "modes": {k: keep(v, ("total_kwh", "person_min_in_dark", "false_offs", "room_min_lit_empty")) for k, v in om.items()},
            "rollcall": keep(om["schedule"], ("rollcall_counter_mean_err", "rollcall_counter_max_err", "rollcall_register_mean_err",
                                              "rollcall_register_max_err", "rollcall_estimate_mean_err", "rollcall_estimate_max_err",
                                              "rollcall_wifi_mean_err", "rollcall_wifi_max_err", "tailgates_true", "tailgates_caught",
                                              "tailgate_false_alarms")),
        },
        "home": {
            "source": src("home_replay.js", h["meta"], seed=h["meta"]["seed"], season=h["meta"]["season"], category=h["meta"]["category"],
                          pv_kwp=h["meta"]["pv_kwp"], battery_kwh=h["meta"]["battery_kwh"]),
            "modes": {k: keep(v, ("house_dark_min", "hot_sleep_person_min", "bill_rs")) for k, v in hm.items()},
        },
        "hospital": {
            "source": src("hospital_replay.js", p["meta"], seed=p["meta"]["seed"], arrivals_pct=p["meta"]["arrivals_pct"],
                          alarm_delay_s=p["meta"]["alarm_delay"]),
            "beds": len(p["beds"]) if isinstance(p.get("beds"), list) else None,
            "modes": {k: keep(v, ("alarms_sounded", "brief_true_events_not_sounded", "equipment_search_min", "drips_without_pump",
                                  "fridge_minutes_over_8C", "bed_turnaround_min", "hand_hygiene_true_pct", "hand_hygiene_reported_pct",
                                  "door_to_doctor_all_min", "ed_attendants_in_bays_mean", "visitor_min_outside_hours",
                                  "most_visitors_at_a_bed", "visitors_turned_away")) for k, v in pm.items()},
        },
        "traffic": {
            "source": src("traffic_replay.js", t["meta"], seed=t["meta"]["seed"], per_hour=t["meta"]["per_hour"],
                          minutes=t["meta"]["minutes"], period=t["meta"]["period"]),
            "signals": len(t["signal_sites"]), "plan": [list(g) for g in greens], "places": len(t["pois"]),
            "modes": {k: keep(v, ("trips", "completed", "delay_median_s", "stops_mean", "signal_delay_veh_h", "speed_mean_kmh",
                                  "errand_stops", "still_driving", "gridlocked", "not_yet_entered")) for k, v in tm.items()},
        },
        "junctions": {
            "source": src("junctions_replay.js", j["meta"], seed=j["meta"]["seed"], per_hour=j["meta"]["per_hour"],
                          minutes=j["meta"]["minutes"], trips=j["meta"]["trips"]),
            "fixes": [{"junction": x["name"], **{f: x["fixes"][f]["junction_veh_h"] for f in ("baseline", "retime", "adaptive", "uturn", "underpass")},
                       "uturn_km_extra": round(x["fixes"]["uturn"]["km_extra"])} for x in j["junctions"]],
            "ambulance": {k: keep(v, ("response_mean_s", "to_hospital_mean_s", "reds", "preemptions", "calls", "compared_hospital"))
                          for k, v in j["ambulance"]["summary"].items()},
        },
        "city": {
            "source": src("city_replay.js", c["meta"], seed=c["meta"]["seed"], per_hour=c["meta"]["per_hour"]),
            "smog": keep(c["smog"]["metrics"], ("area_mean_peak", "worst_cell_peak", "map_error_today", "map_error_sensors",
                                                "hotspot_found_m", "true_hotspot_before", "true_hotspot_after")),
            "underpasses": len(c["flood"]["underpasses"]),
            "flood": {k: {**keep(v, ("stranded", "gridlocked", "rerouted", "completed", "delay_median_s")),
                          "deepest_m": max(v["max_depth"].values())} for k, v in c["flood"]["modes"].items()},
            "lights": {**{k: keep(v, ("kwh", "busy_road_minutes_dark", "failures_known_by_morning")) for k, v in c["lights"]["modes"].items()},
                       "lamps": c["lights"]["lamp_count"], "failed_lamps": len(c["lights"]["fails"])},
        },
    }


def n(x, d=None) -> str:
    return f"{x:,.{d}f}" if d is not None else f"{x:,}"


def mmss(s: int) -> str:
    return f"{s // 60}:{s % 60:02d}"


def pct(a: float, b: float) -> int:
    """How much less b is than a, in whole per cent."""
    return round(100 * (1 - b / a))


def src_line(s: dict, extra: dict | None = None) -> str:
    inputs = ", ".join(f"{k} {n(v) if isinstance(v, int) else v}" for k, v in s.items() if k not in ("file", "code_digest", "commit", "date"))
    tail = f" · commit `{extra['commit']}`, {extra['date']}" if extra else ""
    return f"*Source:* `{s['file']}` · {inputs} · code digest `{s['code_digest']}`{tail}"


def render_modules(d: dict) -> str:
    o, h, p, t, j, c = (d[k] for k in ("office", "home", "hospital", "traffic", "junctions", "city"))
    om, hm, pm, tm, a, li = o["modes"], h["modes"], p["modes"], t["modes"], j["ambulance"], c["lights"]
    f0, fl, sm = j["fixes"][0], c["flood"], c["smog"]
    plan = " / ".join(f"{max(g)} s / {min(g)} s" for g in t["plan"])
    return f"""| Module | What it simulates | Headline result | Status |
|---|---|---|---|
| **Office tower** | 3 floors (basement car park, ground, first), {o['source']['staff']} staff and {o['source']['visitors']} visitors who also step out for lunch, the bank, a client or the school pick-up; couriers at reception; badge doors, office Wi-Fi, lights, AC, CO₂ | motion + CO₂ uses **{pct(om['schedule']['total_kwh'], om['pir+co2']['total_kwh'])}% less** light and AC energy than a fixed timetable; badges + Wi-Fi keep the evacuation roll-call within **{o['rollcall']['rollcall_wifi_mean_err']}** people on average (badges alone: {o['rollcall']['rollcall_register_mean_err']}) | ready |
| **Home + GridSense** | double-storey house with roof solar ({h['source']['pv_kwp']:g} kWp), {h['source']['battery_kwh']:g} kWh battery, a day of category {h['source']['category']} load-shedding; a family whose children take the school van, go to tuition, and whose relatives visit in the evening; a gate counter | GridSense keeps the house lit through every cut (**{hm['default']['house_dark_min']} → {hm['gridsense']['house_dark_min']}** dark minutes); a day's bill Rs {hm['default']['bill_rs']} (inverter default) against Rs {hm['gridsense_eco']['bill_rs']} (GridSense eco) | ready |
| **Hospital** | Lahore General Hospital campus from OpenStreetMap; Emergency Department (2 floors) and a ward on floor 2; patients' attendants and visitors | monitor alarms that sounded **{pm['today']['alarms_sounded']} → {pm['connected']['alarms_sounded']}**, equipment search **{pm['today']['equipment_search_min']} → {pm['connected']['equipment_search_min']} min**, bed turnaround **{pm['today']['bed_turnaround_min']} → {pm['connected']['bed_turnaround_min']} min** | ready |
| **Lahore traffic** | Gulberg, Kalma Chowk, Garden Town, Canal Road from OpenStreetMap: flyovers, underpasses, one-way streets, lanes, {t['signals']} signals on a {plan} green plan (the main road waits 15 s at red); {n(tm['fixed']['trips'])} trips in the evening peak with stops at {t['places']} real shops and amenities | adaptive signals finish **{n(tm['fixed']['completed'])} → {n(tm['adaptive']['completed'])}** trips and cut time stopped at signals **{tm['fixed']['signal_delay_veh_h']} → {tm['adaptive']['signal_delay_veh_h']}** vehicle-hours; fixed signals leave **{n(tm['fixed']['gridlocked'])}** vehicles gridlocked | ready |
| **Junction planner** | the evening's three worst junctions under five fixes (retime, adaptive, U-turn conversion, underpass), every vehicle drawn; ten Rescue 1122 calls from the real station | at {f0['junction']} time lost goes **{f0['baseline']} → {min(f0[k] for k in ('retime', 'adaptive', 'uturn', 'underpass'))}** vehicle-hours with the best fix; a green wave gets the ambulance to the call in **{mmss(a['greenwave']['response_mean_s'])}** against {mmss(a['none']['response_mean_s'])} | ready |
| **City systems** | on the same roads, driven by the traffic, every vehicle drawn: PM2.5 on a smoggy November evening with 25 low-cost sensors; {c['underpasses']} real underpasses in a monsoon storm with a power cut; {n(li['lamps'])} streetlights through a night of load-shedding | sensors cut the air map's error **{sm['map_error_today']} → {sm['map_error_sensors']} µg/m³**; closed underpasses strand **{fl['today']['stranded']} → {fl['connected']['stranded']}** vehicles; adaptive lights use **{pct(li['today']['kwh'], li['connected']['kwh'])}% less** energy | ready |"""


def render_results(d: dict, commits: dict | None = None) -> str:
    o, h, p, t, j, c = (d[k] for k in ("office", "home", "hospital", "traffic", "junctions", "city"))
    om, hm, pm, tm = o["modes"], h["modes"], p["modes"], t["modes"]
    rc, a = o["rollcall"], j["ambulance"]
    sm, fl, li = c["smog"], c["flood"], c["lights"]
    cm = commits or {}
    fix_rows = "\n".join(f"| {x['junction']} | {x['baseline']} | {x['retime']} | {x['adaptive']} | {x['uturn']} (+{x['uturn_km_extra']} km) | {x['underpass']} |"
                         for x in j["fixes"])
    return f"""Every figure here is read from the replay the app shows, by `tools/results.py`;
`tests/test_readme_numbers.py` fails if any of them stops matching. Nothing is trained, so there is
no train, validation or test split: each module runs one seed under every rule set, on the same
people, patients or trips. Shares, rates and capacities that are assumptions are labelled in the code.

**Office tower**, one working day. {src_line(o['source'], cm.get('office'))}

| | Fixed schedule | Motion | Motion + CO₂ |
|---|---|---|---|
| Lights + AC, kWh | {n(om['schedule']['total_kwh'], 1)} | {n(om['pir']['total_kwh'], 1)} | {n(om['pir+co2']['total_kwh'], 1)} |
| Person-minutes in the dark | {om['schedule']['person_min_in_dark']} | {om['pir']['person_min_in_dark']} | {om['pir+co2']['person_min_in_dark']} |
| Lights switched off on someone | {om['schedule']['false_offs']} | {om['pir']['false_offs']} | {om['pir+co2']['false_offs']} |
| Room-minutes lit while empty | {n(om['schedule']['room_min_lit_empty'])} | {n(om['pir']['room_min_lit_empty'])} | {n(om['pir+co2']['room_min_lit_empty'])} |

Evacuation roll-call, people off from the truth (mean / worst); tailgates caught {rc['tailgates_caught']} of {rc['tailgates_true']}, false alarms {rc['tailgate_false_alarms']}:

| Door counters | Badge register | Register + tailgate alerts | Badges + phones on the Wi-Fi |
|---|---|---|---|
| {rc['rollcall_counter_mean_err']} / {rc['rollcall_counter_max_err']} | {rc['rollcall_register_mean_err']} / {rc['rollcall_register_max_err']} | {rc['rollcall_estimate_mean_err']} / {rc['rollcall_estimate_max_err']} | **{rc['rollcall_wifi_mean_err']} / {rc['rollcall_wifi_max_err']}** |

**Home + GridSense**, a {h['source']['season']} day of category {h['source']['category']} load-shedding. {src_line(h['source'], cm.get('home'))}

| | Inverter default | UPS circuit | GridSense eco | GridSense |
|---|---|---|---|---|
| House dark, min | {hm['default']['house_dark_min']} | {hm['ups']['house_dark_min']} | {hm['gridsense_eco']['house_dark_min']} | {hm['gridsense']['house_dark_min']} |
| Too hot to sleep, person-min | {hm['default']['hot_sleep_person_min']} | {hm['ups']['hot_sleep_person_min']} | {hm['gridsense_eco']['hot_sleep_person_min']} | {hm['gridsense']['hot_sleep_person_min']} |
| Day's bill, Rs | {hm['default']['bill_rs']} | {hm['ups']['bill_rs']} | {hm['gridsense_eco']['bill_rs']} | {hm['gridsense']['bill_rs']} |

**Hospital**, one day, same patients and events. {src_line(p['source'], cm.get('hospital'))}

| | Today | Connected |
|---|---|---|
| HDU alarms that sounded | {pm['today']['alarms_sounded']} | {pm['connected']['alarms_sounded']} |
| Brief real events that never sounded (the cost of the alarm delay) | {pm['today']['brief_true_events_not_sounded']} | {pm['connected']['brief_true_events_not_sounded']} |
| Minutes searching for equipment | {pm['today']['equipment_search_min']} | {pm['connected']['equipment_search_min']} |
| Drips run without a pump | {pm['today']['drips_without_pump']} | {pm['connected']['drips_without_pump']} |
| Fridge minutes above 8 °C | {pm['today']['fridge_minutes_over_8C']} | {pm['connected']['fridge_minutes_over_8C']} |
| Bed turnaround, median min | {pm['today']['bed_turnaround_min']} | {pm['connected']['bed_turnaround_min']} |
| Hand hygiene: true / as reported, % | {pm['today']['hand_hygiene_true_pct']} / {pm['today']['hand_hygiene_reported_pct']} | {pm['connected']['hand_hygiene_true_pct']} / {pm['connected']['hand_hygiene_reported_pct']} |
| Door to doctor, median min | {pm['today']['door_to_doctor_all_min']} | {pm['connected']['door_to_doctor_all_min']} |
| Relatives standing in the ED bays, mean | {pm['today']['ed_attendants_in_bays_mean']} | {pm['connected']['ed_attendants_in_bays_mean']} |
| Ward visitor-minutes outside 16:00–18:00 | {n(pm['today']['visitor_min_outside_hours'])} | {n(pm['connected']['visitor_min_outside_hours'])} |
| Most visitors at one bed | {pm['today']['most_visitors_at_a_bed']} | {pm['connected']['most_visitors_at_a_bed']} |
| Families turned away after 18:00 (the cost of the pass desk) | {pm['today']['visitors_turned_away']} | {pm['connected']['visitors_turned_away']} |

**Lahore traffic**, the evening peak on real roads; every signal's main road gets 60 s of green and
waits 15 s at red, so side roads get 8 s. {src_line(t['source'], cm.get('traffic'))}

| | Fixed signals | Adaptive signals |
|---|---|---|
| Trips | {n(tm['fixed']['trips'])} | {n(tm['adaptive']['trips'])} |
| Trips finished | {n(tm['fixed']['completed'])} | {n(tm['adaptive']['completed'])} |
| Gridlocked (standing 5+ min) at the end | {n(tm['fixed']['gridlocked'])} | {n(tm['adaptive']['gridlocked'])} |
| Never got onto the road | {n(tm['fixed']['not_yet_entered'])} | {n(tm['adaptive']['not_yet_entered'])} |
| Median delay of finished trips, s | {tm['fixed']['delay_median_s']} | {tm['adaptive']['delay_median_s']} |
| Stops per trip | {tm['fixed']['stops_mean']} | {tm['adaptive']['stops_mean']} |
| Stopped at signals, vehicle-hours | {tm['fixed']['signal_delay_veh_h']} | {tm['adaptive']['signal_delay_veh_h']} |
| Mean speed, km/h | {tm['fixed']['speed_mean_kmh']} | {tm['adaptive']['speed_mean_kmh']} |
| Stops at shops and amenities | {n(tm['fixed']['errand_stops'])} | {n(tm['adaptive']['errand_stops'])} |

The median delay counts only trips that finished, so a gridlocked evening can show a lower median
than a flowing one: read it with the trips finished and the gridlocked count beside it.

**Junction planner**, the evening's three worst junctions, every fix on the same trips; vehicle-hours
lost within 350 m. {src_line(j['source'], cm.get('junctions'))}

| Junction | As today | Retime | Adaptive | U-turn conversion | Underpass |
|---|---|---|---|---|---|
{fix_rows}

Rescue 1122, {a['none']['calls']} calls from the real station:

| | No priority | Siren | Green wave |
|---|---|---|---|
| To the call, mean | {mmss(a['none']['response_mean_s'])} | {mmss(a['siren']['response_mean_s'])} | **{mmss(a['greenwave']['response_mean_s'])}** |
| On to hospital, mean ({a['none']['compared_hospital']} calls every way finished) | {mmss(a['none']['to_hospital_mean_s'])} | {mmss(a['siren']['to_hospital_mean_s'])} | {mmss(a['greenwave']['to_hospital_mean_s'])} |
| Red lights met | {a['none']['reds']} | {a['siren']['reds']} | {a['greenwave']['reds']} |
| Signals preempted | {a['none']['preemptions']} | {a['siren']['preemptions']} | {a['greenwave']['preemptions']} |

**City systems.** {src_line(c['source'], cm.get('city'))}

| Smog, a November evening | One official monitor | + 25 low-cost sensors, loop counts and phone reports |
|---|---|---|
| Air-map error near roads, µg/m³ | {sm['map_error_today']} | **{sm['map_error_sensors']}** |
| Hotspot placed, m from the real one | not placed | {n(sm['hotspot_found_m'])} |
| PM2.5 at the real hotspot after adaptive signals there, µg/m³ | {sm['true_hotspot_before']} | {sm['true_hotspot_after']} |

Area mean at the peak {sm['area_mean_peak']} µg/m³; worst street cell {n(sm['worst_cell_peak'], 1)} µg/m³.

| Monsoon storm with a power cut | Today | Connected |
|---|---|---|
| Deepest water, m | {fl['today']['deepest_m']} | **{fl['connected']['deepest_m']}** |
| Vehicles stalled in water | {fl['today']['stranded']} | **{fl['connected']['stranded']}** |
| Gridlocked | {fl['today']['gridlocked']} | {fl['connected']['gridlocked']} |
| Rerouted round a closed underpass | {fl['today']['rerouted']} | {fl['connected']['rerouted']} |
| Trips finished | {n(fl['today']['completed'])} | {n(fl['connected']['completed'])} |
| Median delay of finished trips, s | {fl['today']['delay_median_s']} | {fl['connected']['delay_median_s']} |

| Streetlights, 23:00–05:00 ({n(li['lamps'])} lamps) | Today | Connected |
|---|---|---|
| Energy, kWh | {n(li['today']['kwh'], 1)} | **{n(li['connected']['kwh'], 1)}** ({pct(li['today']['kwh'], li['connected']['kwh'])}% less) |
| Busy road-minutes in the dark | {n(li['today']['busy_road_minutes_dark'])} | **{n(li['connected']['busy_road_minutes_dark'])}** |
| Failed lamps known by morning | {li['today']['failures_known_by_morning']} of {li['failed_lamps']} | **{li['connected']['failures_known_by_morning']} of {li['failed_lamps']}** |"""


def splice(text: str, part: str, body: str) -> str:
    a, b = MARKS[part]
    i, k = text.index(a) + len(a), text.index(b)
    return text[:i] + "\n" + body + "\n" + text[k:]


def wanted(text: str) -> str:
    d = extract()
    return splice(splice(text, "modules", render_modules(d)), "results", render_results(d))


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    have = README.read_text(encoding="utf-8")
    want = wanted(have)
    if cmd == "write":
        README.write_text(want, encoding="utf-8", newline="\n")
        print("README.md: module table and Results rewritten from the replays")
    elif have != want:
        print("README.md differs from the replays: run python tools/results.py write")
        sys.exit(1)
    else:
        print("README.md matches the replays")


if __name__ == "__main__":
    main()
