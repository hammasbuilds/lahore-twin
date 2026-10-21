"""Isometric animations of every Lahore Twin module, two kinds each, from the committed replays.

    python tools/isometric.py            # writes docs/isometric/<module>.html (overview) and <module>-arch.html

* **overview** - the stages an input passes through, each with the code that does it
  (``mediakit.isometric``);
* **architecture** - the module as layers of real components, and one real piece of data
  hopping between them, shown exactly as it was: the bus message with its id, topic,
  payload and cause, the record, the log entry (``mediakit.isodeep``).

Every unit shown is copied from the committed replay files in ``viewer/`` at generation
time, so the animation and the app always tell the same story. Dev-only: needs the shared
media kit (``MEDIAKIT`` env var, default ``D:/launchpad``).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.environ.get("MEDIAKIT", "D:/launchpad"))
from mediakit import isodeep, isometric  # noqa: E402
from mediakit.isodeep import Component as C, Hop, Layer  # noqa: E402
from mediakit.isometric import Stage  # noqa: E402

OUT = ROOT / "docs" / "isometric"
REPO = "github.com/hammasbuilds/lahore-twin"


def load(name: str) -> dict:
    s = (ROOT / "viewer" / name).read_text(encoding="utf-8")
    return json.JSONDecoder().raw_decode(s[s.index("{"):])[0]


def j(obj, keys=None) -> str:
    """A record as it is, one field per line, optionally only some fields."""
    if keys:
        obj = {k: obj[k] for k in keys if k in obj}
    if not isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False)
    # one field per line, each value compact: lists stay on their line
    rows = [f'  "{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in obj.items()]
    return "{\n" + ",\n".join(rows) + "\n}"


def clock(t: float) -> str:
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def first(log, pred):
    return next(m for m in log if pred(m))


# ------------------------------------------------------------------ office
def office():
    R = load("replay.js")
    M = R["modes"]["pir+co2"]
    log, mt = M["log"], M["metrics"]
    by = {m["id"]: m for m in log}
    off = first(log, lambda m: m["topic"].endswith("/light") and m.get("cause") in by and by[m["cause"]].get("cause") in by)
    vac = by[off["cause"]]
    mot = by[vac["cause"]]
    badge = first(log, lambda m: m["topic"] == "office/gate/badge")
    who = badge["text"].split(" badged")[0]
    wifi = first(log, lambda m: m["topic"] == "office/wifi/presence" and who in m["text"])
    pid = next(p["id"] for p in R["people"] if p["name"] == who)
    tg = first(log, lambda m: m["topic"] == "office/alert/tailgate")
    beam = by.get(tg.get("cause")) or first(log, lambda m: m["topic"] == "office/gate/beam")
    saving = round(100 * (1 - mt["total_kwh"] / R["modes"]["schedule"]["metrics"]["total_kwh"]))
    figs = ((f"{saving}%", "less light + AC energy"), (f"{mt['tailgates_caught']}/{mt['tailgates_true']}", "tailgates caught"),
            (str(mt["rollcall_wifi_mean_err"]), "roll-call error, people"))
    arch = "A rule engine on an MQTT-style bus over a 1-second simulation. No model, no embedding, no vector store."
    ov = isometric.Anatomy(
        key="office", project="Lahore Twin · Office tower", repo=REPO,
        tagline="A working day for 52 people on three floors, and the building's IoT reacting to them.",
        given="day 7 · 36 staff with desks · 4 visitors · motion + CO₂ rules",
        given_note="the inputs of “Run with your values”",
        produced=f"{mt['total_kwh']} kWh, {mt['person_min_in_dark']} person-min in the dark, roll-call ±{mt['rollcall_wifi_mean_err']}",
        produced_note="per rule set, on the same people",
        architecture=arch,
        stages=(
            Stage("Plan the day", "Arrivals, meetings, lunch, prayers, couriers, people stepping out", "office.build()", "people + stays"),
            Stage("Walk the building", "Every person walks door to door, floors by lift and stairs", "sim.Sim._step_person()", "positions/s"),
            Stage("Sense", "Motion, CO₂, badge readers, door beams, phones on Wi-Fi", "sim.Sim._pir() / _wifi()", "bus messages"),
            Stage("Decide", "Lights and AC by motion + CO₂; attendance from badges", "rules.Automation / rules.Attendance", "commands + alerts"),
            Stage("Physics", "Room temperature, CO₂ and the energy meter respond", "devices.RoomEnv", "kWh, °C, ppm"),
            Stage("Record", "Every message with its cause, device timelines, series", "export.run_all()", "replay.js"),
            Stage("Show", "Floors, people, why-chains, attendance and roll-call", "viewer/app.js", "the dashboard"),
        ),
        figures=figs)
    deep = isodeep.Deep(
        key="office", project="Lahore Twin · Office tower", repo=REPO,
        tagline="One real chain from the day: a corridor goes quiet and its lights go off; a badge and a phone report the same person.",
        architecture=arch,
        layers=(Layer("world", "Simulated world", "people, rooms, devices"),
                Layer("sense", "Sensors", "publish what they see"),
                Layer("bus", "Message bus", "every message keeps its cause"),
                Layer("rules", "Rules", "turn messages into actions"),
                Layer("out", "Record & view", "replay file, dashboard")),
        components=(C("people", "People", "world", "sim.Sim._step_person()", 0), C("room", "Room & lights", "world", "devices.RoomEnv", 1),
                    C("pir", "Motion sensor", "sense", "sim.Sim._pir()", 0), C("badge", "Badge reader", "sense", "sim.Sim._room_change()", 1),
                    C("wifi", "Wi-Fi AP", "sense", "sim.Sim._wifi()", 2),
                    C("bus", "Bus", "bus", "bus.Bus.publish()", 1),
                    C("auto", "Automation", "rules", "rules.Automation", 0), C("att", "Attendance", "rules", "rules.Attendance", 2),
                    C("rec", "Recorder", "out", "export.run_all()", 0), C("ui", "Dashboard", "out", "viewer/app.js", 2)),
        hops=(
            Hop("pir", "bus", j(mot), "The corridor's motion sensor reports someone moving. The bus stamps the message with an id that every later decision can point back to.", mot["topic"]),
            Hop("bus", "auto", j(vac), f"No motion for {(vac['t'] - mot['t']) // 60} minutes: the rule marks the corridor vacant, citing message {mot['id']} as its cause.", vac["topic"]),
            Hop("auto", "room", j(off), f"It switches the lights off at {clock(off['t'])}; cause {vac['id']}. The room's light load drops on the next physics step.", off["topic"]),
            Hop("people", "badge", j({"person": pid, "name": who, "dir": "in", "door": badge["text"].split("(")[-1].rstrip(")")}), "Arriving staff cross the main badge gate; the reader fires as they pass from the public side to the secure side.", "door crossing"),
            Hop("badge", "att", j(badge), "Attendance logs the first badge-in of the day and checks it against 09:15 for lateness.", badge["topic"]),
            Hop("wifi", "att", j(wifi), f"{(wifi['t'] - badge['t'])} s later the same person's phone joins the Wi-Fi: a second, independent sign they are inside.", wifi["topic"]),
            Hop("bus", "att", j(tg), f"A door beam counted an entry ({beam['id'] if beam else '?'}) with no badge read inside the window: a possible tailgate. Phones on the Wi-Fi later put that person back in the roll-call.", tg["topic"]),
            Hop("att", "rec", j({"rollcall_badges_mean_err": mt["rollcall_estimate_mean_err"], "rollcall_badges_wifi_mean_err": mt["rollcall_wifi_mean_err"], "tailgates": f"{mt['tailgates_caught']} of {mt['tailgates_true']}"}), "Every message, device change and minute of the series goes into the replay with its cause.", "export"),
            Hop("rec", "ui", j({"why": [mot["id"], vac["id"], off["id"]]}), "Click the corridor's light in the dashboard and the why-chain walks these ids back to the motion sensor.", "viewer"),
        ),
        given="a working day: arrivals, meetings, lunch, outings, couriers",
        produced="lights and AC per room, attendance, tailgate alerts, a roll-call",
        figures=figs, source="viewer/replay.js (day 7)")
    return ov, deep


# ------------------------------------------------------------------ home
def home():
    H = load("home_replay.js")["june"]
    G = H["modes"]["gridsense"]
    log, mt, dm = G["log"], G["metrics"], H["modes"]["default"]["metrics"]
    inv = first(log, lambda m: m["topic"] == "home/inverter/settings")
    gate = first(log, lambda m: m["topic"] == "home/gate/count")
    by = {m["id"]: m for m in log}
    fan = first(log, lambda m: m["topic"].endswith("/fan") and m.get("cause") in by)
    want = by[fan["cause"]]
    out0 = H["outages"][0]
    figs = ((f"{dm['house_dark_min']} → {mt['house_dark_min']}", "dark minutes"), (f"Rs {mt['bill_rs']}", "the day's bill"),
            (str(len(H["gate"])), "gate crossings"))
    arch = "A planning controller (rules + a reserve calculation) over a 1-second house simulation. No model, no embedding, no vector store."
    ov = isometric.Anatomy(
        key="home", project="Lahore Twin · Home + GridSense", repo=REPO,
        tagline="A Lahore family's day on solar through load-shedding, and an energy manager that plans around the cuts.",
        given="June · feeder category IV · 6 kWp solar · 10 kWh battery",
        given_note="the inputs of “Run with your values”",
        produced=f"{mt['house_dark_min']} dark minutes, Rs {mt['bill_rs']}, every decision with its reason",
        produced_note="four controllers, the same day",
        architecture=arch,
        stages=(
            Stage("Plan the day", "School van, office, tuition, errands, guests, prayers, outages", "home.build()", "people + outages"),
            Stage("Live it", "People move room to room; fans, ACs and lights follow them", "home_sim.HomeSim._step_person()", "wants"),
            Stage("Count at the gate", "A beam counter reports every coming and going", "home_sim.HomeSim._gate()", "home/gate/count"),
            Stage("Plan the power", "Reserve for the next cut, pre-cool, run the pump on spare sun", "gridsense.GridSense", "inverter commands"),
            Stage("Physics", "Sun, battery, inverter limits, room heat, the roof tank", "power.Inverter / devices", "kW, %, °C"),
            Stage("Record", "Every decision with its cause and the minute series", "export_home.run_all()", "home_replay.js"),
            Stage("Show", "Floors, power flow, who is home, the comparison", "viewer/home.js", "the dashboard"),
        ),
        figures=figs)
    deep = isodeep.Deep(
        key="home", project="Lahore Twin · Home + GridSense", repo=REPO,
        tagline="Real messages from one June day: a published outage, the controller's plan, a fan someone wanted, a child leaving for school.",
        architecture=arch,
        layers=(Layer("world", "House", "family, rooms, appliances"), Layer("sense", "Sensors & meters", "gate, presence, inverter"),
                Layer("bus", "Message bus", "messages with causes"), Layer("ctrl", "GridSense", "plans power around cuts"),
                Layer("out", "Record & view", "replay, dashboard")),
        components=(C("family", "Family", "world", "home_sim.HomeSim._step_person()", 0), C("fans", "Fans & ACs", "world", "home_sim.HomeSim._update_wants()", 1),
                    C("grid", "Feeder (LESCO)", "world", "home._outages()", 2),
                    C("gatec", "Gate counter", "sense", "home_sim.HomeSim._gate()", 0), C("invm", "Inverter", "sense", "power.Inverter", 2),
                    C("bus", "Bus", "bus", "bus.Bus.publish()", 1),
                    C("gs", "GridSense", "ctrl", "gridsense.GridSense", 1),
                    C("rec", "Recorder", "out", "export_home.run_all()", 0), C("ui", "Dashboard", "out", "viewer/home.js", 2)),
        hops=(
            Hop("grid", "gs", j(out0), f"The published load-shedding schedule: a cut from {clock(out0['start'])} to {clock(out0['end'])}. GridSense sizes a battery reserve for it.", "schedule"),
            Hop("gs", "invm", j(inv), "It sets the inverter's mode and floor, and says why, in the message itself.", inv["topic"]),
            Hop("family", "fans", j(want), "Someone in the room wants the fan: the room is warm and occupied.", want["topic"]),
            Hop("fans", "bus", j(fan), f"The fan goes on, citing message {want['id']}.", fan["topic"]),
            Hop("family", "gatec", j({"t": gate["t"], "person": gate["text"].split(": ")[1].split(" went")[0], "way": "out"}), "A child walks out of the gate to the school van; the beam counts the crossing.", "beam"),
            Hop("gatec", "bus", j(gate), "The counter publishes how many are home. Fans and lights follow presence room by room.", gate["topic"]),
            Hop("bus", "rec", j({"house_dark_min": mt["house_dark_min"], "bill_rs": mt["bill_rs"], "default_dark_min": dm["house_dark_min"]}), "Every message, device change and minute of power goes into the replay.", "export"),
            Hop("rec", "ui", j({"people_tab": f"{gate['payload']} at home", "why": [want["id"], fan["id"]]}), "The People tab shows the gate log; clicking the fan shows why it came on.", "viewer"),
        ),
        given="a June day of category IV load-shedding, 6 kWp, 10 kWh",
        produced="decisions with reasons, dark minutes, comfort, the bill",
        figures=figs, source="viewer/home_replay.js (June, day 7)")
    return ov, deep


# ------------------------------------------------------------------ hospital
def hospital():
    P = load("hospital_replay.js")
    Cn, Td = P["modes"]["connected"], P["modes"]["today"]
    log, mt, mt0 = Cn["log"], Cn["metrics"], Td["metrics"]
    by = {m["id"]: m for m in log}
    arr = first(log, lambda m: m["topic"].endswith("/arrival"))
    tri = first(log, lambda m: m["topic"].endswith("/triage") and m.get("cause") == arr["id"])
    rec = Cn["records"][0] if isinstance(Cn["records"], list) else next(iter(Cn["records"].values()))
    ans = first(log, lambda m: m["topic"].endswith("/alarm/answered") and m.get("cause") in by)
    alm = by[ans["cause"]]
    hidden = first(Cn["alarms"], lambda a: a.get("hidden"))
    figs = ((f"{mt0['alarms_sounded']} → {mt['alarms_sounded']}", "alarms that sounded"),
            (f"{mt0['equipment_search_min']:.0f} → {mt['equipment_search_min']:.0f}", "min searching for kit"),
            (f"{mt0['ed_attendants_in_bays_mean']} → {mt['ed_attendants_in_bays_mean']}", "relatives in the bays"))
    arch = "Agents (generator coroutines) on a shared task board, rules on an MQTT-style bus. No model, no embedding, no vector store."
    ov = isometric.Anatomy(
        key="hospital", project="Lahore Twin · Hospital", repo=REPO,
        tagline="Lahore General Hospital's emergency department and a ward for a day, Today against Connected.",
        given="day 7 · 100% arrivals · 3 ward nurses · 15 s alarm delay",
        given_note="the inputs of “Run with your values”",
        produced=f"alarms {mt0['alarms_sounded']} → {mt['alarms_sounded']}, bed turnaround {mt0['bed_turnaround_min']} → {mt['bed_turnaround_min']} min",
        produced_note="the same patients under both rule sets",
        architecture=arch,
        stages=(
            Stage("Who comes", "Arrivals, triage colours, ward patients, alarms, calls, families", "hospital.build()", "the day"),
            Stage("Staff and patients", "Doctors, nurses, porters, cleaners and patients as agents", "hospital_sim.HospitalSim.staff_loop()", "tasks"),
            Stage("Alarms and calls", "Monitors and call buttons; Connected routes them to the bed's nurse", "hospital_sim.HospitalSim.ward_alarm()", "routed alerts"),
            Stage("Equipment", "Pumps, chairs, trolleys; a locator ends the search", "hospital_sim.HospitalSim.fetch()", "asset moves"),
            Stage("Families", "Attendants follow patients; a pass desk at visiting hours", "hospital_sim.HospitalSim.ed_attendant()", "people counts"),
            Stage("Record", "Patient records, bed board, every message with its cause", "export_hospital.run_all()", "hospital_replay.js"),
            Stage("Show", "Campus, ED, ward, boards and the comparison", "viewer/hospital.js", "the dashboard"),
        ),
        figures=figs)
    deep = isodeep.Deep(
        key="hospital", project="Lahore Twin · Hospital", repo=REPO,
        tagline="Real records from one day: a patient's way through the emergency department, and a monitor alarm under Connected.",
        architecture=arch,
        layers=(Layer("world", "Patients & families", "who comes in"), Layer("agents", "Staff agents", "take tasks from the board"),
                Layer("sense", "Devices", "monitors, call buttons, badges"), Layer("bus", "Message bus", "messages with causes"),
                Layer("out", "Record & view", "records, boards, dashboard")),
        components=(C("pat", "Patient", "world", "hospital_sim.HospitalSim.ed_patient()", 0), C("fam", "Attendants", "world", "hospital_sim.HospitalSim.ed_attendant()", 1),
                    C("clerk", "Clerk & triage", "agents", "hospital_sim.HospitalSim.perform()", 0), C("nurse", "Ward nurse", "agents", "hospital_sim.HospitalSim.staff_loop()", 1),
                    C("mon", "Bedside monitor", "sense", "hospital_sim.HospitalSim.ward_alarm()", 1), C("delay", "Alarm delay", "sense", "hospital_sim.HospitalSim._alarm_task()", 2),
                    C("bus", "Bus", "bus", "bus.Bus.publish()", 1),
                    C("rec", "Records", "out", "export_hospital.run_all()", 0), C("ui", "Dashboard", "out", "viewer/hospital.js", 2)),
        hops=(
            Hop("pat", "bus", j(arr), "A patient walks in, with relatives behind them.", arr["topic"]),
            Hop("bus", "clerk", j(tri), f"Registered and triaged {rec['colour'].upper()}, citing the arrival message.", tri["topic"]),
            Hop("fam", "pat", j({"attendants": "1-3 relatives", "connected": "one attendant card; the rest wait outside"}), "Under Connected one relative stays at the bedside; the others wait at the door.", "attendant card"),
            Hop("clerk", "rec", j(rec, ["id", "colour", "arrive", "triaged", "placed", "place", "seen", "left", "outcome"]), "The patient's record: every timestamp from the door to going home.", "record"),
            Hop("mon", "delay", j(hidden), "A brief artefact: the 15-second delay holds it, and it ends before anyone is called.", "alarm (held)"),
            Hop("mon", "bus", j(alm), "A sustained alarm survives the delay and goes to the bed's own nurse's badge, not to everyone.", alm["topic"]),
            Hop("bus", "nurse", j(ans), "The nurse walks to the bed and answers it, citing the alarm.", ans["topic"]),
            Hop("nurse", "rec", j({"alarms_sounded": mt["alarms_sounded"], "today": mt0["alarms_sounded"], "brief_true_events_not_sounded": mt["brief_true_events_not_sounded"]}), "The day's count, and the cost of the delay, kept beside it.", "metrics"),
            Hop("rec", "ui", j({"board": "emergency + beds", "compare": "Today vs Connected"}), "The boards and the comparison read straight from these records.", "viewer"),
        ),
        given="a day of emergency arrivals, a 36-bed ward, alarms, families",
        produced="waits, alarms answered, equipment found, beds turned round",
        figures=figs, source="viewer/hospital_replay.js (day 7)")
    return ov, deep


# ------------------------------------------------------------------ traffic
def traffic():
    T = load("traffic_replay.js")
    F, A = T["modes"]["fixed"], T["modes"]["adaptive"]
    mf, ma = F["metrics"], A["metrics"]
    i = next(k for k, v in enumerate(A["vehicles"]) if any(e[3] >= 0 and e[1] for e in v[6]) and len(T["routes"][k]) > 20)
    v = A["vehicles"][i]
    stop = next(e for e in v[6] if e[3] >= 0)
    poi = T["pois"][stop[3]]
    purpose = T["purposes"][T["trip_purpose"][i]]
    sig = T["signal_sites"][0]
    slog = A["signals"][str(sig["id"])][:4]
    figs = ((f"{mf['delay_median_s']:.0f} → {ma['delay_median_s']:.0f} s", "median delay, fixed → adaptive"),
            (f"{mf['errand_stops']:,}", "stops at real shops"), (f"{T['meta']['trips']:,}", "trips in the evening peak"))
    arch = "A microscopic traffic simulation (car-following + lane changing) on OpenStreetMap roads; signal controllers are rules. No model, no embedding, no vector store."
    ov = isometric.Anatomy(
        key="traffic", project="Lahore Twin · Lahore traffic", repo=REPO,
        tagline="An evening peak on Gulberg's real roads: trips with reasons, real shops, 59 signals.",
        given="evening · 8,000 trips an hour · seed 7",
        given_note="the inputs of “Run with your values”",
        produced=f"median delay {mf['delay_median_s']:.0f} s fixed, {ma['delay_median_s']:.0f} s adaptive; the worst junctions",
        produced_note="the same trips under both signal plans",
        architecture=arch,
        stages=(
            Stage("Real roads", "OpenStreetMap ways split into directed links with lanes and layers", "roads.load()", "9,698 links"),
            Stage("Trips with reasons", "Shopping, pharmacy, school run, fuel, at 432 real places", "traffic_sim.make_demand()", "routes + stops"),
            Stage("Signals", "60 s / 30 s fixed plans or loop-detector adaptive", "traffic_sim.TrafficSim.tick_signals()", "phase log"),
            Stage("Drive", "Car-following, lane changes, give-way, kerb stops, parking", "traffic_sim.TrafficSim.step()", "positions/s"),
            Stage("Measure", "Delay, stops, junction losses, gridlock, stops at shops", "traffic_sim.TrafficSim.metrics()", "metrics"),
            Stage("Record", "Routes once, positions as small deltas, tiles", "export_traffic.run_all()", "traffic_replay.js"),
            Stage("Show", "A map that streams around the camera, follow, places", "viewer/traffic.js", "the dashboard"),
        ),
        figures=figs)
    deep = isodeep.Deep(
        key="traffic", project="Lahore Twin · Lahore traffic", repo=REPO,
        tagline=f"One real vehicle from the evening: why it drove, the shop it stopped at, the signal it met.",
        architecture=arch,
        layers=(Layer("map", "Map", "OpenStreetMap roads and places"), Layer("demand", "Demand", "who drives where, and why"),
                Layer("ctrl", "Signals", "fixed or adaptive controllers"), Layer("drive", "Driving", "every vehicle, every second"),
                Layer("out", "Record & view", "replay, map, panels")),
        components=(C("osm", "Road network", "map", "roads.load()", 0), C("pois", "Shops & amenities", "map", "traffic_sim.snap_pois()", 2),
                    C("dem", "Trip generator", "demand", "traffic_sim.make_demand()", 1),
                    C("sig", "Signal controller", "ctrl", "traffic_sim.TrafficSim.tick_signals()", 2),
                    C("idm", "Car-following", "drive", "traffic_sim.TrafficSim._ahead()", 0), C("stop", "Stops & parking", "drive", "traffic_sim.TrafficSim._start_errand()", 2),
                    C("rec", "Recorder", "out", "export_traffic.run_all()", 0), C("ui", "Map viewer", "out", "viewer/traffic.js", 2)),
        hops=(
            Hop("osm", "dem", j({"links": len(T["links"]), "roads": len(T["roads"]), "signals": len(T["signal_sites"])}), "The real road network: every road piece a directed link with its lanes, speed and layer (flyovers +1, underpasses -1).", "network"),
            Hop("pois", "dem", j({"name": poi[3], "kind": T["poi_kinds"][poi[2]], "x": poi[0], "y": poi[1]}), "A real place from OpenStreetMap, snapped to the street it opens onto.", "place"),
            Hop("dem", "idm", j({"vehicle": i, "kind": T["kinds"][v[0]], "why": purpose, "sets_off": clock(T["meta"]["start"] + v[1]), "route_links": len(T["routes"][i])}), "A trip with a reason: the generator picked the nearest of four places that sell it, and routed around expected waits at red.", "trip"),
            Hop("sig", "idm", j({"signal": sig["name"], "greens_s": sig.get("greens"), "log": slog}), "The signal on its way: fixed 60 s / 30 s, amber 3 s, all-red 2 s - here under adaptive control, each green ended by a gap in traffic.", "phase log"),
            Hop("idm", "stop", j({"stop": [clock(T["meta"]["start"] + stop[0]), clock(T["meta"]["start"] + stop[1])], "what": stop[2], "at": poi[3]}), "It reaches the shop and pulls off the road to park; a short stop would have blocked the kerb lane instead.", "stop"),
            Hop("stop", "rec", j({"trips": T["meta"]["trips"], "errand_stops": ma["errand_stops"], "delay_median_s": ma["delay_median_s"], "gridlocked": ma["gridlocked"]}), "Every vehicle's route is stored once, its positions as whole-metre deltas every 4 s.", "metrics"),
            Hop("rec", "ui", j({"follow": f"vehicle #{i + 1}", "panel": ["Why", "Stops on the way", "Route"]}), "Follow it on the map: the Follow panel shows why it drove and where it stopped.", "viewer"),
        ),
        given="an evening peak, 8,000 trips an hour, real roads and places",
        produced="delay, stops, signal losses, busiest places, per signal plan",
        figures=figs, source="viewer/traffic_replay.js (evening, seed 7)")
    return ov, deep


# ------------------------------------------------------------------ junction planner
def junctions():
    J = load("junctions_replay.js")
    j0 = J["junctions"][0]
    f = j0["fixes"]
    S = J["ambulance"]["summary"]
    call = J["ambulance"]["calls"][0]
    mm = lambda s: f"{s // 60}:{s % 60:02d}"  # noqa: E731
    figs = ((f"{f['baseline']['junction_veh_h']} → {f['uturn']['junction_veh_h']}", "veh-h lost, U-turn conversion"),
            (f"{mm(S['none']['response_mean_s'])} → {mm(S['greenwave']['response_mean_s'])}", "ambulance to the call"),
            (f"+{f['uturn']['km_extra']:.0f} km", "the U-turn's cost"))
    arch = "The traffic simulation re-run per fix, with turn bans, rerouting and signal preemption. No model, no embedding, no vector store."
    ov = isometric.Anatomy(
        key="junctions", project="Lahore Twin · Junction planner", repo=REPO,
        tagline="The worst junctions under the fixes Lahore uses, and Rescue 1122 through the peak.",
        given="evening · 8,000 trips an hour · seed 7",
        given_note="the inputs of “Run with your values”",
        produced=f"{j0['name']}: {f['baseline']['junction_veh_h']} → {f['uturn']['junction_veh_h']}–{f['retime']['junction_veh_h']} veh-h; ambulance −{round(100 * (1 - S['greenwave']['response_mean_s'] / S['none']['response_mean_s']))}%",
        produced_note="every fix on the same trips",
        architecture=arch,
        stages=(
            Stage("Find the worst", "Rank junctions by time lost in the evening peak", "junctions.run_all()", "3 junctions"),
            Stage("Retime", "Webster's split on the demand each approach carries", "junctions.webster()", "greens"),
            Stage("U-turn conversion", "Ban crossing moves, open median gaps, reroute", "junctions.uturn_conversion() / reroute()", "new routes"),
            Stage("Underpass", "Main-road through traffic skips the surface signal", "TrafficSim.underpass", "signal-free"),
            Stage("Ambulance", "Station to call to hospital; none, siren, green wave", "junctions.run_ambulance()", "traces"),
            Stage("Record", "Close maps, fix results, queues, signal greens", "export_junctions.run_all()", "junctions_replay.js"),
            Stage("Show", "The fix drawn on the junction; the time-distance diagram", "viewer/junctions.js", "the planner"),
        ),
        figures=figs)
    deep = isodeep.Deep(
        key="junctions", project="Lahore Twin · Junction planner", repo=REPO,
        tagline=f"Real results: {j0['name']} converted to U-turns, and one Rescue 1122 call under a green wave.",
        architecture=arch,
        layers=(Layer("net", "Network", "roads, movements, gaps"), Layer("fix", "Fixes", "what changes per scenario"),
                Layer("sim", "Simulation", "the same trips, re-run"), Layer("amb", "Rescue 1122", "calls and priority"),
                Layer("out", "Record & view", "results, maps, diagrams")),
        components=(C("rank", "Junction ranking", "net", "TrafficSim.metrics()['worst_junctions']", 0), C("mv", "Movements", "net", "junctions.Movements", 2),
                    C("uturn", "U-turn conversion", "fix", "junctions.uturn_conversion()", 0), C("web", "Webster retime", "fix", "junctions.webster()", 2),
                    C("run", "Scenario run", "sim", "junctions.run_fix()", 1),
                    C("call", "Ambulance call", "amb", "junctions.ambulance_calls()", 0), C("pre", "Preemption", "amb", "TrafficSim._preempt_requests()", 2),
                    C("rec", "Recorder", "out", "export_junctions.run_all()", 0), C("ui", "Planner", "out", "viewer/junctions.js", 2)),
        hops=(
            Hop("rank", "mv", j({"junction": j0["name"], "main_road": j0["main"], "lost_today_veh_h": f["baseline"]["junction_veh_h"]}), "The worst junction of the evening, and its main road.", "worst"),
            Hop("mv", "uturn", j({"allowed": "main road straight on, left turns", "banned": "crossing and right turns", "gaps": j0["gaps"]}), "Movements are judged whole, approach to exit; U-turn gaps open in the median 150-400 m away.", "turn bans"),
            Hop("uturn", "run", j({k: f["uturn"][k] for k in ("rerouted", "junction_veh_h", "queue_peak", "km_extra", "pedestrian_crossing")}), "Trips that crossed are rerouted to the gaps and the same trips are run again.", "scenario"),
            Hop("web", "run", j({"greens_s": f["retime"]["greens"], "junction_veh_h": f["retime"]["junction_veh_h"]}), "Webster's method on the real per-lane demand: the side road gets the long green, because the main road's through traffic is on the flyover.", "retime"),
            Hop("call", "pre", j({"dispatched": clock(J["meta"]["start"] + call["t0"]), "route_m": call["length"], "signals": [s[3] for s in call["signals"]], "to": call["hospital"]}), "A call: from the real Rescue 1122 station, ten minutes there, to the nearest emergency department.", "call"),
            Hop("pre", "run", j({w: call["modes"][w]["response_s"] for w in ("none", "siren", "greenwave") if w in call["modes"]}), "Each signal within 300 m turns green for it, keeping amber and all-red; the same call, three ways.", "response, s"),
            Hop("run", "rec", j({"baseline": f["baseline"]["junction_veh_h"], "retime": f["retime"]["junction_veh_h"], "adaptive": f["adaptive"]["junction_veh_h"], "uturn": f["uturn"]["junction_veh_h"], "underpass": f["underpass"]["junction_veh_h"]}), "Every fix's results, queue series and the ambulance traces are written once.", "results"),
            Hop("rec", "ui", j({"view": ["Fix a junction", "Ambulance"], "diagram": "time against distance"}), "The planner draws the fix on the real roads and the green-wave diagram.", "viewer"),
        ),
        given="an evening peak and its worst junctions; ten ambulance calls",
        produced="time lost per fix, its costs; ambulance times three ways",
        figures=figs, source="viewer/junctions_replay.js (seed 7)")
    return ov, deep


# ------------------------------------------------------------------ city systems
def _cell(G, x, y):
    i = min(G["nx"] - 1, max(0, int((x - G["x0"]) // G["cell"])))
    jj = min(G["ny"] - 1, max(0, int((y - G["y0"]) // G["cell"])))
    return jj * G["nx"] + i


def city():
    Cy = load("city_replay.js")
    sm, F, Lt = Cy["smog"]["metrics"], Cy["flood"], Cy["lights"]
    fa, fb, la, lb = F["modes"]["today"], F["modes"]["connected"], Lt["modes"]["today"], Lt["modes"]["connected"]
    u0 = F["underpasses"][0]["name"]
    figs = ((f"{sm['map_error_today']:.0f} → {sm['map_error_sensors']:.0f}", "air-map error, µg/m³"), (f"{fa['stranded']} → {fb['stranded']}", "vehicles stalled in underpasses"),
            (f"−{round(100 * (1 - lb['kwh'] / la['kwh']))}%", "streetlight energy"))
    arch = "Three IoT systems on the traffic simulation's own vehicles: a dispersion grid with a land-use regression, underpass water balances, lamp-by-lamp dimming. No model, no embedding, no vector store."
    ov = isometric.Anatomy(
        key="city", project="Lahore Twin · City systems", repo=REPO,
        tagline="Smog sensors, underpass flood alarms and streetlights on Lahore's real roads, driven by its traffic.",
        given="an evening · 8,000 trips an hour · seed 7",
        given_note="the inputs of “Run with your values”",
        produced=f"map error {sm['map_error_today']} → {sm['map_error_sensors']} µg/m³; {fa['stranded']} → {fb['stranded']} stalled; {la['kwh']:,.0f} → {lb['kwh']:,.0f} kWh",
        produced_note="Today against Connected, the same trips",
        architecture=arch,
        stages=(
            Stage("Traffic", "The evening's trips on the real roads, minute by minute", "traffic_sim.TrafficSim", "vehicles"),
            Stage("Smog", "Exhaust and idling per road, spread on a 100 m grid over the haze", "city.smog()", "PM2.5 field"),
            Stage("Sensors", "One monitor, or 25 low-cost sensors and the loop counts", "city.sensor_sites() / smog()", "the city's map"),
            Stage("Storm", "Rain into each underpass, pumps out until the feeder trips", "city.depth_series()", "water depth"),
            Stage("Gates", "Level sensors close the underpass and reroute traffic", "city.flood()", "detours"),
            Stage("Night", "Each road dims unless traffic is on or beside it", "city.streetlights()", "lamp levels"),
            Stage("Show", "Smog, Rain and Night, Today against Connected", "viewer/city.js", "City Systems"),
        ),
        figures=figs)
    deep = isodeep.Deep(
        key="city", project="Lahore Twin · City systems", repo=REPO,
        tagline="One evening, one storm, one night: the traffic's own vehicles through three city systems.",
        architecture=arch,
        layers=(Layer("road", "Traffic", "vehicles on the real roads"), Layer("phys", "Physics", "smoke, water, light"),
                Layer("iot", "Sensors & controls", "what the city measures and does"), Layer("out", "Record & view", "replay and page")),
        components=(C("sim", "Traffic simulation", "road", "traffic_sim.TrafficSim", 1),
                    C("disp", "Dispersion grid", "phys", "city.Grid.spread()", 0), C("sump", "Underpass basin", "phys", "city.depth_series()", 1), C("lamp", "Lamp levels", "phys", "city.streetlights()", 2),
                    C("lur", "Sensors + LUR", "iot", "city.smog()", 0), C("gate", "Level sensor + gate", "iot", "city.flood()", 1), C("dim", "Dimming controller", "iot", "city.streetlights()", 2),
                    C("rec", "Recorder", "out", "export_city.run_all()", 0), C("ui", "City Systems", "out", "viewer/city.js", 2)),
        hops=(
            Hop("sim", "disp", j({"trips": Cy["smog"]["trips"], "minutes": Cy["smog"]["minutes"], "emits": "g per road per minute: exhaust per km + idling in queues"}), "The traffic module's vehicles are the smog's source.", "emissions"),
            Hop("disp", "lur", j({"area_mean_peak": sm["area_mean_peak"], "worst_cell_peak": sm["worst_cell_peak"]}), "PM2.5 at street level, µg/m³, at the peak.", "PM2.5"),
            Hop("lur", "sim", j({"hotspot_found_m": sm["hotspot_found_m"], "adaptive_signals": sm["adaptive_signals"], "real_hotspot": [sm["true_hotspot_before"], sm["true_hotspot_after"]]}), "Where the sensors find the hotspot, nearby signals go adaptive; same trips again.", "action"),
            Hop("sump", "gate", j({"underpass": u0, "max_depth_m": [fa["max_depth"][u0], fb["max_depth"][u0]], "power_cut": [clock(Cy["meta"]["flood_start"] + F["power_cut"][0]), clock(Cy["meta"]["flood_start"] + F["power_cut"][1])]}), "Today against Connected: the generator and the gate.", "depth"),
            Hop("gate", "sim", j({"stranded": [fa["stranded"], fb["stranded"]], "rerouted": fb["rerouted"], "trips_finished": [fa["completed"], fb["completed"]]}), "A closed underpass turns cars back to the surface road.", "detour"),
            Hop("sim", "dim", j({"night_trips": Lt["trips"], "lamps": Lt["lamp_count"], "dim_to": Lt["dim"]}), "Which roads have traffic each minute decides each road's level.", "occupancy"),
            Hop("dim", "lamp", j({"kwh": [la["kwh"], lb["kwh"]], "busy_road_minutes_dark": [la["busy_road_minutes_dark"], lb["busy_road_minutes_dark"]]}), "Today against Connected, the whole night.", "energy"),
            Hop("rec", "ui", j({"views": ["Smog", "Rain", "Night"], "rule_sets": ["Today", "Connected"]}), "One replay, three views on the same base map.", "viewer"),
        ),
        given="an evening's trips on the real roads",
        produced="air map, underpass depths, lamp levels: Today against Connected",
        figures=figs, source="viewer/city_replay.js (seed 7)")
    return ov, deep


# ------------------------------------------------------------------ the app
def app():
    figs = (("6", "modules running"), ("1", "server, stdlib only"), ("0", "real devices needed"))
    arch = "One offline web app over stdlib-Python simulators; a local server re-runs a module with your values. No model, no embedding, no vector store."
    ov = isometric.Anatomy(
        key="app", project="Lahore Twin", repo=REPO,
        tagline="IoT simulation of a city, one building at a time: office, home, hospital, traffic, junctions, city systems.",
        given="a module and your values, e.g. traffic · morning · 4,000 trips/h",
        given_note="typed into “Run with your values”",
        produced="that module's dashboard, simulated from your values",
        produced_note="labelled “Your run” with the inputs",
        architecture=arch,
        stages=(
            Stage("Overview", "Pick a module, read its About, or run it with your values", "viewer/shell.js", "the request"),
            Stage("Check the inputs", "Every value against its range; a bad one is refused with the reason", "serve.clean()", "clean inputs"),
            Stage("Cache key", "Inputs + the module's code digest: a code change never serves an old run", "serve.run_key()", "runs/<key>.js"),
            Stage("Simulate", "The module's own engine, the same one the demos use", "serve.simulate()", "replay"),
            Stage("Open it", "The module page loads the run in the shell", "viewer/embed.js", "“Your run”"),
        ),
        figures=figs)
    deep = isodeep.Deep(
        key="app", project="Lahore Twin", repo=REPO,
        tagline="What happens between typing a value and seeing the simulated result.",
        architecture=arch,
        layers=(Layer("ui", "Browser", "shell and module pages"), Layer("srv", "Local server", "serve.py, stdlib"),
                Layer("eng", "Engines", "one simulator per module"), Layer("disk", "Files", "replays and the run cache")),
        components=(C("form", "Run form", "ui", "viewer/shell.js", 0), C("page", "Module page", "ui", "viewer/embed.js", 2),
                    C("clean", "Input check", "srv", "serve.clean()", 0), C("key", "Cache key", "srv", "serve.run_key()", 2),
                    C("sim", "Simulator", "eng", "export_traffic.run_all()", 1),
                    C("cache", "viewer/runs/", "disk", "serve.simulate()", 1)),
        hops=(
            Hop("form", "clean", 'POST /api/run/traffic\n{"period": "morning", "per_hour": 4000}', "The values typed into the form go to the local server.", "HTTP"),
            Hop("clean", "key", '{"seed": 7, "per_hour": 4000, "period": "morning"}', "Each value is checked against its range; missing ones take defaults. 50,000 trips an hour would be refused here, with the reason.", "clean()"),
            Hop("key", "cache", 'sha256(["traffic", inputs, source_digest("traffic")])[:12]\n-> runs/traffic-<key>.js', "The key includes the code's digest, so after any change to the simulator an old cached run is never served.", "run_key()"),
            Hop("cache", "sim", "cache miss -> run_all(seed=7, per_hour=4000, period='morning')", "Not cached: the traffic engine simulates the morning with these values (about 25 s).", "simulate()"),
            Hop("sim", "cache", "window.TRAFFIC = {meta: {period: 'morning', per_hour: 4000, ...}, ...}", "The replay is written to a temporary file and renamed into place, so a half-written run is never read.", "replay"),
            Hop("cache", "page", '{"replay": "runs/traffic-<key>.js", "inputs": {...}}', "The shell opens the module on that replay and labels it “Your run · seed 7 · morning · 4,000 trips/h”.", "HTTP 200"),
        ),
        given="a module and the values typed into its form",
        produced="the module's dashboard on a fresh simulation",
        figures=figs, source="serve.py and tools/ui_check_app.js runs")
    return ov, deep


MODULES = {"app": app, "office": office, "home": home, "hospital": hospital, "traffic": traffic, "junctions": junctions, "city": city}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    from isometric_tools import TOOLS          # one pair per tool inside each module, as well as per module
    for key, build in {**MODULES, **TOOLS}.items():
        ov, deep = build()
        # the board's convention: <proj>.* for the overview, <proj>-arch.* for the architecture view
        (OUT / f"{key}.html").write_text(isometric.render(ov), encoding="utf-8", newline="\n")
        (OUT / f"{key}-arch.html").write_text(isodeep.render(deep), encoding="utf-8", newline="\n")
        index.append({"key": key, "title": ov.project, "overview": f"{key}.html", "architecture": f"{key}-arch.html",
                      "overview_s": round(ov.seconds), "architecture_s": round(deep.seconds)})
        print(f"{key:10} overview {ov.seconds:4.0f}s · architecture {deep.seconds:4.0f}s ({len(deep.hops)} hops)")
    (OUT / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
