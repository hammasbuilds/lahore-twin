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
      "Moves 46 people through their day: arriving by car or on foot, meetings, lunch queue, prayers, washroom and coffee breaks, going home.",
      "Badge readers and door counters on every secure door: attendance, late arrivals, tailgating alerts, missing badge-outs and an evacuation roll-call.",
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
    analysis: "Motion sensors cut lighting and AC energy by about 30% against a fixed timetable; adding CO₂ keeps that saving while switching far fewer lights off on people who sit still. The badge register is a better roll-call than door counters, and better still when tailgating alerts are added to it.",
  },
  home: {
    title: "Home + GridSense",
    icon: "⌂",
    page: "home.html",
    status: "ready",
    what: "A double-storey Lahore house with 6 kWp of solar on the roof, a 10 kWh battery and a hybrid inverter, living through a day of load-shedding — and GridSense, an energy manager that plans around the published outage schedule.",
    does: [
      "Simulates a family of six and a helper: school, work, cooking, prayers, sleep, laundry, the roof tank and the water pump.",
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
      "Two ways of running it on the same patients: Today (alarms for everyone, searching for equipment, phone calls about beds) and Connected (badges, routed alarms with a short delay, an equipment locator, a live bed board, fridge probes).",
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
    analysis: "Badges and sensors do not add doctors, so emergency waits barely change. They end the equipment hunt, keep infusion pumps in the department, cut the alarms nurses walk to by about 60% (at the price of brief real events that never sound, counted), shorten bed turnaround and catch an open fridge in minutes. A one-hour hand-hygiene audit reports about twice the true rate; counting dispensers reports it as it is.",
  },
  traffic: {
    title: "Lahore traffic",
    icon: "⇄",
    page: "traffic.html",
    status: "ready",
    what: "A morning peak on real Lahore roads from OpenStreetMap — Gulberg, Kalma Chowk, Garden Town and the Canal Road — with motorcycles, cars, rickshaws and buses, flyovers, underpasses, small streets, one-way and two-way roads, and smart traffic signals.",
    does: [
      "Builds the road network from the real map: every road class from the Canal Road to living streets, lane counts, one-way streets, flyovers above and underpasses below.",
      "Drives about 8,000 trips through an hour of morning peak: each vehicle follows the one ahead, changes lane when another is better, gives way to the bigger road, stops at red and queues back through junctions. Vehicles keep left, as in Pakistan.",
      "Runs the same morning twice: fixed-time signals, and adaptive signals that hold green while loop detectors still see traffic.",
      "Ranks the worst junctions by time vehicles spend stopped there — the list the junction planner starts from.",
    ],
    inputs: [
      ["Signal rule set", "Fixed signals or Adaptive signals"],
      ["Demand", "trips per hour entering and moving in the area (2,000–12,000)"],
      ["Seed", "a different morning: other trips and timings"],
    ],
    outputs: [
      "A streaming map that loads around the camera like a game map; drag to pan, scroll to zoom",
      "Follow a vehicle: the camera rides along, with its route, speed and arrival time; a minimap shows where it is",
      "Signals changing on every approach, a junction inspector with its phase log",
      "Travel time, delay, stops per trip, mean speed and the hotspot list, side by side for both rule sets",
    ],
    analysis: "Adaptive signals cut the time vehicles spend stopped at signals by about four-fifths and median delay by about two-thirds on the same trips; the same few junctions stay near the top under both — Allama Shabbir Usmani Road / Kiramat Road and the Main Boulevard Garden Town crossing. Signals here are placed at crossings of named main roads because OpenStreetMap maps only two in the area.",
  },
  junctions: {
    title: "Junction planner",
    icon: "✣",
    page: "junctions.html",
    status: "planned",
    what: "Finds the junctions where traffic jams build up and tests fixes — an underpass, a U-turn, a flyover, new signal timings — plus a green wave for ambulances.",
    does: ["Planned after the traffic module."],
    inputs: [],
    outputs: [],
    analysis: "",
  },
  city: {
    title: "City systems",
    icon: "☁",
    page: "city.html",
    status: "planned",
    what: "Smog sensors, underpass flooding alarms and smart streetlights across the city.",
    does: ["Planned after the junction planner."],
    inputs: [],
    outputs: [],
    analysis: "",
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
