/* What each module is, what it does, what you can put in and what comes out.
 * Shown by the shell's About panel and by each module's About button. */
"use strict";

window.TWIN_ABOUT = {
  office: {
    title: "Office tower",
    icon: "▦",
    page: "office.html",
    status: "ready",
    what: "A three-storey office in Lahore — basement car park, ground floor with reception and offices, first floor with a second office, boardroom and server room — run for a whole working day by simulated people and simulated IoT devices.",
    does: [
      "Moves about 50 people through their day: arriving by car or on foot, meetings, lunch queue, prayers, washroom and coffee breaks, going home. Some step out and come back: lunch at a dhaba, a client visit, the bank, the school pick-up; couriers and food riders drop off at reception.",
      "Badge readers and door counters on every secure door: attendance, late arrivals, tailgating alerts, missing badge-outs and an evacuation roll-call. Phones on the office Wi-Fi give the roll-call a second opinion.",
      "Lights and air-conditioning under three rule sets — a fixed timetable, motion sensors, and motion plus CO₂ — on the same people and the same day.",
      "Every automatic action carries its cause, so you can ask why a light came on and follow the chain back.",
    ],
    inputs: [
      ["Rule set", "Fixed schedule, Motion, or Motion + CO₂"],
      ["Seed", "a different day: other arrival times, meetings, visitors (1–999)"],
      ["Staff", "how many people have desks (10–36)"],
      ["Visitors", "guests booked into meetings (0–8)"],
    ],
    outputs: [
      "The floor plan, floor by floor, with people, lights, AC, cars in the basement",
      "Energy used by lights and AC under each rule set, and how much each saves",
      "Comfort: minutes in the dark, too warm, stuffy rooms",
      "Attendance register, tailgates caught, roll-call accuracy",
      "An event log with the reason behind every action",
    ],
    analysis: "Motion sensors cut lighting and AC energy by about 30% against a fixed timetable; adding CO₂ keeps that saving while switching far fewer lights off on people who sit still. The badge register is a better roll-call than door counters, but people going in and out all day — and tapping out of one floor, then walking in behind a colleague at the other — leave it about 2 people off on average. Adding phones on the Wi-Fi brings that down to about 0.3.",
  },
  home: {
    title: "Home + GridSense",
    icon: "⌂",
    page: "home.html",
    status: "ready",
    what: "A double-storey Lahore house with 6 kWp of solar on the roof, a 10 kWh battery and a hybrid inverter, living through a day of load-shedding — and GridSense, an energy manager that plans around the published outage schedule.",
    does: [
      "Simulates a family of six and a helper through an ordinary Lahore day: the school van at 07:20, father at the office, the university student, the market and pharmacy, evening tuition, groceries, prayers, cooking, sleep, laundry, the roof tank and the water pump.",
      "Visitors come and go: neighbours in the morning, relatives in the evening, Nana and Nani some afternoons. A beam counter on the gate counts every crossing, and the drawing room's fan and lights follow the guests.",
      "Models the solar panels, battery, inverter limits, low voltage and the published plus unannounced power cuts.",
      "Compares four ways of running the house on the same day: the inverter's default, a UPS-only circuit, GridSense eco and GridSense.",
      "GridSense keeps a battery reserve sized for the next outage, pre-cools rooms before a cut, runs the pump and washer on spare sun, and protects compressors on low voltage.",
    ],
    inputs: [
      ["Controller", "Inverter default, UPS circuit, GridSense eco, GridSense"],
      ["Season", "June (hot) or October (mild)"],
      ["Feeder category", "how many hours of load-shedding the area gets (I, III, IV, V)"],
      ["Solar and battery size", "kWp of panels, kWh of battery"],
      ["Seed", "a different day: other routines, weather and unannounced cuts"],
    ],
    outputs: [
      "Each floor and the roof with people, fans, ACs, lights, the tank and the panels",
      "Who is home: how many are in, who is out and why, which visitors are due, the day's head count and the gate counter's log",
      "A live power-flow card: solar, battery, grid and house",
      "Minutes the house was dark, minutes too hot to sleep or awake, the day's bill",
      "Every decision the controller took and why",
    ],
    analysis: "GridSense never lets the house go dark while the plain inverter default does in the evening outages; GridSense eco costs the same as the default; the comfort setting keeps people cooler at night for a higher bill. October days often end with a negative bill from exported solar.",
  },
  hospital: {
    title: "Hospital",
    icon: "✚",
    page: "hospital.html",
    status: "ready",
    what: "The Lahore General Hospital campus from OpenStreetMap, with the Emergency Department (and its basement) and a 36-bed medical ward on the second floor of the main block simulated room by room.",
    does: [
      "About 160 emergency arrivals in a day: registration, five-colour triage, doctors, blood tests, X-ray, drips, admission or discharge, and people who leave without being seen.",
      "A medical ward with call buttons, a high-dependency unit whose monitors raise alarms (most of them false), medicine fridges and bed cleaning.",
      "Doctors, nurses, porters, cleaners and clerks working three shifts from a shared task board.",
      "Families, as in a Pakistani government hospital: 1–3 relatives come with every emergency patient and stay at the bedside, one stays the night on the ward and goes down to the pharmacy for the medicines, and visitors come through the day.",
      "Two ways of running it on the same patients: Today (alarms for everyone, searching for equipment, phone calls about beds, relatives everywhere) and Connected (badges, routed alarms with a short delay, an equipment locator, a live bed board, fridge probes, one attendant card per patient and a visitor pass desk).",
    ],
    inputs: [
      ["Rule set", "Today or Connected"],
      ["Seed", "a different day of patients and events"],
      ["Arrivals", "how busy the emergency department is (50–200%)"],
      ["Ward nurses", "nurses per day shift on the ward"],
      ["Alarm delay", "seconds a non-critical alarm waits before it sounds"],
    ],
    outputs: [
      "Site, emergency department (two floors) and main block (two floors) with people, beds, equipment, call lights and alarms",
      "An emergency board, a bed board, an equipment list and an event log with causes",
      "Waits to triage and to a doctor, length of stay, patients who left unseen",
      "Call-button and alarm response, false-alarm walks, minutes spent searching for equipment, fridge minutes above 8 °C, bed turnaround",
    ],
    analysis: "Badges and sensors do not add doctors, so emergency waits barely change. They end the equipment hunt, keep infusion pumps in the department, cut the alarms nurses walk to by about 60% (at the price of brief real events that never sound, counted), shorten bed turnaround and catch an open fridge in minutes. A one-hour hand-hygiene audit reports about twice the true rate; counting dispensers reports it as it is. One attendant card per patient halves the relatives standing in the emergency bays, and the visitor pass desk all but ends visiting outside 16:00–18:00, at the price of a crowded ward at four and families turned away after six.",
  },
  traffic: {
    title: "Lahore traffic",
    icon: "⇄",
    page: "traffic.html",
    status: "ready",
    what: "An evening or morning peak on real Lahore roads from OpenStreetMap — Gulberg, Kalma Chowk, Garden Town and the Canal Road — with motorcycles, cars, rickshaws and wagons, flyovers, underpasses, small streets, one-way and two-way roads, 59 traffic signals, and the 432 real shops, restaurants, banks, schools, hospitals, fuel stations and mosques people stop at.",
    does: [
      "Builds the road network from the real map: every road class from the Canal Road to living streets, lane counts, one-way streets, flyovers above and underpasses below.",
      "Drives about 7,000 trips through a peak hour: each vehicle follows the one ahead, changes lane when another is better, gives way to the bigger road, stops at red and queues back through junctions. Vehicles keep left, as in Pakistan.",
      "Trips have reasons. Evening: home from work, shopping, the mall, takeaway, dinner out, the pharmacy, the bank, fuel, prayers, tuition pick-ups. Morning: the office, the school run, university, breakfast, fuel. Short stops block the kerb lane, long ones pull off to park, and rickshaws and wagons stop for passengers anywhere.",
      "Signals stand where two named through roads cross at grade, as in Lahore: the main road 60 s green, the side road 30 s, 3 s amber, 2 s all-red, each junction at its own point in the cycle, so a light can turn red just as you reach it.",
      "Runs the same hour twice: those fixed-time signals, and adaptive signals that hold green while loop detectors still see traffic.",
      "Ranks the worst junctions by time vehicles spend stopped there — the list the junction planner starts from.",
    ],
    inputs: [
      ["Signal rule set", "Fixed signals or Adaptive signals"],
      ["Peak", "evening (17:30, shops open) or morning (07:30, the school run)"],
      ["Demand", "trips per hour entering and moving in the area (2,000–12,000)"],
      ["Seed", "a different day: other trips, stops and timings"],
    ],
    outputs: [
      "A streaming map that loads around the camera like a game map; drag to pan, scroll to zoom",
      "Follow a vehicle: the camera rides along, with why it is driving, its stops and their times, its route, speed and arrival; a minimap shows where it is",
      "Shops and amenities on the map; the busiest places this hour and who is parked at each",
      "Signals changing on every approach with countdown timers, a junction inspector with its phase log",
      "Travel time, delay (not counting time at the shop), stops per trip, mean speed, stops made and the hotspot list, side by side for both rule sets, and why people drove",
      "Keys: Space play/pause, ← → a minute, Shift + arrows pan, + − zoom, f follow a vehicle, Esc stop following; Tab reaches every control and hotspot",
    ],
    analysis: "On an evening of 8,000 trips an hour, adaptive signals cut the time vehicles spend stopped at signals by about three-quarters (90 to 21 vehicle-hours) and median delay from 105 to 60 seconds on the same trips. Firozpur Road / Wahdat Road is the worst junction by far. Signals here are placed at crossings of named through roads because OpenStreetMap maps only two in the area; trip purposes and stop times are assumptions.",
  },
  junctions: {
    title: "Junction planner",
    icon: "✣",
    page: "junctions.html",
    status: "ready",
    what: "Takes the evening's worst junctions on Lahore's real roads and tries the fixes the city actually uses — retiming, an adaptive signal, a U-turn conversion, an underpass — on exactly the same trips; and sends Rescue 1122 ambulances through the peak with no priority, a siren, or a green wave.",
    does: [
      "Ranks the junctions by time lost in the traffic module's evening peak and picks the worst three.",
      "Retime: Webster's method on the demand each approach really carries. Adaptive: loop detectors at that junction only.",
      "U-turn conversion: the crossing closes; through and right-turning traffic turns left and U-turns at a gap in the main road 150–400 m away (through the median on a divided road), and is rerouted with the turn bans.",
      "Underpass: the main road's straight-on traffic passes under the crossing; what is left keeps a retimed surface signal.",
      "Ambulance: ten calls from the real Rescue 1122 station in OpenStreetMap, ten minutes at the call, then to the nearest hospital with an emergency department. Siren: cars pull over where they can and it crosses a red slowly. Green wave: each signal turns green for it about 25 s ahead.",
    ],
    inputs: [
      ["Demand", "trips per hour in the peak (2,000–12,000)"],
      ["Seed", "a different evening: other trips, other calls"],
      ["Junction to plan", "the evening's worst (default), or any of the 59 signalised junctions"],
      ["Fix, call and way", "pick on the page; every one is already simulated"],
    ],
    outputs: [
      "A close map of each junction from the real roads, the fix drawn on it",
      "Vehicle-hours lost at the junction, queue peak, network delay, extra kilometres and what pedestrians lose, for every fix",
      "The ambulance on its route, signals on the way, time to the call and to hospital, and a time–distance (green-wave) diagram",
    ],
    analysis: "At the worst junction, Firozpur Road / Wahdat Road, every fix roughly thirds the time lost, and the U-turn conversion does best at the junction but adds hundreds of kilometres of driving and takes the crossing from pedestrians. Retiming alone hands the long green to Wahdat Road, because Firozpur's through traffic is on the flyover above. A green wave gets ambulances to their calls about 11% sooner than no priority (4:27 → 3:58), a little under the 14–23% field studies report: these calls are short, with one to four signals each.",
  },
  city: {
    title: "City systems",
    icon: "☁",
    page: "city.html",
    status: "ready",
    what: "Three city-wide IoT systems on Lahore's real roads, driven by the traffic module: a smog sensor network on a November evening, underpasses flooding in a monsoon storm with a power cut, and streetlights through a night of load-shedding.",
    does: [
      "Smog: PM2.5 at street level every minute from the regional haze under a closing inversion plus what the traffic module's vehicles emit, exhaust and idling. One official monitor against 25 low-cost sensors at schools, hospitals and junction poles, mapped with the signals' loop-detector counts; the hotspot they find gets adaptive signals.",
      "Rain: each real underpass a basin filling from the streets around it, pumped until LESCO's feeder trips. Today the water finds the drivers; Connected's level sensors start the generator, close the gate at 0.15 m and route traffic over the surface.",
      "Night: about 9,500 LED streetlights. Connected dims each road to 30% unless traffic is on or next to it, keeps main roads lit on a battery through load-shedding, and every lamp reports its own failure.",
    ],
    inputs: [
      ["Demand", "trips per hour in the evening (2,000–12,000); the storm and the night scale from it"],
      ["Seed", "a different evening: other trips, sensors' errors, failures"],
      ["View and rule set", "Smog, Rain or Night; Today or Connected; what the city sees or the truth"],
    ],
    outputs: [
      "A PM2.5 map in the US AQI bands with every sensor's reading; the hotspot the network finds",
      "Underpass gauges, gates, stalled vehicles, depth and rain charts with the power cut",
      "Every road's light level minute by minute, the shed feeder, failed lamps, power drawn",
      "Today against Connected for each: map error, water depth, vehicles stalled, kWh, roads left dark",
    ],
    analysis: "Twenty-five low-cost sensors with the signals' traffic counts halve the error of the city's air map and find the hotspot within about 150 m; adaptive signals there cut its PM2.5 by 8–14%. In the storm the water reaches about half a metre and strands drivers Today; Connected closes the gates first, nobody stalls, and more trips get home at a few seconds' detour. Adaptive streetlights use about 38% less energy and keep main roads lit through the cut. Background, storm, pumps and lamp figures are assumptions, labelled on each view.",
  },
};

function twinAboutHtml(key) {
  const a = window.TWIN_ABOUT[key];
  if (!a) return "";
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  let h = `<h2>${esc(a.title)}</h2><p>${esc(a.what)}</p>`;
  if (a.does.length) h += `<h3>What it does</h3><ul>${a.does.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  if (a.inputs.length) h += `<h3>What you can put in</h3><table>${a.inputs.map(([k, v]) => `<tr><td><b>${esc(k)}</b></td><td>${esc(v)}</td></tr>`).join("")}</table>`;
  if (a.outputs.length) h += `<h3>What comes out</h3><ul>${a.outputs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  if (a.analysis) h += `<h3>What it shows</h3><p>${esc(a.analysis)}</p>`;
  h += `<p class="muted" style="font-size:12px">Everything here is simulated: no real people, patients or devices. Every device sits behind an MQTT-style topic, so a real sensor can take its place.</p>`;
  return h;
}
