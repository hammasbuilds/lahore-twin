# Lahore Twin — build plan and round log

One 2D world, six phases, built in this order. No phase starts before the one
above it has finished its build **and** ten review rounds.

| # | Phase | Status |
|---|---|---|
| 1 | Office tower — people, attendance, IoT, energy | building |
| 2 | Home + GridSense — load-shedding energy manager | — |
| 3 | Hospital — staff, patients, IoT, management panel | — |
| 4 | Lahore traffic — OpenStreetMap road network, smart signals, hotspot finder | — |
| 5 | Junction fix planner + ambulance green wave | — |
| 6 | City systems — smog, underpass flooding, streetlights | — |

## Process for every phase

1. Research (web, papers, vendor docs) — notes go in the phase section below.
2. Plan: features, simulation model, UI, design style, colour theme.
3. Build: engine + front end + `demo.py` + tests.
4. Ten review rounds. Each round: run the demo, drive the UI in a headless
   browser as a user would (screenshots read back), list issues and weaknesses,
   fix them, re-check, log the round here.
5. Commit locally. No push until the user asks.

## Ground rules

- Standard library Python only for the engine; the viewer is one offline HTML
  page with no CDN — the result must never depend on a network.
- Every device sits behind an MQTT-style topic (`office/<room>/<device>`), so a
  real ESP32 or Zigbee sensor replaces a simulated one without touching rules.
- Every actuator change carries its cause (the rule and the event that fired it).
- Comparisons are matched: same seed, same people, same day; only the rule set
  changes.
- Numbers from the simulator are labelled simulated. No real traffic, crowd or
  hospital data is copied; street geometry comes from OpenStreetMap.

---

## Phase 1 — Office tower

### Research notes

- **Motion sensors miss still people.** CMU's Intelligent Workplace study: PIR
  errs when occupants sit still, type or read, and cannot count people. A 2021
  *Energies* study of 18 multi-sensors found a ceiling PIR in the middle of a
  room ~60% accurate for presence vs 84% under the desk. Vendors report focused
  workers marked absent after a 15–30 min timeout. → model a low per-second
  detection probability for a still person, and measure "false-offs".
- **CO₂ is the complementary signal.** Occupants emit CO₂, heat and sound (CMU,
  10-week open-office study); PIR+other-sensor fusion reaches >99% room
  occupancy accuracy (Sensors & Materials 2015). → fuse a CO₂ trend with PIR.
- **Tailgating = head count vs credential reads.** Patents and vendors (IEE,
  Axis, ACTi) all compare a people counter at the door with badge reads; badges
  alone cannot see tailgating. Counters have false positives (lingering in the
  doorway). → beam counter + badge reader on the lobby gate; reconcile.
- **Occupancy control savings.** Schneider Electric, London meeting rooms:
  ~22% energy and carbon reduction, rooms resting 76% of business hours
  (vendor study, indicative). → report energy *and* comfort, never energy alone.
- **Occupant behaviour models.** LBL's agent-based Occupancy Simulator (Hong):
  arrival/departure from LIGHTSWITCH-2002 cumulative probabilities, Markov
  movement between spaces, a separate stochastic meeting model. arXiv 0706.1926:
  personal event schedules with times and probabilities. → per-person schedule
  of events with priorities, meetings from a generated calendar.
- **Dashboard design.** Operator dashboards: dark background, colour carries
  state (cyan / amber / green / red) so urgency reads before text; 2D plan with
  switchable overlays (occupancy, temperature, energy); biggest number first.

### Simulation model

- Plan: `plans/office.json` — 21 rooms, 23 doors, named spots (24 desks, 2
  cabins, meeting seats, queue, cafeteria seats, prayer, washrooms), 12 parking
  bays. A* on a 0.5 m grid through doors only.
- People (~40): staff, managers, receptionist, office boy, guard, cleaner,
  visitors. Each gets a day of events by priority: meetings > lunch > prayer >
  washroom > desk. Arrival ~N(09:00, 15 min) with a late tail; 60% drive.
- Behaviour that makes the system work for its living: tailgating at the badge
  gate, forgotten badges (manual check-in at reception), forgetting to badge
  out, meeting no-shows, people sitting still for long stretches.
- Devices per room: PIR (still-person detection ~1/300 s), CO₂ (mass balance,
  1 ACH, 60 s reports, ±15 ppm), temperature (first-order RC with Lahore
  October outdoor curve 20–33 °C), lights, AC (thermostat 24 °C, COP 3),
  power meter. Entrance: beam counter + badge reader. Parking bay sensors.
- Rule sets compared on the identical day:
  1. **schedule** — lights and AC on 08:30–18:30 everywhere (what most offices do)
  2. **pir** — lights/AC follow motion, 10 min hold, meeting pre-cool
  3. **pir+co2** — as 2, but a room is only declared empty when CO₂ is falling
     or near ambient
- Alerts: tailgate, late arrival, missing badge-out, meeting no-show released,
  cafeteria busy, CO₂ > 1000 ppm (ventilation boost), after-hours motion.

### UI

- One offline page: 2D plan on canvas, people as role-coloured dots, cars in
  bays, rooms tinted by state (light, AC, occupancy, temperature, CO₂ layers).
- Timeline 07:00–21:00, play/pause, speed, scrub. Click a room → its sensors and
  *why* each device is in its state. Click a person → their day.
- Side panels: live event log, attendance (system's view vs ground truth),
  energy (kW series for the three rule sets), alerts.
- Style: operator console. Dark by default with a light theme; neutral slate
  base, state colours: cyan = AC, amber = light, green = OK/occupied, red =
  alert, violet = people. Tabular numerals, biggest number first.

### Round log

_(rounds start after the build)_
