"""Tool-level isometric animations: one overview and one architecture view per tool inside each
module, each following that tool's own data, copied from the committed replays.

Imported by tools/isometric.py, which writes them as docs/isometric/<module>-<tool>.html and
<module>-<tool>-arch.html beside the module-level pair.
"""

from __future__ import annotations

from isometric import REPO, clock, first, j, load  # noqa: E402  (tools/ is on sys.path when run)
from mediakit import isodeep, isometric
from mediakit.isodeep import Component as C, Hop, Layer
from mediakit.isometric import Stage

NOMODEL = "No model, no embedding, no vector store."


def _pair(key, project, tagline, arch, given, given_note, produced, produced_note, stages, figs,
          layers, comps, hops, d_given, d_produced, source, deep_tagline):
    ov = isometric.Anatomy(key=key, project=project, repo=REPO, tagline=tagline, given=given, given_note=given_note,
                           produced=produced, produced_note=produced_note, architecture=arch, stages=stages, figures=figs)
    deep = isodeep.Deep(key=key, project=project, repo=REPO, tagline=deep_tagline, architecture=arch, layers=layers,
                        components=comps, hops=hops, given=d_given, produced=d_produced, figures=figs, source=source)
    return ov, deep


# ------------------------------------------------------------------ office
def office_lights():
    R = load("replay.js")
    M, S = R["modes"]["pir+co2"], R["modes"]["schedule"]
    log, mt = M["log"], M["metrics"]
    by = {m["id"]: m for m in log}
    ac = first(log, lambda m: m["topic"].endswith("/ac") and m.get("payload") is True and m.get("cause") in by)
    acm = by[ac["cause"]]
    vent = first(log, lambda m: m["topic"].endswith("/vent") and m.get("cause") in by)
    co2 = by[vent["cause"]]
    opt = first(log, lambda m: m["topic"].endswith("/optimum_start"))
    off = first(log, lambda m: m["topic"].endswith("/light") and m.get("payload") is False and m.get("cause") in by)
    vac = by[off["cause"]]
    saving = round(100 * (1 - mt["total_kwh"] / S["metrics"]["total_kwh"]))
    figs = ((f"{saving}%", "less light + AC energy"), (f"{S['metrics']['room_min_lit_empty']:,} → {mt['room_min_lit_empty']:,}", "room-min lit while empty"),
            (str(mt["false_offs"]), "lights off on someone"))
    arch = "Rules on an MQTT-style bus: motion, CO₂ and temperature in, light / AC / ventilation commands out. " + NOMODEL
    return _pair(
        "office-lights", "Office · lights & AC", "Motion and CO₂ decide the lights, AC and ventilation of every room, against a fixed timetable.",
        arch, "the day's people · motion + CO₂ rules", "the rule set picked in the header",
        f"{mt['total_kwh']} kWh against {S['metrics']['total_kwh']} on a timetable", "same people, same day",
        (Stage("Sense", "Motion sensors, CO₂ and temperature in every room", "sim.Sim._pir() / _report()", "motion · ppm · °C"),
         Stage("Vacant?", "No motion for the room's timeout: vacant", "rules.Automation", "vacant"),
         Stage("Lights", "Off when vacant, on with motion; CO₂ holds them if someone sits still", "rules.Automation", "light cmd"),
         Stage("AC & air", "Optimum start before the day; ventilation boost on high CO₂", "rules.Automation", "ac / vent cmd"),
         Stage("Physics", "Light load, AC power, room heat and CO₂ respond", "devices.RoomEnv", "kWh"),
         Stage("Compare", "The same day under a fixed timetable and motion alone", "export.run_all()", "the Compare tab")),
        figs,
        (Layer("room", "Rooms", "people, air, heat"), Layer("sense", "Sensors", "motion, CO₂, temperature"),
         Layer("bus", "Message bus", "messages with causes"), Layer("rules", "Automation", "lights, AC, air")),
        (C("people", "People", "room", "sim.Sim._step_person()", 0), C("air", "Room air & heat", "room", "devices.RoomEnv", 2),
         C("pir", "Motion sensor", "sense", "sim.Sim._pir()", 0), C("co2s", "CO₂ / temp sensor", "sense", "sim.Sim._report()", 2),
         C("bus", "Bus", "bus", "bus.Bus.publish()", 1),
         C("lights", "Light rule", "rules", "rules.Automation", 0), C("hvac", "AC & air rule", "rules", "rules.Automation", 2)),
        (Hop("pir", "bus", j(acm), "Someone moves in the meeting room.", acm["topic"]),
         Hop("bus", "hvac", j(ac), f"The room is occupied inside its AC window: AC on, citing motion {acm['id']}.", ac["topic"]),
         Hop("co2s", "hvac", j(opt), "Before the day: the room is warm, so the AC starts early enough to reach 24 °C on time.", opt["topic"]),
         Hop("air", "co2s", j(co2), "Thirty people breathing: the open workspace's CO₂ rises.", co2["topic"]),
         Hop("co2s", "hvac", j(vent), f"Above the limit: ventilation boost, citing reading {co2['id']}.", vent["topic"]),
         Hop("bus", "lights", j(vac), "No motion for the room's timeout: vacant.", vac["topic"]),
         Hop("lights", "air", j(off), f"Lights off, citing {vac['id']}; the light load falls on the next step.", off["topic"])),
        "a working day of people in rooms", "light, AC and ventilation decisions with their causes",
        "viewer/replay.js (day 7, Motion + CO₂)", "Real messages: an AC turned on by motion, an optimum start, a CO₂ boost, a corridor going dark.")


def office_attendance():
    R = load("replay.js")
    M = R["modes"]["pir+co2"]
    log, mt = M["log"], M["metrics"]
    by = {m["id"]: m for m in log}
    badge = first(log, lambda m: m["topic"] == "office/gate/badge")
    who = badge["text"].split(" badged")[0]
    wifi = first(log, lambda m: m["topic"] == "office/wifi/presence" and who in m["text"])
    tg = first(log, lambda m: m["topic"] == "office/alert/tailgate")
    beam = by.get(tg.get("cause"))
    rez = first(log, lambda m: m["topic"] == "office/gate/rezero")
    late = next((m for m in log if m["topic"] == "office/alert/late"), None)
    figs = ((f"{mt['tailgates_caught']}/{mt['tailgates_true']}", "tailgates caught"),
            (f"{mt['rollcall_estimate_mean_err']} → {mt['rollcall_wifi_mean_err']}", "roll-call error, people"),
            (str(mt["register_count"]), "in the register"))
    arch = "Badge readers, door beam counters and Wi-Fi presence reconciled by rules. " + NOMODEL
    hops = [Hop("door", "badge", j(badge), "A badge read at the main gate.", badge["topic"]),
            Hop("badge", "att", j({"person": who, "checkin": clock(badge["t"])}), "The first badge of the day goes into the register" + (" and is checked against 09:15." if late else "."), "register")]
    if beam:
        hops.append(Hop("door", "beam", j(beam), "The door's beam counts one person in.", beam["topic"]))
    hops += [Hop("beam", "att", j(tg), "A beam count with no badge read inside the window: a possible tailgate.", tg["topic"]),
             Hop("ap", "att", j(wifi), f"{wifi['t'] - badge['t']} s after the badge, the same person's phone joins the Wi-Fi.", wifi["topic"]),
             Hop("att", "roll", j(rez), "Door counters drift; after 15 minutes of disagreement they are re-zeroed to the badge estimate.", rez["topic"]),
             Hop("roll", "ui", j({"badges_alone_mean_err": mt["rollcall_estimate_mean_err"], "badges_wifi_mean_err": mt["rollcall_wifi_mean_err"]}), "A phone on the Wi-Fi outvotes a stale badge-out: the roll-call stays within a fraction of a person.", "roll-call")]
    return _pair(
        "office-attendance", "Office · attendance & roll-call", "Who is in the building, from badges, door beams and phones on the Wi-Fi.",
        arch, "badge reads, door beams, Wi-Fi joins", "the same in every rule set",
        f"{mt['register_count']} checked in, {mt['tailgates_caught']} of {mt['tailgates_true']} tailgates caught, roll-call ±{mt['rollcall_wifi_mean_err']}",
        "against the simulator's truth",
        (Stage("Badge", "First badge-in, lateness after 09:15, badge-outs", "rules.Attendance._on_badge()", "register"),
         Stage("Count", "Beams at every badge door, in and out", "rules.Attendance._on_beam()", "counts"),
         Stage("Tailgates", "A count with no badge read in the window", "rules.Attendance.tick()", "alerts"),
         Stage("Phones", "Wi-Fi joins 20–90 s after arrival, drops 5 min after leaving", "sim.Sim._wifi()", "presence"),
         Stage("Roll-call", "Badges + Wi-Fi: a connected phone means inside", "rules.Attendance.estimate_with_wifi()", "people inside")),
        figs,
        (Layer("door", "Doors", "people crossing"), Layer("sense", "Readers", "badge, beam, access point"),
         Layer("rules", "Attendance", "register and reconciliation"), Layer("out", "Roll-call", "who is inside now")),
        (C("door", "Badge door", "door", "sim.Sim._room_change()", 0), C("badge", "Badge reader", "sense", "sim.Sim._room_change()", 0),
         C("beam", "Door beam", "sense", "sim.Sim._room_change()", 1), C("ap", "Wi-Fi AP", "sense", "sim.Sim._wifi()", 2),
         C("att", "Attendance", "rules", "rules.Attendance", 1), C("roll", "Roll-call", "out", "rules.Attendance.estimate_with_wifi()", 0),
         C("ui", "Attendance tab", "out", "viewer/app.js", 2)),
        tuple(hops), "people coming and going all day", "a register, tailgate alerts, an evacuation roll-call",
        "viewer/replay.js (day 7)", "Real messages: a badge, a phone joining, a tailgate, the counters re-zeroed.")


# ------------------------------------------------------------------ home
def home_gridsense():
    H = load("home_replay.js")["june"]
    G = H["modes"]["gridsense"]
    log, mt, dm = G["log"], G["metrics"], H["modes"]["default"]["metrics"]
    inv = first(log, lambda m: m["topic"] == "home/inverter/settings")
    pump = first(log, lambda m: m["topic"].endswith("/pump") and m.get("payload") is True)
    wash = first(log, lambda m: m["topic"].endswith("/washer") and m.get("payload") is True)
    out0 = H["outages"][0]
    s = G["series"]
    k = s["t"].index(next(t for t in s["t"] if t >= 12 * 3600))
    figs = ((f"{dm['house_dark_min']} → {mt['house_dark_min']}", "dark minutes"), (f"Rs {mt['bill_rs']}", "the day's bill"),
            (f"{mt['solar_used_pct']}%", "solar used"))
    arch = "A planning controller: a reserve sized for the next published cut, plus rules for spare sun and low voltage. " + NOMODEL
    return _pair(
        "home-gridsense", "Home · GridSense", "An energy manager that plans the battery around Lahore's published load-shedding.",
        arch, "June · category IV · 6 kWp · 10 kWh", "the inputs of “Run with your values”",
        f"{mt['house_dark_min']} dark minutes (default {dm['house_dark_min']}), Rs {mt['bill_rs']}", "same family, same cuts",
        (Stage("Read the schedule", "Published outages, the solar forecast, the battery", "gridsense.GridSense", "plan"),
         Stage("Keep a reserve", "Enough battery for the next cut, topped up off-peak", "gridsense.GridSense", "SOC floor"),
         Stage("Use spare sun", "Pump, washer and iron when the panels have surplus", "gridsense.GridSense", "start cmds"),
         Stage("Before a cut", "Fill the tank, pre-cool bedrooms if it fits the inverter", "gridsense.GridSense", "pre-cool"),
         Stage("Inverter", "Mode and floor set on the hybrid inverter", "power.Inverter", "kW flows")),
        figs,
        (Layer("grid", "Grid & sun", "feeder, panels"), Layer("power", "Power hardware", "inverter, battery, tank"),
         Layer("ctrl", "GridSense", "plans and rules"), Layer("out", "Record & view", "power flow, decisions")),
        (C("feeder", "Feeder schedule", "grid", "home._outages()", 0), C("sun", "Solar panels", "grid", "power.Inverter", 2),
         C("inv", "Inverter + battery", "power", "power.Inverter", 0), C("tank", "Pump & washer", "power", "home_sim.HomeSim", 2),
         C("gs", "GridSense", "ctrl", "gridsense.GridSense", 1), C("ui", "Power flow", "out", "viewer/home.js", 1)),
        (Hop("feeder", "gs", j(out0), f"Published: a cut {clock(out0['start'])}–{clock(out0['end'])}.", "schedule"),
         Hop("gs", "inv", j(inv), "The inverter's mode and battery floor, with the reason in the message.", inv["topic"]),
         Hop("gs", "tank", j(pump), "Before the cut, fill the roof tank while there is grid.", pump["topic"]),
         Hop("sun", "gs", j({"t": clock(s["t"][k]), "pv_kw": s["pv_kw"][k], "load_kw": s["load_kw"][k], "soc": s["soc"][k]}), "Midday: the panels make more than the house uses.", "minute series"),
         Hop("gs", "tank", j(wash), "Spare sun covers the washer: it starts now instead of in the evening peak.", wash["topic"]),
         Hop("inv", "ui", j({"house_dark_min": mt["house_dark_min"], "bill_rs": mt["bill_rs"], "solar_used_pct": mt["solar_used_pct"]}), "The day's result, against the inverter's own default.", "metrics")),
        "a June day with published and unannounced cuts", "inverter settings, starts, a full tank, no dark minutes",
        "viewer/home_replay.js (June, day 7)", "Real decisions: an outage, the inverter's floor, the tank, the washer on spare sun.")


def home_people():
    H = load("home_replay.js")["june"]
    G = H["modes"]["gridsense"]
    log = G["log"]
    names = {p["id"]: p for p in H["people"]}
    g_out = H["gate"][0]
    guest = next((g for g in H["gate"] if g[1].startswith("g") and g[2] == "in"), H["gate"][-1])
    gmsg = first(log, lambda m: m["topic"] == "home/gate/count" and m["t"] == guest[0])
    by = {m["id"]: m for m in log}
    dfan = next((m for m in log if m["topic"] == "home/drawing/fan" and m.get("payload") is True and m["t"] >= guest[0]), None)
    want = by.get(dfan["cause"]) if dfan else None
    figs = ((str(len(H["gate"])), "gate crossings"), (str(sum(1 for p in H["people"] if p["role"] in ("relative", "grandparent"))), "guests"),
            (str(max(g[3] for g in H["gate"])), "most at home"))
    arch = "A beam counter at the gate and presence per room driving fans and lights. " + NOMODEL
    hops = [Hop("fam", "gate", j({"t": clock(g_out[0]), "person": names[g_out[1]]["name"], "role": names[g_out[1]]["role"], "way": g_out[2]}), "The school van at the gate: a child walks out.", "beam"),
            Hop("gate", "bus", j(first(log, lambda m: m["topic"] == "home/gate/count")), "The counter publishes how many are home.", "home/gate/count"),
            Hop("fam", "gate", j({"t": clock(guest[0]), "person": names[guest[1]]["name"], "role": names[guest[1]]["role"], "way": "in"}), "Evening: relatives arrive and sit in the drawing room.", "beam"),
            Hop("gate", "bus", j(gmsg), "The head count rises with every guest.", gmsg["topic"])]
    if dfan and want:
        hops += [Hop("bus", "rule", j(want), "People in the drawing room, and it is warm: they want the fan.", want["topic"]),
                 Hop("rule", "dev", j(dfan), f"Fan on, citing {want['id']}.", dfan["topic"])]
    hops.append(Hop("bus", "ui", j({"at_home": gmsg["payload"], "tab": "People", "log": "Gate counter"}), "The People tab: who is home, who is out and why, the gate log.", "viewer"))
    return _pair(
        "home-people", "Home · who's home", "A family's comings and goings counted at the gate, and the house following them.",
        arch, "the family's day: school, office, tuition, errands, guests", "drawn per day (seed)",
        f"{len(H['gate'])} crossings counted; fans and lights follow presence", "the People tab",
        (Stage("Plan the day", "Reasons for every absence; visitors some days", "home.build()", "stays"),
         Stage("Gate counter", "Every crossing in or out, with the head count", "home_sim.HomeSim._gate()", "home/gate/count"),
         Stage("Presence", "Who is in each room, every second", "home_sim.HomeSim._update_wants()", "wants"),
         Stage("Fans & lights", "Follow the people in each room", "home_sim.HomeSim", "device on/off"),
         Stage("People tab", "At home, out and why, visitors due, the gate log", "viewer/home.js renderPeople()", "the panel")),
        figs,
        (Layer("fam", "Family & guests", "who comes and goes"), Layer("sense", "Gate & rooms", "counter, presence"),
         Layer("bus", "Bus & rules", "wants and commands"), Layer("out", "Devices & view", "fans, People tab")),
        (C("fam", "Family & guests", "fam", "home.build()", 1), C("gate", "Gate counter", "sense", "home_sim.HomeSim._gate()", 0),
         C("bus", "Bus", "bus", "bus.Bus.publish()", 0), C("rule", "Room wants", "bus", "home_sim.HomeSim._update_wants()", 2),
         C("dev", "Drawing-room fan", "out", "home_sim.HomeSim", 2), C("ui", "People tab", "out", "viewer/home.js", 0)),
        tuple(hops), "a family's day and its visitors", "a head count, a gate log, devices following people",
        "viewer/home_replay.js (June, day 7)", "Real crossings from one day: the school van out, relatives in, the drawing-room fan on.")


# ------------------------------------------------------------------ hospital
def _hosp():
    P = load("hospital_replay.js")
    return P, P["modes"]["connected"], P["modes"]["today"]


def hospital_ed():
    P, Cn, Td = _hosp()
    log, mt, m0 = Cn["log"], Cn["metrics"], Td["metrics"]
    arr = first(log, lambda m: m["topic"].endswith("/arrival"))
    tri = first(log, lambda m: m["topic"].endswith("/triage") and m.get("cause") == arr["id"])
    rec = Cn["records"][0]
    seen = next((m for m in log if m["topic"] == f"hospital/ed/{rec['id']}/seen"), None)
    left = next((m for m in log if m["topic"] == f"hospital/ed/{rec['id']}/left"), None)
    figs = ((str(mt["ed_arrivals"]), "arrivals"), (f"{mt['door_to_doctor_all_min']} min", "door to doctor"), (str(mt["left_unseen"]), "left unseen"))
    arch = "Patients and staff as agents on a shared task board, five-colour triage. " + NOMODEL
    hops = [Hop("pat", "clerk", j(arr), "A patient walks in and queues to register.", arr["topic"]),
            Hop("clerk", "board", j(tri), "Registered and triaged; the colour sets their place in every queue.", tri["topic"])]
    if seen:
        hops.append(Hop("board", "doc", j(seen), "A doctor takes the assessment task from the board.", seen["topic"]))
    if left:
        hops.append(Hop("doc", "rec", j(left), "Results back, reviewed, sent home.", left["topic"]))
    hops.append(Hop("rec", "ui", j(rec, ["id", "colour", "arrive", "registered", "triaged", "placed", "place", "seen", "results", "left", "outcome"]),
                    "The record behind the emergency board: every timestamp from the door to going home.", "record"))
    return _pair(
        "hospital-ed", "Hospital · emergency department", "A day of arrivals through registration, triage, a bed, a doctor, tests and a decision.",
        arch, "day 7 · 100% arrivals", "the inputs of “Run with your values”",
        f"door to doctor {mt['door_to_doctor_all_min']} min, {mt['left_unseen']} left unseen, {mt['admitted']} admitted", "Connected rule set",
        (Stage("Arrive", "On foot or by ambulance", "hospital_sim.HospitalSim.ed_patient()", "arrival"),
         Stage("Register & triage", "Clerk, then a triage nurse; five colours", "hospital_sim.HospitalSim.perform()", "colour"),
         Stage("A place", "Resus, majors, a chair or the waiting hall", "hospital_sim.HospitalSim.free_bed()", "bed"),
         Stage("Doctor", "Assessment by priority; red pauses others", "hospital_sim.HospitalSim.staff_loop()", "seen"),
         Stage("Tests & treatment", "Bloods, X-ray, drips with a pump", "hospital_sim.HospitalSim.perform()", "results"),
         Stage("Decision", "Home, admitted, or another ward", "hospital_sim.HospitalSim.ed_patient()", "outcome")),
        figs,
        (Layer("pat", "Patients", "arrive, wait, leave"), Layer("staff", "Staff agents", "clerk, triage, doctors"),
         Layer("board", "Task board", "who does what next"), Layer("out", "Record & view", "patient record, board")),
        (C("pat", "Patient", "pat", "hospital_sim.HospitalSim.ed_patient()", 1), C("clerk", "Clerk & triage", "staff", "hospital_sim.HospitalSim.perform()", 0),
         C("doc", "Doctor", "staff", "hospital_sim.HospitalSim.staff_loop()", 2), C("board", "Task board", "board", "hospital_sim.HospitalSim.pick()", 1),
         C("rec", "Patient record", "out", "export_hospital.run_all()", 0), C("ui", "Emergency board", "out", "viewer/hospital.js", 2)),
        tuple(hops), "a day of emergency arrivals", "waits, placements, decisions",
        "viewer/hospital_replay.js (day 7, Connected)", "One real patient's way through the emergency department.")


def hospital_alarms():
    P, Cn, Td = _hosp()
    log, mt, m0 = Cn["log"], Cn["metrics"], Td["metrics"]
    by = {m["id"]: m for m in log}
    ans = first(log, lambda m: m["topic"].endswith("/alarm/answered") and m.get("cause") in by)
    alm = by[ans["cause"]]
    hidden = first(Cn["alarms"], lambda a: a.get("hidden"))
    call = next((m for m in log if m["topic"].endswith("/call")), None)
    figs = ((f"{m0['alarms_sounded']} → {mt['alarms_sounded']}", "alarms that sounded"), (str(mt["brief_true_events_not_sounded"]), "brief real events held"),
            (f"{mt['call_response_min']} min", "call answered, median"))
    arch = "Alarms and calls routed to the bed's own nurse's badge, with a short delay for non-critical alarms. " + NOMODEL
    hops = [Hop("mon", "delay", j(hidden), "A brief artefact: held by the 15-second delay and over before anyone is called.", "held"),
            Hop("mon", "delay", j(alm), "A sustained alarm outlasts the delay.", alm["topic"]),
            Hop("delay", "route", j({"bed": alm["topic"].split("/")[2], "to": "that bed's nurse", "critical_skips_delay": True}), "Routed to the nurse assigned to that bed, not to the whole ward.", "badge page"),
            Hop("route", "nurse", j(ans), "The nurse walks to the bed and answers.", ans["topic"])]
    if call:
        hops.append(Hop("btn", "route", j(call), "A call button: routed the same way.", call["topic"]))
    hops.append(Hop("nurse", "ui", j({"today_sounded": m0["alarms_sounded"], "connected_sounded": mt["alarms_sounded"], "held_brief_real": mt["brief_true_events_not_sounded"]}), "Fewer walks to false alarms, and the cost counted beside it.", "metrics"))
    return _pair(
        "hospital-alarms", "Hospital · ward alarms & calls", "Monitor alarms and call buttons on a 36-bed ward, Today against Connected.",
        arch, "day 7 · 3 ward nurses · 15 s alarm delay", "the inputs of “Run with your values”",
        f"alarms {m0['alarms_sounded']} → {mt['alarms_sounded']}, {mt['brief_true_events_not_sounded']} brief real events not sounded", "the same alarms both ways",
        (Stage("Monitor", "HDU monitors raise alarms, most of them artefacts", "hospital.build()", "alarm"),
         Stage("Delay", "Non-critical alarms wait 15 s; critical ones do not", "hospital_sim.HospitalSim.ward_alarm()", "held / sounded"),
         Stage("Route", "To the bed's own nurse's badge", "hospital_sim.HospitalSim._alarm_task()", "page"),
         Stage("Answer", "The nurse walks to the bed", "hospital_sim.HospitalSim.staff_loop()", "answered")),
        figs,
        (Layer("bed", "Beds", "monitors and call buttons"), Layer("logic", "Alarm logic", "delay and routing"),
         Layer("staff", "Nurses", "badges, walking"), Layer("out", "Record & view", "the comparison")),
        (C("mon", "Bedside monitor", "bed", "hospital_sim.HospitalSim.ward_alarm()", 0), C("btn", "Call button", "bed", "hospital_sim.HospitalSim.ward_call()", 2),
         C("delay", "15 s delay", "logic", "hospital_sim.HospitalSim.ward_alarm()", 0), C("route", "Router", "logic", "hospital_sim.HospitalSim._alarm_task()", 2),
         C("nurse", "Bed's nurse", "staff", "hospital_sim.HospitalSim.staff_loop()", 1), C("ui", "Compare", "out", "viewer/hospital.js", 1)),
        tuple(hops), "a day of monitor alarms and call buttons", "alarms sounded and answered, the delay's cost",
        "viewer/hospital_replay.js (day 7, Connected)", "Real alarms: one held by the delay, one routed to its nurse and answered.")


def hospital_equipment():
    P, Cn, Td = _hosp()
    log, mt, m0 = Cn["log"], Cn["metrics"], Td["metrics"]
    fetch = Cn["fetches"][0]
    fetch0 = next((f for f in Td["fetches"] if f["kind"] == fetch["kind"] and f["secs"] > f["direct"]), Td["fetches"][0])
    par = first(log, lambda m: m["topic"].endswith("/below_par"))
    asset = next(a for a in Cn["assets"] if a[1].startswith(fetch["kind"]))
    figs = ((f"{m0['equipment_search_min']:.0f} → {mt['equipment_search_min']:.0f}", "minutes searching"), (f"{m0['drips_without_pump']} → {mt['drips_without_pump']}", "drips without a pump"),
            (str(mt["ed_free_pumps_at_end"]), "free ED pumps at midnight"))
    arch = "Asset tags with an indoor locator and a par level that sends a porter for more. " + NOMODEL
    return _pair(
        "hospital-equipment", "Hospital · equipment locator", "Infusion pumps, chairs and trolleys: walking straight to one instead of searching.",
        arch, "day 7 · pumps, chairs, trolleys tagged", "Connected rule set",
        f"searching {m0['equipment_search_min']:.0f} → {mt['equipment_search_min']:.0f} min a day", "the same fetches both ways",
        (Stage("Need", "A drip needs a pump; a patient needs a chair", "hospital_sim.HospitalSim.perform()", "fetch task"),
         Stage("Locate", "Today: search room by room. Connected: the nearest free one", "hospital_sim.HospitalSim.fetch()", "asset id"),
         Stage("Walk", "Straight to it and back", "hospital_sim.HospitalSim.fetch()", "metres"),
         Stage("Par level", "Below par in the ED: a porter brings more from the basement", "hospital_sim.HospitalSim.par_level()", "porter task")),
        figs,
        (Layer("floor", "Floors", "where the kit is"), Layer("tags", "Tags & locator", "positions of every asset"),
         Layer("staff", "Staff", "nurses, porters"), Layer("out", "Record & view", "equipment list")),
        (C("asset", "Pump (tag)", "floor", "hospital_sim.HospitalSim.asset_moved()", 0), C("store", "Basement store", "floor", "hospital_sim.HospitalSim.par_level()", 2),
         C("loc", "Locator", "tags", "hospital_sim.HospitalSim.free_assets()", 1), C("nurse", "Nurse", "staff", "hospital_sim.HospitalSim.fetch()", 0),
         C("porter", "Porter", "staff", "hospital_sim.HospitalSim.par_level()", 2), C("ui", "Equipment list", "out", "viewer/hospital.js", 1)),
        (Hop("asset", "loc", j({"t": asset[0], "asset": asset[1], "building": asset[2], "x": asset[3], "y": asset[4], "held_by": asset[5]}), "Every pump's tag reports where it is.", "asset position"),
         Hop("nurse", "loc", j({"need": fetch["kind"], "for": "a drip", "unit": fetch["unit"]}), "A drip needs a pump.", "request"),
         Hop("loc", "nurse", j(fetch), f"Connected: straight to the nearest free one, {fetch['secs']} s.", "fetch"),
         Hop("nurse", "ui", j(fetch0), f"Today, the same need: {fetch0['secs']} s, {fetch0['secs'] - fetch0['direct']} s of it searching.", "fetch (Today)"),
         Hop("loc", "porter", j(par), "Too few pumps left in the ED: a porter is sent to the basement.", par["topic"]),
         Hop("porter", "store", j({"from": "basement store", "to": "ED", "kind": "pump"}), "Spare pumps come up before a drip runs without one.", "porter task")),
        "a day of drips, chairs and transfers", "time searching, drips without a pump",
        "viewer/hospital_replay.js (day 7)", "Real fetches: a pump found in seconds under Connected, the search it took Today.")


def hospital_families():
    P, Cn, Td = _hosp()
    mt, m0 = Cn["metrics"], Td["metrics"]
    att = next((k, v) for k, v in Cn["agents"].items() if v["role"] == "attendant" and "-a" in k)
    att_labels = [l for l in Cn["labels"] if l[1] == att[0]][:3]
    watt = next((k, v) for k, v in Cn["agents"].items() if v["role"] == "attendant" and k.endswith("-att"))
    w_labels = [l for l in Cn["labels"] if l[1] == watt[0]][:3]
    vis = next(k for k, v in Cn["agents"].items() if v["role"] == "visitor")
    v_labels = [l for l in Cn["labels"] if l[1] == vis][:3]
    figs = ((f"{m0['ed_attendants_in_bays_mean']} → {mt['ed_attendants_in_bays_mean']}", "relatives in the bays"),
            (f"{m0['visitor_min_outside_hours']:,} → {mt['visitor_min_outside_hours']}", "visitor-min outside hours"),
            (str(mt["visitors_turned_away"]), "families turned away"))
    arch = "Relatives as agents following their patient; an attendant card and a visitor pass desk as rules. " + NOMODEL
    return _pair(
        "hospital-families", "Hospital · families & passes", "Nobody comes alone: attendants at the bedside, a relative overnight, visitors at four.",
        arch, "1–3 relatives an emergency patient, one overnight per ward bed", "assumptions, labelled",
        f"bays {m0['ed_attendants_in_bays_mean']} → {mt['ed_attendants_in_bays_mean']} relatives; {mt['visitors_turned_away']} families turned away", "Today vs Connected",
        (Stage("Come with the patient", "1–3 relatives follow them through the department", "hospital_sim.HospitalSim.ed_attendant()", "followers"),
         Stage("Attendant card", "Connected: one at the bedside, the rest outside", "hospital_sim.HospitalSim.ed_attendant()", "1 inside"),
         Stage("Overnight & pharmacy", "One relative stays and buys the medicines", "hospital_sim.HospitalSim.ward_attendant()", "trip"),
         Stage("Visiting hours", "Pass desk: 16:00–18:00, two per bed", "hospital_sim.HospitalSim.ward_visitor()", "passes"),
         Stage("Count", "Relatives in the bays and on the ward, every minute", "hospital_sim.HospitalSim._family_census()", "metrics")),
        figs,
        (Layer("fam", "Families", "relatives and visitors"), Layer("rules", "Cards & passes", "who may go in"),
         Layer("places", "Bays & ward", "where they stand"), Layer("out", "Record & view", "the comparison")),
        (C("att", "ED attendant", "fam", "hospital_sim.HospitalSim.ed_attendant()", 0), C("watt", "Overnight relative", "fam", "hospital_sim.HospitalSim.ward_attendant()", 1),
         C("vis", "Visitor", "fam", "hospital_sim.HospitalSim.ward_visitor()", 2), C("card", "Attendant card", "rules", "hospital_sim.HospitalSim.ed_attendant()", 0),
         C("desk", "Pass desk", "rules", "hospital_sim.HospitalSim.ward_visitor()", 2), C("ward", "Ward & pharmacy", "places", "hospital_sim.HospitalSim._family_census()", 1),
         C("ui", "Compare", "out", "viewer/hospital.js", 1)),
        (Hop("att", "card", j({"agent": att[0], **att[1], "labels": att_labels}), "A relative follows the patient in; the card decides who stays at the bedside.", "agent"),
         Hop("watt", "ward", j({"agent": watt[0], "name": watt[1]["name"], "labels": w_labels}), "The relative who stays the night, and goes down for the medicines after the round.", "agent"),
         Hop("vis", "desk", j({"agent": vis, "labels": v_labels}), "A visitor at the lobby: before four they wait downstairs, after six they are turned away.", "agent"),
         Hop("desk", "ward", j({"most_at_one_bed": mt["most_visitors_at_a_bed"], "peak_on_ward": mt["ward_visitors_peak"]}), "Two per bed, and the four o'clock rush it causes.", "census"),
         Hop("ward", "ui", j({k: [m0[k], mt[k]] for k in ("ed_attendants_in_bays_mean", "visitor_min_outside_hours", "visitors_turned_away")}), "Today against Connected, the cost counted with the gain.", "metrics")),
        "relatives with every patient, visitors through the day", "crowding in the bays and on the ward, the cost of the passes",
        "viewer/hospital_replay.js (day 7)", "Real relatives from one day: an attendant, an overnight relative, a visitor at the desk.")


# ------------------------------------------------------------------ traffic
def _traffic():
    T = load("traffic_replay.js")
    return T, T["modes"]["fixed"], T["modes"]["adaptive"]


def traffic_trips():
    T, F, A = _traffic()
    ma = A["metrics"]
    i = next(k for k, v in enumerate(A["vehicles"]) if any(e[3] >= 0 and e[1] for e in v[6]) and len(T["routes"][k]) > 20)
    v = A["vehicles"][i]
    stop = next(e for e in v[6] if e[3] >= 0)
    poi = T["pois"][stop[3]]
    purpose = T["purposes"][T["trip_purpose"][i]]
    rk = next(k for k, v2 in enumerate(A["vehicles"]) if T["kinds"][v2[0]] == "rickshaw" and any(e[3] < 0 for e in v2[6]))
    figs = ((f"{ma['errand_stops']:,}", "stops at real places"), (f"{ma['passenger_stops']:,}", "passenger stops"), (f"{ma['ended_at_a_place']}", "trips ended at a place"))
    arch = "A trip generator over OpenStreetMap shops and amenities; kerb stops and parking in the simulation. " + NOMODEL
    return _pair(
        "traffic-trips", "Traffic · trips & shops", "Why people drive in the evening, and the real places they stop at.",
        arch, "evening · 8,000 trips/h", "the inputs of “Run with your values”",
        f"{ma['errand_stops']:,} stops at {len(T['pois'])} real places", "adaptive signals",
        (Stage("Places", "432 shops and amenities from OpenStreetMap, on their street", "traffic_sim.snap_pois()", "access links"),
         Stage("Purpose", "Home, shopping, pharmacy, takeaway, prayers, fuel…", "traffic_sim.make_demand()", "purpose"),
         Stage("Choose a place", "The most convenient of four that sell it", "traffic_sim.make_demand() errand()", "route + stop"),
         Stage("Stop", "Kerb lane for short stops, off the road to park", "traffic_sim.TrafficSim._start_errand()", "held"),
         Stage("Passengers", "Rickshaws and wagons stop anywhere along the kerb", "traffic_sim.make_demand()", "stops")),
        figs,
        (Layer("map", "Map", "places and streets"), Layer("dem", "Demand", "purposes and routes"),
         Layer("drive", "Driving", "stops and parking"), Layer("out", "Record & view", "Places tab, Follow")),
        (C("poi", "Shops & amenities", "map", "traffic_sim.snap_pois()", 0), C("gen", "Trip generator", "dem", "traffic_sim.make_demand()", 1),
         C("veh", "Vehicle", "drive", "traffic_sim.TrafficSim.step()", 0), C("stop", "Stops & parking", "drive", "traffic_sim.TrafficSim._start_errand()", 2),
         C("ui", "Places tab", "out", "viewer/traffic.js renderPlaces()", 1)),
        (Hop("poi", "gen", j({"name": poi[3], "kind": T["poi_kinds"][poi[2]], "x": poi[0], "y": poi[1]}), "A real place, snapped to the street it opens onto.", "place"),
         Hop("gen", "veh", j({"vehicle": i, "kind": T["kinds"][v[0]], "why": purpose, "route_links": len(T["routes"][i])}), "The trip and its reason; routed via the place.", "trip"),
         Hop("veh", "stop", j({"what": stop[2], "from": clock(T["meta"]["start"] + stop[0]), "to": clock(T["meta"]["start"] + stop[1]), "at": poi[3]}), "It pulls in to park; the stop's time is not counted as delay.", "stop log"),
         Hop("gen", "stop", j({"vehicle": rk, "kind": "rickshaw", "stops": A["vehicles"][rk][6][:3]}), "A rickshaw stops for passengers at the kerb, holding the lane behind it.", "stop log"),
         Hop("stop", "ui", j({"errand_stops": ma["errand_stops"], "passenger_stops": ma["passenger_stops"], "busiest": "Places tab"}), "The busiest places this hour, and who is parked at each.", "metrics")),
        "an evening's trips with reasons", "stops at real places, passenger stops",
        "viewer/traffic_replay.js (evening, seed 7)", "Real trips: a shopping stop at a named shop, a rickshaw picking up passengers.")


def traffic_signals():
    T, F, A = _traffic()
    mf, ma = F["metrics"], A["metrics"]
    sig = next(s for s in T["signal_sites"] if s["name"] == mf["worst_junctions"][0][0])
    lf, la = F["signals"][str(sig["id"])][:6], A["signals"][str(sig["id"])][:6]
    figs = ((f"{mf['signal_delay_veh_h']} → {ma['signal_delay_veh_h']}", "veh-h stopped at signals"), (str(len(T["signal_sites"])), "signals"),
            (f"{mf['delay_median_s']:.0f} → {ma['delay_median_s']:.0f} s", "median delay"))
    arch = "Two-phase signal controllers: a fixed 60 s / 30 s plan, or loop detectors that hold the green. " + NOMODEL
    return _pair(
        "traffic-signals", "Traffic · signals", "Where Lahore's signals stand, how they are timed, and fixed against adaptive.",
        arch, "the same evening's trips", "fixed and adaptive rule sets",
        f"stopped at signals {mf['signal_delay_veh_h']} → {ma['signal_delay_veh_h']} veh-h", "same vehicles",
        (Stage("Where", "Two named through roads crossing at grade", "roads.signal_sites()", "59 junctions"),
         Stage("Phases", "Approaches split into two phases by direction", "traffic_sim.build_signals()", "phases"),
         Stage("Fixed", "Bigger road 60 s, side road 30 s, amber 3 s, all-red 2 s", "traffic_sim.TrafficSim.tick_signals()", "100 s cycle"),
         Stage("Adaptive", "Detectors 40 m back hold the green; end on a 3 s gap", "traffic_sim.TrafficSim._detect()", "gap-out"),
         Stage("Measure", "Vehicle-hours stopped at each junction", "traffic_sim.TrafficSim.metrics()", "hotspots")),
        figs,
        (Layer("road", "Junction", "approaches and queues"), Layer("det", "Detectors", "loops 40 m back"),
         Layer("ctrl", "Controller", "fixed or adaptive"), Layer("out", "Record & view", "phase log, countdown")),
        (C("app", "Approaches", "road", "traffic_sim.build_signals()", 0), C("q", "Queue", "road", "traffic_sim.TrafficSim._ahead()", 2),
         C("loop", "Loop detector", "det", "traffic_sim.TrafficSim._detect()", 1), C("fix", "Fixed plan", "ctrl", "traffic_sim.TrafficSim.tick_signals()", 0),
         C("ada", "Adaptive", "ctrl", "traffic_sim.TrafficSim.tick_signals()", 2), C("ui", "Junction panel", "out", "viewer/traffic.js renderJunction()", 1)),
        (Hop("app", "fix", j({"signal": sig["name"], "phases": [len(p) for p in sig["phases"]], "greens_s": sig.get("greens")}), "The worst junction of the evening: its two phases and their fixed greens.", "controller"),
         Hop("fix", "q", j({"log": lf}), "Fixed: the same split all evening; queues wait out the side road's red.", "phase log (fixed)"),
         Hop("q", "loop", j({"detect_m": 40, "gap_s": 3, "min_green_s": 10, "max_green": "1.5 × fixed"}), "Vehicles over the loop keep the green alive.", "detector"),
         Hop("loop", "ada", j({"log": la}), "Adaptive: each green ends on a gap, so the split follows the traffic.", "phase log (adaptive)"),
         Hop("ada", "ui", j({"worst_fixed": mf["worst_junctions"][:3], "signal_veh_h": [mf["signal_delay_veh_h"], ma["signal_delay_veh_h"]]}), "Hotspots and the countdown on each signal head.", "metrics")),
        "an evening's traffic at 59 signals", "phase logs, time lost per junction, fixed vs adaptive",
        "viewer/traffic_replay.js (evening, seed 7)", "Real phase logs from the worst junction, fixed and adaptive.")


def traffic_map():
    T, F, A = _traffic()
    v = A["vehicles"][3]
    figs = ((str(len(T["tiles"])), "map tiles of 400 m"), (f"{len(T['roads']):,}", "road pieces"), (f"{T['meta']['sample']} s", "position samples"))
    arch = "A compact replay (routes once, positions as whole-metre deltas) streamed into a canvas map by tiles. " + NOMODEL
    return _pair(
        "traffic-map", "Traffic · the streaming map", "How the map loads around the camera like a game map, and how a vehicle is redrawn from a few numbers.",
        arch, "the recorded evening", "viewer/traffic_replay.js",
        "a map that streams in around you; any vehicle can be followed", "in the browser, offline",
        (Stage("Record compactly", "Routes stored once; positions as whole-metre deltas every 4 s", "export_traffic._mode_replay()", "deltas"),
         Stage("Tiles", "Roads indexed by 400 m tile", "export_traffic.run_all()", "tile → roads"),
         Stage("Stream", "Tiles in view fade in; tiles left behind are released", "viewer/traffic.js draw()", "loaded tiles"),
         Stage("Decode", "Distance along the route → link → point and lane offset", "viewer/traffic.js vehAt()", "x, y"),
         Stage("Follow", "The camera rides along; a minimap shows where", "viewer/traffic.js frame()", "camera")),
        figs,
        (Layer("file", "Replay file", "what was recorded"), Layer("load", "Streaming", "tiles in view"),
         Layer("draw", "Drawing", "roads, vehicles"), Layer("you", "You", "camera, follow")),
        (C("rep", "traffic_replay.js", "file", "export_traffic.run_all()", 1), C("tiles", "Tile index", "load", "viewer/traffic.js visibleTiles()", 0),
         C("dec", "Decoder", "load", "viewer/traffic.js vehiclesOf()", 2), C("roads", "Road painter", "draw", "viewer/traffic.js draw()", 0),
         C("veh", "Vehicle painter", "draw", "viewer/traffic.js vehAt()", 2), C("cam", "Camera & follow", "you", "viewer/traffic.js frame()", 1)),
        (Hop("rep", "tiles", j({"tile_m": T["meta"]["tile"], "tiles": len(T["tiles"]), "example": {k: T["tiles"][k][:6] for k in list(T["tiles"])[:1]}}), "Roads are indexed by 400 m tile.", "tiles"),
         Hop("cam", "tiles", j({"zoom": "street level", "in_view": "6 tiles", "released_after_s": 2}), "Only tiles near the camera are drawn; ones left behind are let go.", "view"),
         Hop("rep", "dec", j({"vehicle": [T["kinds"][v[0]], v[1], v[2], v[3]], "deltas_m": v[4][:12], "lane_changes": v[5][:3]}), "One vehicle: kind, times, and how far it moved every 4 s, in whole metres.", "record"),
         Hop("dec", "veh", j({"route_links": len(T["routes"][3]), "cum_m": sum(v[4][:12]), "drives_on": "the left"}), "Summed deltas give the distance along its route; the link and lane give its point on the road.", "position"),
         Hop("veh", "cam", j({"follow": "vehicle #4", "minimap": True}), "Follow it: the camera glides with it, the map streams in ahead.", "camera")),
        "the recorded evening", "a map you can fly over and ride along in",
        "viewer/traffic_replay.js", "Real records: a tile, one vehicle's metre deltas, decoded to a point on the road.")


# ------------------------------------------------------------------ junction planner
def _jn():
    return load("junctions_replay.js")


def junctions_fixes():
    J = _jn()
    j0 = J["junctions"][0]
    f = j0["fixes"]
    figs = ((f"{f['baseline']['junction_veh_h']}", "veh-h lost today"), (f"{f['uturn']['junction_veh_h']}", "after a U-turn conversion"),
            (f"+{f['uturn']['km_extra']:.0f} km", "its cost in driving"))
    arch = "The traffic simulation re-run per fix: Webster retiming, per-junction adaptive, turn bans with rerouting, an underpass. " + NOMODEL
    return _pair(
        "junctions-fixes", "Junction planner · fixes", f"{j0['name']}: retime, adaptive, U-turn conversion or underpass, on the same trips.",
        arch, "the evening's worst junctions", "seed 7, 8,000 trips/h, 30 min",
        f"{f['baseline']['junction_veh_h']} → {f['retime']['junction_veh_h']} / {f['adaptive']['junction_veh_h']} / {f['uturn']['junction_veh_h']} / {f['underpass']['junction_veh_h']} veh-h", "retime / adaptive / U-turn / underpass",
        (Stage("Worst", "Rank junctions by time lost", "junctions.run_all()", "3 junctions"),
         Stage("Retime", "Webster split from per-lane demand", "junctions.webster()", "greens"),
         Stage("Adaptive", "Detectors at this junction only", "Signal.adaptive", "gap-out"),
         Stage("U-turn", "Close the crossing; median gaps; reroute", "junctions.uturn_conversion() / reroute()", "new routes"),
         Stage("Underpass", "Main road straight on skips the signal", "TrafficSim.underpass", "signal-free"),
         Stage("Compare", "Time lost, queues, extra km, pedestrians", "junctions.run_fix()", "table")),
        figs,
        (Layer("net", "Network", "roads and movements"), Layer("fix", "Fixes", "one per scenario"),
         Layer("sim", "Re-run", "same trips"), Layer("out", "Planner", "map and table")),
        (C("mv", "Movements", "net", "junctions.Movements", 0), C("gaps", "Median gaps", "net", "junctions.uturn_conversion()", 2),
         C("web", "Webster", "fix", "junctions.webster()", 0), C("ban", "Turn bans", "fix", "junctions.Movements.banned_at()", 2),
         C("run", "Scenario run", "sim", "junctions.run_fix()", 1), C("ui", "Fix table", "out", "viewer/junctions.js renderPlan()", 1)),
        (Hop("mv", "ban", j({"junction": j0["name"], "allowed": "main straight on, left turns", "banned": "crossing, right turns"}), "Movements judged whole, approach to exit.", "turn bans"),
         Hop("gaps", "ban", j({"gaps_m_from_centre": j0["gaps"]}), "Gaps across the median 150-400 m away for the U-turn.", "gaps"),
         Hop("ban", "run", j({k: f["uturn"][k] for k in ("rerouted", "junction_veh_h", "km_extra")}), "Rerouted trips, the same demand, run again.", "U-turn result"),
         Hop("web", "run", j({"greens_s": f["retime"]["greens"], "junction_veh_h": f["retime"]["junction_veh_h"]}), "Webster gives the side road the long green here.", "retime result"),
         Hop("run", "ui", j({k: f[k]["junction_veh_h"] for k in ("baseline", "retime", "adaptive", "uturn", "underpass")}), "Every fix on the same trips, with what each costs.", "table")),
        "the worst junction and the evening's trips", "time lost per fix, extra driving, pedestrian cost",
        "viewer/junctions_replay.js (seed 7)", "Real results at Firozpur Road / Wahdat Road, fix by fix.")


def junctions_ambulance():
    J = _jn()
    S = J["ambulance"]["summary"]
    call = J["ambulance"]["calls"][1]
    g = call["modes"]["greenwave"]
    mm = lambda s: f"{s // 60}:{s % 60:02d}"  # noqa: E731
    figs = ((f"{mm(S['none']['response_mean_s'])} → {mm(S['greenwave']['response_mean_s'])}", "to the call, mean"), (f"{S['greenwave']['reds']}", "reds met on a green wave"),
            (str(S["greenwave"]["preemptions"]), "signals turned"))
    arch = "Signal preemption: each signal within 300 m of the ambulance turns green for it, keeping amber and all-red. " + NOMODEL
    return _pair(
        "junctions-ambulance", "Junction planner · ambulance green wave", "Rescue 1122 from the real station, through the evening peak, three ways.",
        arch, "10 calls in 30 minutes", "seed 7",
        f"{mm(S['none']['response_mean_s'])} / {mm(S['siren']['response_mean_s'])} / {mm(S['greenwave']['response_mean_s'])} to the call", "none / siren / green wave",
        (Stage("Call", "From the Rescue 1122 station on OpenStreetMap", "junctions.ambulance_calls()", "route"),
         Stage("Siren", "Cars pull over; it crosses a red slowly", "traffic_sim.TrafficSim._ahead_road()", "pull-over"),
         Stage("Green wave", "Signals within 300 m turn green ahead", "TrafficSim._preempt_requests()", "preemption"),
         Stage("Scene & hospital", "Ten minutes at the call, then the nearest emergency department", "junctions.ambulance_calls()", "stops"),
         Stage("Compare", "Response, reds met, everyone else's delay", "junctions.run_ambulance()", "table")),
        figs,
        (Layer("call", "Rescue 1122", "station, call, hospital"), Layer("road", "Roads & traffic", "who is in the way"),
         Layer("sig", "Signals", "preempted ahead"), Layer("out", "Planner", "route and diagram")),
        (C("st", "Station", "call", "junctions.station()", 0), C("hosp", "Hospital", "call", "junctions.ambulance_calls()", 2),
         C("amb", "Ambulance", "road", "traffic_sim.TrafficSim.step()", 1), C("pre", "Preemption", "sig", "TrafficSim._preempt_requests()", 0),
         C("head", "Signal heads", "sig", "TrafficSim.tick_signals()", 2), C("ui", "Time-distance", "out", "viewer/junctions.js drawTD()", 1)),
        (Hop("st", "amb", j({"dispatched": clock(J["meta"]["start"] + call["t0"]), "route_m": call["length"], "signals": [s[3] for s in call["signals"]]}), "A call: dispatched from the station.", "call"),
         Hop("amb", "pre", j({"next_signal": call["signals"][0][3], "at_m": call["signals"][0][0], "phase": call["signals"][0][2]}), "300 m from the next signal, the ambulance asks for its phase.", "request"),
         Hop("pre", "head", j({"green_for_it": g["greens"][0][:3]}), "The signal ends the other green (after 5 s), runs amber and all-red, and shows green for it.", "green intervals"),
         Hop("amb", "hosp", j({"trace_t_m": g["trace"][:6], "response_s": g["response_s"], "to_hospital_s": g["to_hospital_s"]}), "Its distance against time, every 4 s.", "trace"),
         Hop("hosp", "ui", j({w: call["modes"][w]["response_s"] for w in ("none", "siren", "greenwave")}), "The same call three ways, on the time-distance diagram.", "response, s")),
        "ten Rescue 1122 calls in the evening peak", "response and hospital times, reds met, three ways",
        "viewer/junctions_replay.js (seed 7)", "One real call: dispatched, preempted signal by signal, to the hospital.")


# ------------------------------------------------------------------ city systems
def _cy():
    return load("city_replay.js")


def city_smog():
    from isometric import _cell
    Cy = _cy()
    S = Cy["smog"]
    m, G = S["metrics"], S["grid"]
    fi = len(S["frames"]) - 1
    k = max(range(len(S["sensors"])), key=lambda i: S["readings"][fi][i])
    sen = S["sensors"][k]
    truth_there = S["truth"][fi][_cell(G, sen["x"], sen["y"])]
    t = clock(Cy["meta"]["smog_start"] + S["frames"][fi] * 60)
    figs = ((f"{m['map_error_today']:.0f} → {m['map_error_sensors']:.0f}", "map error near roads, µg/m³"), (f"{m['hotspot_found_m']} m", "hotspot placed off"),
            (f"{m['true_hotspot_before']:.0f} → {m['true_hotspot_after']:.0f}", "PM2.5 at the real hotspot"))
    arch = "Gaussian dispersion of the traffic's own emissions on a 100 m grid; a land-use regression of 25 sensors on loop-detector counts, residuals by inverse distance. " + NOMODEL
    return _pair(
        "city-smog", "City systems · smog sensors", "A November evening: one official monitor against 25 low-cost sensors, and what the city does with the map.",
        arch, "a November evening, 17:30-18:30", f"{S['trips']:,} trips, seed 7",
        f"map error {m['map_error_today']} → {m['map_error_sensors']} µg/m³; hotspot {m['true_hotspot_before']} → {m['true_hotspot_after']}", "one monitor → 25 sensors + action",
        (Stage("Emit", "Exhaust per km and idling per minute, per road", "city.Emissions", "g/min"),
         Stage("Spread", "Gaussian, 250 m, on a 100 m grid over the inversion's haze", "city.Grid.spread() / background()", "truth"),
         Stage("Read", "Each sensor with its own gain error and noise", "city.smog()", "readings"),
         Stage("Calibrate", "One network-wide correction from the sensor beside the monitor", "city.smog()", "calibrated"),
         Stage("Map", "Regress readings on loop-detector counts; interpolate the residuals", "city.smog() / idw()", "the city's map"),
         Stage("Act", "Signals within 400 m of the hotspot go adaptive; re-run", "city.smog(adaptive_near)", "less idling")),
        figs,
        (Layer("src", "Traffic", "the source"), Layer("air", "Air", "what is really there"),
         Layer("net", "Sensor network", "what the city can see"), Layer("act", "Action", "signals at the hotspot")),
        (C("em", "Emissions", "src", "city.Emissions", 0), C("loop", "Loop detectors", "src", "Emissions.counts", 2),
         C("grid", "Dispersion grid", "air", "city.Grid.spread()", 1),
         C("sen", "Low-cost sensor", "net", "city.sensor_sites()", 0), C("lur", "Land-use regression", "net", "city.smog()", 2),
         C("sig", "Adaptive signals", "act", "Signal.adaptive", 1)),
        (Hop("em", "grid", j({"trips": S["trips"], "per_road_per_minute": "g of PM2.5: km driven x factor + seconds idling x factor"}), "Every vehicle of the traffic module, by kind.", "emissions"),
         Hop("grid", "sen", j({"at": t, "sensor": sen["name"], "kind": sen["kind"], "truth_ugm3": truth_there}), "The air at the sensor's cell, as it really is.", "truth"),
         Hop("sen", "lur", j({"at": t, "sensor": sen["name"], "gain": sen["gain"], "reading_ugm3": S["readings"][fi][k]}), "What the sensor reports after the network-wide correction.", "reading"),
         Hop("loop", "lur", j({"counts": "vehicle-seconds on signal approaches only", "why": "a proxy for traffic, not a copy of the truth"}), "The signals' loop detectors give the regression its shape.", "counts"),
         Hop("lur", "sig", j({"map_error": [m["map_error_today"], m["map_error_sensors"]], "hotspot_found_m": m["hotspot_found_m"], "adaptive_signals": m["adaptive_signals"]}), "The worst quarter-hour cell on the sensors' map; nearby signals go adaptive.", "hotspot"),
         Hop("sig", "grid", j({"where_it_acted": [m["hotspot_before"], m["hotspot_after"]], "real_hotspot": [m["true_hotspot_before"], m["true_hotspot_after"]]}), "The same trips again, with less idling at the hotspot.", "µg/m³")),
        "an evening's traffic and the regional haze", "the air map, its error, the hotspot and the action's effect",
        "viewer/city_replay.js (seed 7)", f"One real reading: {sen['name']} at {t}, against the truth in its cell.")


def city_rain():
    Cy = _cy()
    F = Cy["flood"]
    a, b = F["modes"]["today"], F["modes"]["connected"]
    # the underpass with the most drivers stalled Today among those Connected closed, so both stories are told
    u = max((x for x in F["underpasses"] if b["closed_min"][x["name"]]), key=lambda x: a["stranded_at"][x["name"]])["name"]
    t0 = Cy["meta"]["flood_start"]
    first_stall = next(t for t, n in a["stranded_events"] if n == u)
    shut = b["closed"][u][0][0] if b["closed"][u] else None
    figs = ((f"{a['stranded']} → {b['stranded']}", "vehicles stalled"), (f"{max(a['max_depth'].values())} → {max(b['max_depth'].values())} m", "deepest water"),
            (f"{a['completed']:,} → {b['completed']:,}", "trips finished"))
    arch = "A water balance per real underpass (rain on the dip and its catchment in, pumps out while there is power), stall depths per vehicle kind, gates that reroute the traffic. " + NOMODEL
    return _pair(
        "city-rain", "City systems · underpass flood alarms", "A monsoon storm with a power cut: the water finds the drivers, or the gate closes first.",
        arch, "a 60 mm/h storm, 18:00-19:15", f"power cut {clock(t0 + F['power_cut'][0])}-{clock(t0 + F['power_cut'][1])}, seed 7",
        f"{a['stranded']} → {b['stranded']} stalled; {b['rerouted']} rerouted; {a['completed']:,} → {b['completed']:,} trips", "Today → Connected",
        (Stage("Find", "Tunnel pieces on OpenStreetMap grouped into underpasses", "city.underpasses()", "7 basins"),
         Stage("Fill", "Rain on the dip and 2 ha of streets draining in", "city.rain_mmh() / depth_series()", "depth"),
         Stage("Pump", "0.25 m³/s until LESCO's feeder trips; then the generator", "city.depth_series()", "outflow"),
         Stage("Stall", "Motorcycles at 0.30 m, cars at 0.45 m", "city.flood()", "stranded"),
         Stage("Gate", "Close at 0.15 m, reopen at 0.05 m, reroute traffic", "city.flood() / Movements.closed", "detours")),
        figs,
        (Layer("sky", "Storm & grid", "rain and power"), Layer("pit", "Underpass", "the basin and its pumps"),
         Layer("iot", "Level sensor", "gate and generator"), Layer("road", "Traffic", "who drives in")),
        (C("rain", "Rain", "sky", "city.rain_mmh()", 0), C("feed", "LESCO feeder", "sky", "city.POWER_CUT", 2),
         C("sump", "Basin + pumps", "pit", "city.depth_series()", 1),
         C("lvl", "Level sensor", "iot", "city.flood()", 0), C("gate", "Gate + generator", "iot", "city.flood()", 2),
         C("cars", "Vehicles", "road", "traffic_sim.TrafficSim", 1)),
        (Hop("rain", "sump", j({"peak_mm_h": max(F["rain"]), "catchment_m2": F["underpasses"][0]["catchment_m2"]}), "Rain on the dip and the streets that drain into it.", "inflow"),
         Hop("feed", "sump", j({"power_cut": [clock(t0 + F["power_cut"][0]), clock(t0 + F["power_cut"][1])], "generator_after_s": F["generator"]}), "The pumps stop when the feeder trips; Today's generator starts 30 min late, Connected's in 2.", "power"),
         Hop("sump", "cars", j({"underpass": u, "first_stall": clock(t0 + first_stall), "stalled_here": a["stranded_at"][u], "max_depth_m": a["max_depth"][u]}), "Today: drivers find the water.", "stalled"),
         Hop("sump", "lvl", j({"underpass": u, "close_at_m": 0.15, "max_depth_m": b["max_depth"][u]}), "Connected: the level sensor watches the same basin.", "level"),
         Hop("lvl", "gate", j({"underpass": u, "closed_at": clock(t0 + shut) if shut is not None else None, "closed_min": b["closed_min"][u]}), "The gate closes before the water is deep enough to stall anyone.", "gate"),
         Hop("gate", "cars", j({"rerouted": b["rerouted"], "stranded": b["stranded"], "delay_median_s": [a["delay_median_s"], b["delay_median_s"]]}), "Traffic heading in is sent over the surface road.", "detour")),
        "a storm, a power cut and the evening's traffic", "depth per underpass, vehicles stalled, trips finished",
        "viewer/city_replay.js (seed 7)", f"One real underpass, {u}, through the storm both ways.")


def city_night():
    Cy = _cy()
    Lt = Cy["lights"]
    a, b = Lt["modes"]["today"], Lt["modes"]["connected"]
    t0 = Cy["meta"]["night_start"]
    road = max(range(len(b["changes"])), key=lambda i: len(b["changes"][i] or []))
    ch = b["changes"][road][:6]
    fail = Lt["fails"][0]
    figs = ((f"{a['kwh']:,.0f} → {b['kwh']:,.0f}", "kWh in a night"), (f"{a['busy_road_minutes_dark']:,} → {b['busy_road_minutes_dark']:,}", "busy road-minutes dark"),
            (f"{a['failures_known_by_morning']} → {b['failures_known_by_morning']}", "failed lamps known"))
    arch = "Lamp-by-lamp levels from the traffic simulation's occupancy each minute, a battery for main roads through load-shedding, failure reports. " + NOMODEL
    return _pair(
        "city-night", "City systems · adaptive streetlights", "A night of load-shedding: every lamp full all night, or dimmed until traffic comes.",
        arch, f"{Lt['lamp_count']:,} lamps, 23:00-05:00", f"{Lt['trips']:,} night trips, seed 7",
        f"{a['kwh']:,.0f} → {b['kwh']:,.0f} kWh; dark busy road-minutes {a['busy_road_minutes_dark']:,} → {b['busy_road_minutes_dark']:,}", "Today → Connected",
        (Stage("Lamps", "Every road from residential up, 35-40 m apart", "city.streetlights()", f"{Lt['lamp_count']:,} lamps"),
         Stage("Traffic", "Which road pieces have a vehicle, each minute", "TrafficSim (night run)", "occupancy"),
         Stage("Dim", "30% unless traffic is on it or next to it", "city.streetlights()", "levels"),
         Stage("Shed", "01:00-02:00 the east feeder goes; main roads on a battery", "city.OUTAGE", "kept lit"),
         Stage("Report", "A failed lamp reports itself at once", "city.FAIL_RATE", "repairs")),
        figs,
        (Layer("road", "Traffic", "the night's vehicles"), Layer("ctl", "Controller", "per road piece"),
         Layer("lamp", "Lamps & feeder", "power drawn")),
        (C("occ", "Occupancy", "road", "streetlights() watched()", 0), C("veh", "Vehicles", "road", "TrafficSim", 2),
         C("dim", "Dimming", "ctl", "city.streetlights()", 0), C("bat", "Battery (main roads)", "ctl", "city.streetlights()", 2),
         C("lamp", "LED lamps", "lamp", "city.streetlights()", 0), C("feed", "Feeder", "lamp", "city.OUTAGE", 2)),
        (Hop("veh", "occ", j({"night_trips": Lt["trips"], "sampled": "every 10 s, the road piece under each vehicle"}), "Which roads are in use, minute by minute.", "occupancy"),
         Hop("occ", "dim", j({"road_piece": road, "level_changes": [[clock(t0 + mi * 60), lv] for mi, lv in ch]}), "This road piece's level as traffic comes and goes.", "levels"),
         Hop("feed", "bat", j({"outage": [clock(t0 + Lt["outage"][0]), clock(t0 + Lt["outage"][1])], "east_half": "dark Today"}), "Load-shedding on the eastern feeder.", "outage"),
         Hop("bat", "lamp", j({"main_roads": "lit on the battery", "busy_road_minutes_dark": [a["busy_road_minutes_dark"], b["busy_road_minutes_dark"]]}), "Main roads stay lit through the cut.", "kept lit"),
         Hop("lamp", "dim", j({"failed_lamp": {"road_piece": fail[0], "at": clock(t0 + fail[1] * 60)}, "known_by_morning": [a["failures_known_by_morning"], b["failures_known_by_morning"]]}), "A failed lamp reports itself; Today it waits for a complaint.", "failure"),
         Hop("dim", "feed", j({"kwh": [a["kwh"], b["kwh"]], "full_night_kwh": Lt["night_full_kwh"]}), "Power drawn over the night, Today against Connected.", "kWh")),
        "a night's traffic and a load-shedding hour", "kWh, roads left dark, failures found",
        "viewer/city_replay.js (seed 7)", "One real road piece dimming and brightening with its traffic.")


TOOLS = {"office-lights": office_lights, "office-attendance": office_attendance, "home-gridsense": home_gridsense,
         "home-people": home_people, "hospital-ed": hospital_ed, "hospital-alarms": hospital_alarms,
         "hospital-equipment": hospital_equipment, "hospital-families": hospital_families, "traffic-trips": traffic_trips,
         "traffic-signals": traffic_signals, "traffic-map": traffic_map, "junctions-fixes": junctions_fixes,
         "junctions-ambulance": junctions_ambulance, "city-smog": city_smog, "city-rain": city_rain, "city-night": city_night}
