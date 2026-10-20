# Lahore Twin — build plan and round log

One 2D world, six phases, built in this order. No phase starts before the one
above it has finished its build **and** ten review rounds.

| # | Phase | Status |
|---|---|---|
| 1 | Office tower — people, attendance, IoT, energy | done: build + 10 review rounds |
| 2 | Home + GridSense — load-shedding energy manager | done: build + 10 review rounds |
| 3 | Hospital — staff, patients, IoT, management panel | review round 2 of 10 done |
| 4 | Lahore traffic — OpenStreetMap road network, smart signals, hotspot finder | review round 8 of 10 done |
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

**Build (718e3cf).** Engine, viewer, demo, 19 tests. Found during the build's own
checks: rules ticked every 5 s but compared booking times with `==`, so most
no-shows and pre-cools never fired; the PIR loop iterated a `set`, making the
same seed give different days in different processes; an old manual check-in
could claim another person's badge pass.

**Round 1 — the gate and comfort.**
- *Found:* the one real tailgate went uncaught (a genuine beam miss) and both
  alarms were the modelled doorway double count — one day holds too few events
  to judge a detector. *Fixed:* a quarter of staff now arrive in pairs (where
  real tailgating comes from); `demo.py --week` reports five days. A count in
  the same second as an explained one is now a "check the camera" door-count
  alert, not a tailgate. Five days: 9/9 tailgates caught, 0 false alarms, 1
  same-second double count flagged. Known blind spot, documented: a follower in
  the same second is indistinguishable from a double count.
- *Found (UI, attendance tab):* the receptionist was "on site, not in register"
  — her desk is in front of the badge line; she was registered at lunch. The
  guard was registered at his 10:00 patrol, not 07:00. *Fixed:* a badge reader
  on the staff-only reception door and a guard-post clock-in terminal; every
  badge door reconciles its own counter against its own reader.
- *Found:* occupancy control left people far warmer than the schedule (474 vs
  232 person-min). Measured where: the prayer room heat-soaks to 31 °C and a
  fixed 15-min pre-cool reached only 27 °C by Zuhr. *Fixed:* congregations are
  calendar bookings; pre-cool lead and optimum start come from the room's own
  temperature (330 s/°C). Too warm: 474 → 28 person-min, below the schedule's
  234, for ~1 kWh.
- *Found:* "checked in late at 09:15" — late was `> 09:15:00` but the clock
  shows minutes. *Fixed:* late from 09:16, with minutes late in the text.
- *Found:* UI check crashed once clicking a log row mid re-render. *Fixed:*
  locator-based click with a wait.
- Tests 19 → 24 (process-hash determinism, hot-room pre-cool lead, double count
  vs tailgate, per-door badge matching, receptionist/guard registered on arrival).
- *Open for round 2:* 38 false-offs/day remain under Motion + CO₂ (reception,
  store room, cabin 2); nobody reacts when a light goes off on them.

**Round 2 — lights going off on people, and a fair baseline.**
- *Found:* people left in the dark sat there for hours (116 person-min/day in
  CO₂ mode); the fixed schedule's 476 dark minutes were early arrivals waiting
  for 08:30 — a straw man. *Fixed:* everyone settled in a dark room waves within
  5–20 s, then presses the wall switch after 30 s; wall switches work under every
  rule set; on the schedule, hand-switched lights stay on until 18:30 and an
  hourly after-hours sweep turns them off. Schedule energy rose 171.8 → 182.6 kWh
  (lights switched on at 07:30 now burn all day — what really happens).
- *Added:* adaptive hold — motion within 60 s of a switch-off doubles that
  room's hold (max 4×), an uncontradicted switch-off halves it again. The
  trade-off, five days, Motion + CO₂:
  | hold rule | energy saved | switch-offs on someone/day |
  |---|---|---|
  | fixed 10 min | 14% (old baseline) | 43 |
  | grow only | 8.5% | 11 |
  | grow + relax (kept) | 16.0% (fair baseline) | 14 |
- *Found:* the wave delay drew from the same RNG as the door beam, so gate
  results changed with the rule set — the "identical in every rule set" claim
  was false. *Fixed:* a separate gate RNG; a test asserts gate metrics are equal
  across rule sets.
- *Found (UI):* the vertical reception door drew its reader marker using a y
  coordinate as x (mid-lobby); room names unreadable on data layers; the log
  said "CO₂ steady — keeping it on" then switched off a minute later (the CO₂
  verdict flipped on noise each tick); cafeteria queue counts flooded the log;
  gates were named after the corridor behind them. *Fixed:* per-axis reader
  placement; text colour on filled layers; a CO₂ verdict buys a fixed 5 min;
  queue telemetry is quiet unless it causes an alert; doors carry names ("Main
  badge gate", "Reception staff door").
- Export wrote CRLF on Windows; now bytes + LF. Tests 24 → 27.
- *Open for round 3:* the schedule leaves overtime staff warm after 18:30
  (251 person-min); evacuation headcount (door counter vs register) not shown;
  plan view leaves wide empty margins.

**Round 3 — evacuation roll-call.**
- *Added:* how many people are behind the badge doors right now, three ways:
  door counters (ins − outs), the badge register (last direction per person),
  and the truth.
- *Found:* raw door counters drift — every missed count accumulates, so by
  mid-morning they were 2 off (mean error 1.58 people, 08:30–18:30) while the
  register was 0.18 off. A first "counter vs register mismatch" alert fired
  three times a day on pure sensor drift. *Fixed:* the alert is gone; the
  estimate is register + entries nobody badged for (each tailgate alert adds
  one, a badge-out by someone who never badged in removes one), and counters
  that disagree with it for 15 min are re-zeroed. Seed 7: counters 0.41,
  register 0.18, estimate 0.10 people off on average; worst case 1.
- *Viewer:* attendance tab opens with the roll-call (estimate vs truth, register,
  counters, a day chart). The late threshold in the viewer still used the old
  09:15 rule — aligned to 09:16. Plan margins cut (top 56, bottom 58, sides 20):
  the floor plan is ~10% larger.
- The schedule's overtime heat (251 person-min after the 18:30 switch-off) is
  left as a measured weakness of that baseline, not patched — it is what a
  fixed schedule does.
- Tests 27 → 29.

**Round 4 — parts of the UI nobody had clicked.**
- *Found:* the person inspector had only ever been opened programmatically.
  *Fixed:* the UI check now clicks a person's dot with the mouse (positions
  exposed as `__twin.hits()`) and fails unless the inspector shows that name.
- *Found:* the power chart stayed a comb after 15-minute smoothing. Two causes:
  every room had identical thermal constants (started together, they cycled in
  step), and the open workspace's single on/off AC cycled with a period longer
  than the smoothing window. *Fixed:* per-room envelope and thermal mass
  (±25%, from crc32 of the room id — stable across processes); AC modelled as
  inverter units that modulate capacity across the 1 °C band, which is what
  Lahore offices mostly fit. The chart now shows the schedule tracking the
  afternoon heat, with occupancy control below it. Savings unchanged (15.8%).
- *Found (script):* the mode selector in the UI check was mis-escaped, so the
  evening screenshots silently stayed on the fixed schedule — a check that
  passed while testing the wrong thing. *Fixed:* quoted attribute selector.
- Evening review (19:45, schedule): after the 18:30 switch-off an overtime
  worker re-switched the workspace lights by hand at 19:00 and sat with the AC
  off — the schedule's documented weakness, visible in the replay.

**Round 5 — crowding, frame cost, contrast.**
- *Found:* up to 10 people drawn on one point. Shared spots were picked at
  random when the day was generated, so two people could share a prayer place
  or a stall; and 19 people attend Zuhr in a room with 10 places, so the
  overflow stacked. *Fixed:* stays name a pool and claim a free spot on arrival
  (released when they move on); the prayer room holds 4 rows of 7; coffee has
  its own spots beside the office boy's pantry. Stacked person-minutes per day:
  ~110 → ~16, all of them a person waiting for a busy stall, the queue tail, or
  the office boy at a desk serving tea. Test added (≤30, never in prayer rows).
- *Measured:* frame cost in Chromium with every panel forced to rebuild:
  4–16 ms (events log is the heaviest); playback refreshes panels at 4 Hz.
- *Found:* contrast computed from the live tokens (not eyeballed): light theme
  accent 3.68:1 and ok-green 3.77:1 on white, below 4.5:1 for the small labels
  and pills that use them. *Fixed:* #0e7490 / #047857 → 5.36:1 and 5.48:1. Dark
  theme already ≥ 5.6:1 everywhere. Tests 29 → 30.

**Round 6 — the hardware claim, made real.**
- *Found:* the README promised "replace Bus.publish with an MQTT client" but
  nothing in the repo spoke MQTT. *Added:* `mqtt.py`, a stdlib MQTT 3.1.1
  client (QoS 0) and a two-way bridge; `python -m lahore_twin.live` streams the
  office to a broker in real time or faster. Only sensor topics are accepted
  from outside; commands and alerts are produced by the rules alone.
- *Found while building it:* (1) the first bridge suppressed everything
  published while a device message was being injected — including the rules'
  light command, the very thing a relay waits for; now only the injected message
  is not echoed. (2) `Sim.run()` reset every position on each call, so running
  in two pieces teleported people; positions now start in the constructor and
  `run()` resumes. (3) keepalive pings were timed in simulated seconds — at 1×
  speed that is 10 real minutes, past the broker's 60 s keepalive; now wall time.
- Tests 30 → 34, against a fake broker that speaks the wire protocol (CONNECT,
  SUBSCRIBE, PUBLISH, PINGREQ): a pushed PIR message switches the light and the
  command reaches the broker; outside commands are refused; 3-byte remaining
  lengths round-trip; live mode streams only from `--start`. Not yet run against
  a physical board — stated in the README.

**Round 7 — a stale replay, keyboard users, a flaky check.**
- *Found:* `viewer/replay.js` is committed so the viewer opens without Python,
  and nothing noticed when it fell behind the code. *Fixed:* the replay carries
  a digest of `lahore_twin/*.py` + `plans/*.json` (CRLF-normalised); a test fails
  until `python demo.py` regenerates it. Verified to fail first, pass after.
- *Found:* rooms and people could only be selected by clicking the canvas — no
  way in for a keyboard user. *Added:* a "Find" picker (people by name and role,
  rooms) at the top of the inspector, kept in sync with canvas clicks; the UI
  check selects the prayer room with it and asserts the inspector follows.
- *Found:* the UI check had crashed twice, both times right after `demo.py`
  rewrote the 1.4 MB replay — the page loaded while the fresh file was still
  locked and the viewer never initialised; the crash printed only "Node.js
  v24". *Fixed:* it waits for the viewer to initialise, reloads up to 3 times,
  and prints the real error on failure.
- *Found (UI):* cause chains ended in a raw topic ("office/prayer/temp").
  *Fixed:* temperature and queue readings are described in words.
- Tests 34 → 35.

**Round 8 — twenty days, not one.**
- *Added:* `tools/sweep.py` checks invariants over 20 simulated days (every
  arrival leaves; nobody inside at 21:00; the register misses only tailgaters;
  Motion + CO₂ beats the schedule on energy and Motion on false-offs every day;
  gate results identical across rule sets). 0 violations. Energy 146–158 kWh vs
  the schedule's 179–184 on every day.
- *Found:* the roll-call figure in the README (0.10 people off) came from a
  lucky day: across 20 days it was 0.50, up to 1.04 on a bad day. Traced on
  seed 3: from 16:50 the register over-counted by up to 6 — people who forget to
  tap out on the way home stay "inside" on paper, exactly when an evening
  evacuation would need the number. *Fixed:* exits get the same reconciliation
  as entries: a counted exit with no badge-out lowers the estimate; tapping in
  while registered inside settles one; tapping out while not registered settles
  an unidentified entry (the guard's tailgated patrol had stayed +1 all day).
- *Found on the next measurement:* no improvement on average (0.49), one day
  worse (1.71). Traced on seed 20: the receptionist left her room untapped and
  tapped in at the main gate 4 s later — the settle arrived before the exit was
  reconciled and was dropped. *Fixed:* the settle may run the counter below
  zero briefly. Now 0.23 people off on average across 20 days, never more than
  1 at any moment (register 0.91, counters 0.58); the remaining error is
  tailgaters the beam merged with the person ahead.
- Tests 35 → 37; both new tests fail on the previous code.

**Round 9 — the README against fresh output.**
- *Found:* the README's output table was from round 1 (171.8 kWh; the fair
  wall-switch baseline and inverter AC came later); "caught all 9 tailgates" was
  now 5 of 7 (71%) — when the gate got its own RNG, beam merges started landing
  on real tailgaters, so the old line was a lucky draw; "33 people" was 34; the
  rules table still said a fixed 10-minute hold; devices said "AC with a
  thermostat". *Fixed:* output section rewritten from a fresh run, every claim
  re-measured; the 71% and its cause are stated.
- *Found:* a weakness the README never mentioned — 333 person-minutes a day
  above 1000 ppm CO₂ (full meeting rooms); the boost only began at 1000. Before
  fixing it, the model was missing the cost: outdoor air in a Lahore afternoon
  must be cooled, and ventilation carried no heat. *Fixed:* ventilation heat load
  (0.335 W per m³/h·K) for every room and rule set (AC energy +12 kWh, all three
  columns — the honest baseline); then demand-controlled ventilation from 800
  ppm. Stuffy 333 → 25 person-minutes for +3.4 kWh. Test: a boosted room draws
  more AC on a hot afternoon and holds lower CO₂.
- Every README command run: `demo.py`, `demo.py --week`, `pytest` (38),
  `tools/sweep.py`, `run.bat` (served and stopped in round 8); `live` is covered
  by the fake-broker test. Tests 37 → 38.

**Round 10 — an independent reviewer, cold (74/100), and every finding fixed.**
The reviewer reproduced every README number, the 20-day roll-call figures and
the tests, then found:
1. *High — MQTT echo:* the bridge subscribed to the topics it published; a real
   broker echoes a client's own publishes, so every simulated reading came back
   as a device reading (roll-call 44 vs a true 29). The fake broker never echoed,
   so the tests could not see it. *Fixed:* outbound `lahore-twin/state/...`,
   inbound `lahore-twin/device/...`; the fake broker now echoes like mosquitto;
   a test runs 2.5 h through an echoing broker and requires zero re-injections.
2. *End-of-day alerts at 21:00, timeline ending 20:59* — never visible.
   *Fixed:* the day is closed at 20:59:59 by `Sim.finish()`; UI check asserts
   the badge-out alerts appear at the end of the timeline.
3. *Comfort claim misattributed:* the schedule had wall switches for lights but
   no AC remote, so "252 vs 21" measured AC hours, not pre-cooling. *Fixed:* an
   AC remote for everyone (settled 5 min above 26.5 °C); the schedule's sweep
   clears it hourly. Schedule heat 252 → 128 person-min (overtime after 18:30),
   schedule energy 198.4 → 202.7 kWh; README rewritten with the real cause.
4. *No-show bookings had empty invitee lists*, so the viewer showed "0 people"
   hours early. *Fixed:* invitees kept; days skip the meeting; viewer shows
   "N invited" until the rule releases it.
5. *Keys:* ArrowRight in the Find picker also moved the clock; Space on a mode
   button started playback. *Fixed:* form controls keep their keys; UI check
   asserts both.
6. *Live mode closed the day twice* (alerts at 09:00 and 21:00). *Fixed* with
   (2); test: one set of badge-out alerts, stamped 20:59:59.
7. *Plan specifics hard-coded* (optimum-start rooms, reception check-in gate,
   patrol, cleaning order, furniture, short names, gate label). *Moved* into
   `plans/office.json` under `operations` / `furniture` / `short_names` /
   `labels`, validated on load; Attendance takes the manual gate explicitly.
   Demo numbers unchanged to the decimal — the move changed no behaviour.
8. *Roll-call average hid a split:* README now gives the median (0.01) and the
   5 bad days (~0.8, a merged tailgater each), and says seed 7 is one of them.
9. *A test name promised more than it checked* — renamed and documented.
10. *Sensors overstated:* CO₂/temperature exist in the 12 AC rooms only — said.
11. *Two energy figures* (headline summed minute samples, Compare used physics
    totals): both read the physics totals now.
12. *Readability:* light-theme chart lines told apart by dash, not colour;
    labels shortened or dropped when they do not fit (phone: no overlaps);
    reader labels hidden at small scale.
13. *Text:* roll-call note now includes the exit subtraction; prayer bookings
    named "Zuhr congregation 13:30"; dead 08:30/18:30 branch removed.
14. *Noisy test:* a 6-vs-8 dark-minute margin on one seed replaced by the
    false-off ratio (16 vs 28).
- Tests 38 → 44. Phase 1 closed.

---

## Phase 2 — Home + GridSense

### Research notes

- **Outages are per feeder and published.** LESCO's load-management plan puts
  2,282 feeders in loss-based categories: Category I up to 2 h/day (mostly late
  night), III 4 h, IV 5 h, V 6 h, VI 7 h; 210 feeders (9.3%) have none (The
  News). Reports in 2026 describe 3–6 h on high-loss feeders plus unscheduled
  cuts (Business Recorder, 24News). → a published schedule per feeder category
  *and* random unscheduled outages; the manager knows only the published part.
- **Peak tariff window.** K-Electric: Apr–Oct 18:30–22:30, Nov–Mar 18:00–22:00
  peak, the other 20 h off-peak; NEPRA says designated hours may change. Solar
  buyback for new consumers is being cut (Rs 10–11.3/unit proposed vs Rs 22 for
  existing contracts, gross metering proposed) → self-consumption is worth more
  than export.
- **Solar in Lahore.** NASA POWER via Profile Solar: ~6.3 kWh/day per kWp in
  summer, 4.8 autumn, 3.6 winter, 6.5 spring. → a clear-sky curve scaled to the
  season, with random cloud days.
- **Hybrid inverters.** Growatt-style priority modes: SBU (solar → battery →
  utility), "Load first" with a discharge-stop SOC; grid charging can be
  limited. Forum reports show these settings are static and get stuck. → the
  default inverter is a fixed SBU with a cutoff; GridSense changes the settings
  through the day.
- **Households.** Mirpur survey (523 dwellings): ~2,469 kWh/yr, family of 7,
  AC homes use 44% more. No measured Pakistani appliance table found → nameplate
  assumptions stated in the code (fan 80 W, inverter AC 1.5 t ~1.4 kW, fridge
  ~150 W cycling, water motor 0.75 kW, iron 1 kW, washing machine 0.5 kW).
- **Prior art.** Pretoria dissertation: scheduling + 9.6 kWh battery + 2.74 kWp
  removed loss of power and cut inconvenience 92% in 2023 load-shedding cases.
  Stellenbosch 2026 student HEMS: outage-preparation mode (shed non-essentials,
  charge the battery fast) from inverter data + weather + published schedule.
  IEEE Access 2018: heuristic scheduling of shiftable loads with PV and SOC.
  None models pre-cooling or the roof-tank pump — both are everyday Lahore needs.
- **Dashboard pattern.** Sunsynk/Enphase/Home Assistant power-flow cards: four
  nodes (solar, battery, grid, home) with animated flow direction; daily totals
  kept separate from live power; keep import and export on one grid node.

### Simulation model

- Plan: `plans/home.json` — a 10-marla Lahore house: car porch, drawing room,
  lounge, kitchen, three bedrooms with baths, store, inverter corner; roof with
  6 kWp of panels and a roof water tank fed from an underground tank.
- Family of 6 (world-mix names) plus a part-time helper; routines over 24 h:
  sleep, school/office, cooking, prayer, TV, laundry, ironing, showers.
- Devices: hybrid inverter (6 kW, SBU, cutoff SOC), 10 kWh LFP battery (90%
  usable), PV with season + clouds, grid with voltage swings (180–250 V),
  appliances with nameplate power, roof tank level (use from routines, pump
  fills), room temperature (reusing the office room physics).
- Outages: a published schedule (feeder category, e.g. 3 × 2 h) plus random
  unscheduled cuts; identical across rule sets.
- Rule sets on the identical day:
  1. **Inverter default** — fixed SBU; the family uses appliances whenever;
     the battery runs until cutoff, then the house goes dark.
  2. **UPS circuit** — the common Lahore wiring: only fans, lights, fridge and
     router are on the inverter; ACs and the pump are grid-only.
  3. **GridSense** — knows the published schedule and a solar forecast: keeps a
     battery reserve sized for the next outage's essential load, pre-cools
     bedrooms and fills the roof tank before an outage, moves laundry and
     ironing into solar hours, avoids grid import in the peak window, sheds by
     priority (AC → pump → iron/washer → … fans/lights/fridge/router last),
     cuts AC and fridge below 190 V. Every action carries its cause.
- Measures: essential-load blackout minutes, bedroom temperature through night
  outages, tank-empty minutes, grid kWh peak/off-peak and the bill (stated
  tariff assumptions), solar self-consumption, battery throughput, appliance
  protection events; summer (June) and October; several days.

### UI

- `viewer/home.html`, same design system as the office: 2D house plan with
  people and appliances, a power-flow card (solar / battery / grid / home,
  animated direction), a 24 h outage strip (published vs unscheduled), battery
  SOC and tank-level gauges, appliance list with state and "why", compare tab.
- Colours added to the office palette: solar amber, battery green, grid violet,
  outage red (hatched for unscheduled), water blue.
- Served by the same `run.bat` at http://127.0.0.1:8860/home.html; its own
  Launchpad entry.

### Round log

**Build (ef54897).** House plan, family routines, published + unannounced
outages, PV/battery/inverter/tank physics, three controllers, home viewer,
16 tests. Found in the build's own checks: the occupants' AC wish had no
hysteresis (switched off at 28 °C, rooms hovered there, battery barely used);
exported solar was counted as "used at home" (100% everywhere); telemetry was
logged every minute because the bus matches the last topic segment (`kw`,
`level`); the AC rationing in outages flapped every few seconds (the estimate
counted the running AC's own drain); GridSense tripped the inverter 0.8×/day
(pre-cooling three ACs plus the pump on a 6 kW unit). Each replay now has its
own source digest, so changing home code no longer marks the office stale.

**Round 1 — GridSense's bill.**
- *Found:* GridSense cost more than doing nothing (Rs 541 vs 487 a day over ten
  days). Decomposed: +2.4 kWh/day of load (ACs kept running in outages and
  pre-cooling where the default house goes dark) and +0.7 kWh at peak price,
  while still exporting 4.5 kWh/day at Rs 11 against Rs 42–50 imports.
- *Fixed (cost):* the reserve for an outage after 18:30 is bought before the
  peak window; before a night outage the afternoon sun is banked (loads run on
  off-peak grid, the battery arrives at 18:30 full).
- *Added (comfort):* a solar soak — with the battery full and sun about to be
  exported, occupied rooms are cooled to 25 °C with it.
- *Found:* the bill alone cannot separate "cheaper" from "delivers more", so
  GridSense got two profiles. **Eco** keeps the guarantees (never dark while the
  battery can carry essentials, compressor protection, inside the inverter
  rating) without comfort extras: Rs 446/day, 8% below both baselines, least
  peak import. **Comfort**: Rs 558, the coolest house (925 vs 1,770 person-min
  too hot awake).
- *Found:* a new flapping test (one AC changing state >3× in 10 min — the old
  test counted total changes, a proxy that broke as soon as GridSense did more)
  caught the soak flapping every minute. Two causes, traced tick by tick: rooms
  decided independently (three ACs started on one surplus, overdrew it, all
  stopped), and the house load is measured once a minute (six decisions on a
  number taken before the last change). *Fixed:* a shared surplus budget, one
  new room per fresh reading, each AC charged its real full draw (5.3 kW / COP
  3.2 = 1.65 kW — the appliance table's 1.45 kW was also low, which caused a
  remaining overload trip at 21:30 on one day).
- Tests 16 → 17 (eco is never dark and cheaper than the default over five days;
  the flapping test replaced). 0 overload trips over ten days for all four.

**Round 2 — seasons and feeder categories (30 days).**
- *Added:* `tools/sweep_home.py` — June and October × categories III, IV, V ×
  five days; invariants for both GridSense profiles: never darker than the
  default, no overload trips, no AC flapping, tank never dry, no late jobs.
  0 violations.
- *Found:* October exposed what June hid. Comfort GridSense cost Rs 40–64/day
  against the default's 7–17 with nobody too hot in any setup — it pre-cooled
  and soaked 24 °C rooms. Eco looked Rs 2–4 dearer than the default; traced on
  one day, every setup imported 0 kWh and the bill was only the battery's end
  change (~0.1 kWh apart: noise, not cost). Afternoon banking was also holding
  the battery from 14:00 even when it would reach 18:30 full anyway.
- *Fixed:* pre-cool only when the room is above 26 °C and the outage hours will
  be hot outdoors; soak only rooms above 28 °C; banking only when a projection
  (SOC + forecast sun − present load) says the reserve would not be there by
  18:30. October comfort Rs 48 → 36/day (category IV); June comfort unchanged.
- *Found (my own regression):* the new "warm" gate on pre-cooling had no
  hysteresis — the AC stopped once the room dropped below 26 °C and restarted
  as it warmed (5 changes in 9 minutes). The flapping test caught it. *Fixed:*
  a pre-cool in progress keeps going.

**Round 3 — using the viewer, and a bug that moved every number.**
- *Found (UI):* the AC glyph sat under the room-name label, so the red
  "wanted, no power" cross on the bedroom ACs — the whole point of the UPS
  circuit's night outage — was invisible. *Fixed:* bottom-right corner. The
  events log opened on every want/no-longer-want; it now opens on decisions
  and alerts (UI check asserts it). The home sidebar had one more block than the
  office's three-row grid, which stretched the tab bar into a large empty gap.
- *Found:* comfort GridSense pre-cooled both bedrooms at 09:20 for a 10:00
  outage because someone was in them at that moment; the rooms were empty during
  the outage. *Fixed:* pre-cool only rooms the household's usual routine uses
  during the outage (`operations.usual_occupancy` in the plan — what a real
  controller learns from weeks of presence data). My first table was wrong about
  the lounge (13:00 start; the mother and Dadi sit there from 07:30) and the
  numbers said so; corrected.
- *Found while explaining a surprise:* awake heat in the children's bedroom
  10:00–13:00, when the children are at school. Traced: everyone who went "Out"
  reached the street, and the off-site branch — written for someone arriving for
  the day, with arrival 00:00 — put them straight back at their bed, present and
  sweltering. Five phantom occupants all day: every earlier home number carried
  them. *Fixed* (out stays out until the next stay brings them back through the
  street); test added, fails on the old code. Corrected ten days: eco Rs 418 vs
  default 456 (8% less, never dark); comfort Rs 515, awake heat 542 vs 733
  person-min; README re-measured.
- Tests 62 → 63.

**Round 4 — when GridSense's assumptions fail (stress tests, 5 days each).**
House-dark minutes summed over five days (default / eco / comfort), before → after:
- forecast says clear, day is overcast: 318 / 8 / 13 → 318 / **0 / 0**
- 2 h unannounced cut ending 30 min before the night outage: 248 / 42 / 0 → 248 / **0 / 0**
- category V (6 h) and overcast: 252 / 5 / 0 → 252 / **0 / 0**
Four causes, each traced to the minute it went dark:
1. Outage AC rationing only asked whether the battery lasts *this* cut; during
   an unannounced cut it spent the reserve meant for the published outage half
   an hour later. *Fixed:* the next outage's reserve is subtracted when it starts
   before the battery could recharge.
2. The day-ahead forecast was trusted all day. *Fixed:* after two hours of
   daylight, observed/expected solar replaces it (`sky_factor`).
3. Spending the battery in the peak window went down to 20%; an unannounced cut
   at 21:38 then started at 13% and the house went dark. *Fixed:* a standing
   25% floor (~1.5 h of essentials) even at peak.
4. On a dull day an afternoon outage left the battery near cut-off for hours with
   the grid up — GridSense only grid-charged for a *published* outage within
   4 h. *Fixed:* insurance top-up to the floor whenever below it with the grid up
   (at peak only if very low). Also: an unannounced cut is now assumed to last
   1.5 h from its start (they run 20–90 min), not "one more hour" forever.
Bills moved by under 1%. Tests 63 → 65 (both stress cases, failing before).

**Round 5 — an independent reviewer, cold (62/100).** Its findings and what changed:
1. *High — solar accounting wrong both ways.* In an outage the inverter reported
   sun as used even when the battery took none (real curtailment on seed 7:
   8–14 kWh, reported 0); grid-only loads were netted against export, so solar
   feeding them showed as "wasted". *Fixed:* the inverter now splits solar once
   (`pv_load + pv_batt + pv_out + curtailed = pv`, tested), and the house computes
   the meter: grid-only loads are fed by solar pushed out before any export.
2. *High — one battery, two charge limits.* Sun and grid charging each took the
   full 5 kW (7 kW measured). *Fixed:* one shared allowance (tested).
3. *High — the 5 kW discharge limit below the 6 kW rating* blacked the house out
   as "battery at cut-off". *Fixed:* asking more than battery + sun can give is
   an overload trip with its own reason; GridSense's headroom is the inverter's
   real capacity minus a margin, not a fixed 5.5 kW.
4. *Day boundary:* every controller started at 00:00 on 60% nobody chose.
   *Fixed:* a warm-up run of the same day; each starts with what it left the night
   before. This exposed a planning blind spot — a published block at 00:00 was
   invisible before midnight. *Fixed:* GridSense sees tomorrow's published
   schedule (LESCO publishes ahead).
5. *Feeder categories shared one random stream* (the night block never changed).
   *Fixed:* each category draws its own outages.
6. *usual_occupancy was the generator's script* (perfect foreknowledge).
   *Fixed:* GridSense learns it from four other generated days (rooms used ≥50%
   of days per 30-min slot); the plan no longer carries it.
7. *Sun thrown away in outages while rooms sat at 39 °C.* *Added:* with the
   battery full, curtailed sun runs wanted ACs the battery could not, the pump and
   pending laundry/ironing; comfort also cools warm occupied rooms. A flap this
   introduced (the plan dropped its own room once cooled below 28 °C) was caught
   by the flapping test and fixed with the same hysteresis as the soak.
8. *Comfort's night reserve covered one AC for three sleeping bedrooms*; it now
   covers each bedroom the learned routine expects asleep.
9. *Stale README numbers / overstated claims:* rewritten from fresh runs. The old
   "eco is 8% cheaper" does not survive the honest accounting — eco now costs the
   same as the default (Rs 382 vs 380) while never going dark (default 70
   min/day) and sleeping hotter (628 vs 521); stated plainly. "Runs on battery at
   peak" became "spends the battery above the reserve"; comfort's 4.1 kWh of
   peak import is stated as the cost of its reserve.
10. *Viewer:* events matched across controllers by topic and time; even chart
   ticks; the dark banner names the real reason and sits off the hall label; the
   flow card shows curtailed sun. *Wording:* "three controllers" → four.
11. *Tests:* the same-day test compares all four; the solar tests cover the
   outage branch and the exact split; a shared-charge-limit test; an overload-
   not-cutoff test; the bill test recomputes from the minute series instead of
   copying the formula; reserve and stress tests find suitable outages/seeds
   instead of hard-coding them. Tests 65 → 67.

**Round 6 — the rebuilt physics, re-checked.**
- `tools/sweep_home.py` on the round-5 engine (warm starts, exact accounting,
  per-category outages): 0 violations over 30 days; the categories now differ
  (June default dark 44 / 60 / 61 min for III / IV / V).
- *Found:* the README said October bills were "a few rupees either way"; with
  honest export accounting they are negative (the houses export more than they
  buy) except under the UPS circuit (Rs 69–107). *Fixed* in the README.
- *Found (UI, 00:00 on a day starting inside an outage):* GridSense logged
  "pre-cool before the outage 00:00–02:00", "fill the tank" and a reserve hold at
  the instant the outage began — its first decision ran before the grid sensor's
  first reading. *Fixed:* the simulator publishes the grid state before the first
  tick; test added (seed 7 starts inside the 00:00 block).
- Tests 67 → 68.

**Round 7 — the viewer, both seasons.**
- *Measured:* contrast of the home's energy colours against the panel, computed
  from the live tokens: dark theme 6.3–10.4:1, light 4.8–7.1:1 — all above 4.5:1.
- *Found:* the viewer could only show June; the October story (nobody too hot,
  negative bills, the UPS circuit still paying) was invisible. *Added:* a
  June/October switch. The replay carries both seasons (`window.HOME_SCENARIOS`;
  `window.HOME` stays June); switching rebuilds the index, the finder, legend,
  day charts and comparison. The UI check switches to October and requires the
  scenario and comparison to change. The replay test checks both seasons share
  the current source digest.

**Round 8 — a path to a real inverter.**
- *Found:* the home had no hardware path at all; the office had an MQTT bridge
  and live mode, the house only a replay. Most solar homes here that log their
  inverter use SolarAssistant, which already speaks MQTT.
- *Added:* `solar_assistant.py` — inbound battery SOC, PV, load and grid volts
  rescaled onto the home topics GridSense reads (grid up/down from a voltage
  threshold, published on change only); outbound `home/inverter/settings` becomes
  SolarAssistant's output-priority and max-grid-charge-current `/set` messages.
  Topic names live in `plans/solar_assistant_map.json`. `live_home.py` runs the
  house against a broker (paced clock, `--solar-assistant`); `HomeSim.run` gained
  `until` and `on_tick` for it.
- *Re-checked:* a fake broker test feeds SOC 57 % / 3450 W / 0 V and sees
  GridSense read 0.57 / 3.45 kW / grid down, then a UTI + 1.5 kW setting reach the
  broker as "Utility first" and 31 A; a second test streams half an hour of the
  live house. The first version of the adapter test raced (asserted after the
  first `/set` arrived); it now waits for both. Five consecutive passes.
- Limitation stated in the README: never run against a real box.
- Tests 68 → 70.

**Round 9 — a machine hidden by the person using it.**
- *Found (using the viewer at 10:30):* the log said the washer ran 09:45–10:44,
  but the plan showed it off. The helper stands on the washer's spot, and her
  dot covered the glyph — every attended machine (washer, iron, pump) vanished
  exactly while it was in use.
- *Fixed:* attended machines are drawn 0.6 m beside their spot, towards the
  room's middle; the fridge stays put (it sat clear of its user and moving it
  covered the Kitchen label). The running washer was amber, the legend's colour
  for lights; it is now neutral.
- *Re-checked:* `__home.hiddenRunning()` lists running square glyphs under a
  dot; the UI check scans 06:00–23:00 every 15 min for GridSense and the default
  and fails on any. It fails on the old placement (washer under the helper,
  09:45) and passes now. Fans and ACs are excluded: their blades and bars reach
  past a dot (the first version of the check flagged fans over sleepers).

**Round 10 — labels that leave their box; closing the phase.**
- *Found (light theme, 15:00):* "100% · giving 0.32 kW" ran outside the
  Battery box of the power-flow card; "4.20 kW · 1.23 kW wasted" and
  "1.72 kW out · 228 V" are as long. *Fixed:* each box grows to its widest
  line after drawing, kept inside the card.
- *Re-checked:* the UI check scans 06:00–23:00 every 15 min for GridSense, the
  default and the UPS circuit and fails if any power-flow text leaves its box or
  the card; it fails on the old fixed-width boxes (06:00, "25% · giving
  0.67 kW") and passes now.
- *Final checks:* 70 tests pass; the home sweep (2 seasons × 3 categories ×
  5 days, 2,043 s) reports 0 problems with the same numbers as the README; the
  UI check passes with no console errors. Launchpad entry updated.
- Phase 2 closed.

## Phase 3 — Hospital (Lahore General Hospital campus)

### Research notes

- **The site comes from the map, the inside from planning practice.** The campus
  outline and its 53 building footprints are OpenStreetMap data (way 151735321,
  fetched 2026-10-18, ODbL; `plans/osm/lgh_campus.json`). OSM names the main
  hospital block (4,424 m²), the Emergency Department (1,465 m²), the Blood Bank
  and PINS. The buildings sit 17.5° off north; rotated square, the ED is a
  31 × 50 m block with one notch and the main block a 65 × 123 m comb. Interiors
  are designed, not copied: room sizes are planning assumptions (resus bay ~25 m²,
  majors cubicle ~12 m², multi-bed bay ~3.6 × 3.7 m per bed), not checked against
  the HBN 15-01 / 04-01 room data sheets, which searches did not surface.
- **Adjacencies:** ED next to imaging and resus nearest the ambulance door; triage
  between the entrance and the treatment zone; clean and soiled utility separate;
  nurse station with sight lines to the beds (SCCM 2024, FGI adjacency guides).
- **Asset tracking is the best-supported hospital IoT use.** One metropolitan
  hospital (Int J Qual Health Care 2025): equipment search 86.8% faster after
  tracking. A 3-year, 23-hospital US study: asset tracking is the best use of
  RTLS, only when hospital-wide. BLE gives room level. Nurses lose 21–60 min a
  shift searching (summaries; Nursing Times 2009: over a third ≥1 h). The
  "$14 bn search time" figure is vendor extrapolation and is not used.
- **Alarm fatigue:** a Korean ICU observed 2,184 alarms in 48 h, 63.8% false
  (Healthc Inform Res 2016); UCSF found 94.9% of one arrhythmia alarm type false.
  A 15 s annunciation delay cut ward SpO2 alarms by a further 71% (Dartmouth
  analysis) and NICU SpO2 alarms by 67% (UVA), with the warning that delays can
  hide brief desaturations.
- **Hand hygiene badges:** MedSense (6-bed ICU, BMC Infect Dis 2011) measured
  35.1% compliance over 13,694 opportunities; BioVigil (pre-print) reports higher
  compliance and fewer C. diff cases. Hawthorne effects inflate early gains.
- **Cold chain:** an automated system in Melbourne (2022) detected 28,746 fridge
  excursions against 344 on paper logs — mostly below +2 °C, 95% from one fridge
  brand: monitoring changes what is seen more than what happens. Power loss is a
  usual cause of breaches (Hosp Pharm 2024) — load-shedding makes this local.
- **Staffing in Pakistan:** the Pakistan Nursing Council standard is 1 nurse per
  10 general-ward patients; reported reality in public wards is about 1:40 (one
  repeated source, Firdos et al. 2020). Services Hospital paediatric ward
  occupancy 137.7% (2015 census). Shifts: morning 08–14, evening 14–20, night
  20–08.
- **ED flow (DES literature):** registration and triage times ~ gamma; triage
  level drives arrival mix and patience before leaving without being seen;
  first doctor consult mean 9 min (5–15). Length of stay is the most-validated
  output, then throughput, then time to triage.
- **Nurse call + RTLS:** presence can cancel a call when the nurse enters the
  room; no outcome evidence found, so the response-time effect is labelled a
  model.

### Simulation model

- **Two simulated buildings on a campus map.** The ED (ground floor) and one
  medical ward floor in the main block's south wing, each a `Plan` with rooms,
  doors and A* routes. Moves between them (admissions, porters, staff) follow a
  campus path drawn on the site plan; its length sets the walking time.
- **Patients.** ED arrivals by hour (walk-ins peaking late morning and evening;
  Rescue 1122 ambulances), a 5-colour triage (red, orange, yellow, green, blue).
  Registration → triage → bay (resus / majors / minors / chairs) → doctor →
  tests (lab sample, X-ray) → discharge, admission to the ward, or leaving
  unseen when the wait passes their patience. Ward patients carry vitals that
  drift and occasionally deteriorate.
- **Staff.** Shift rosters (doctors, nurses, porters, cleaners, guards,
  registration clerks) with BLE badges; nurses answer calls and alarms, porters
  move patients and equipment, cleaners turn beds over.
- **Equipment.** Infusion pumps, wheelchairs, trolleys and an ECG cart, each
  left wherever it was last used. Without tracking, finding one is a walk
  through likely rooms; with tracking, a walk to the nearest free one.
- **IoT.** Room-level RTLS, nurse call buttons, bedside monitors, soap
  dispensers counted against bed-zone entries, fridge probes (blood bank 2–6 °C,
  ward medicine fridge 2–8 °C) through grid outages and a generator, bed
  occupancy sensors, waiting-room counter.
- **Two rule sets, same patients and staff (matched seeds):**
  *Today* — overhead page, every alarm sounds at once, calls stay on until
  cancelled by hand, equipment found by searching, beds reported clean by phone.
  *Connected* — calls and alarms routed to the assigned nurse with escalation,
  a short annunciation delay for non-critical alarms (with the missed-brief-event
  count reported beside it), presence auto-cancels calls, an asset locator, a
  live bed board that pages the cleaner on discharge.
- **Outputs.** ED door-to-doctor and length of stay by triage colour, left
  unseen, nurse-call response, alarms reaching a nurse per hour and the critical
  ones answered late, search minutes, hand-hygiene compliance as measured,
  cold-chain minutes out of range and how fast they were noticed, bed turnaround.

### UI

- **Site view** — the campus from OSM (north arrow at 17.5°), the two simulated
  buildings drawn in full, the rest as footprints with their OSM names; patients
  and porters on the campus path.
- **Building view** — ED or ward: rooms, beds coloured by triage or status,
  people, equipment, alarms as pulses, fridge chips.
- **Management panel** — census and ED board (patients by colour and wait),
  bed board, staff on duty by place, equipment finder, alerts with their cause
  chain, the two rule sets side by side.
- **Design style and colour** — clinical and calm: the shared twin tokens with
  a teal accent; the five triage colours are reserved and only ever mean
  triage; alarm red is shared with nothing else. Dark and light themes, phone
  layout, keyboard use, offline (no CDN), contrast measured from tokens.

### Round log

**Build.**
- *Site:* `hospital_site.py` projects the OSM extract, rotates it 17.5°, places
  the ED plan on the ED footprint and the ward plan in the main block's south
  wing (turned so its lift lobby meets the corridor joining the wing), and
  finds a 264 m campus path by A* on a 2 m grid around every footprint. The
  ward's lifts are inside the main block, so the path starts from the open
  ground nearest each end.
- *Scenario:* `hospital.py` draws everything no rule set controls from separate
  streams: rosters for three shifts (plus last night's crew on at 00:00), ED
  arrivals by hour with colours, needs, patience and service times, the ward
  census and discharges, call buttons, HDU alarms (64% false, some brief real
  events), fridge doors, equipment.
- *Simulation:* `hospital_sim.py` — every person is a generator yielding
  go / wait / until; staff take tasks from a shared board; equipment can be
  searched for, carried and attached to a patient; beds run ready → reserved →
  occupied → dirty → ready. Both rule sets in ~21 s.
- *Bugs found by the first numbers (each a "surprising number"):* door to
  triage 134 min and 65 of 150 leaving unseen — the nurse waited for the patient
  within 1.6 m of the nurse's own spot, and the patient sat 2.5 m away, so every
  triage hung for a 30-min timeout (now: each task says where the patient
  should be). 304 failed fetches — the ED's six pumps were all on patients and
  the retry loop counted every 5 min (now: a drip with no pump runs by gravity
  and is counted). Only 3 admissions — porters left trolleys on the ward, so
  after three transfers the ED had none (now they bring them back). Connected
  call p90 worse than Today — a call waited for its assigned nurse even when
  that nurse was busy (now it goes to a free nurse). Red patients 13 min to a doctor —
  "seen" was stamped at the end of the consult (now at its start), and doctors
  now pause a lower-priority consult for a red patient. Leaving unseen was
  17% with exponential patience (many walk out within minutes); gamma k = 3.
- *Viewer:* `hospital.html` + `hospital.js` — Site / Emergency / Ward views,
  the management panel (board, beds, equipment, events, inspector, compare),
  census timeline with alarm ticks and fridge bars; `tools/ui_check_hospital.js`
  drives it (views, rule sets, tabs, a why chain, a real click on a person, the
  site crossing, theme, keyboard, phone width) with no console errors. A
  keyboard shortcut did nothing after clicking a header button (focus on the
  button swallowed every key); now only Space is left to the button.
- *Tests:* `tests/test_hospital.py`, 9 tests. Launchpad entry added.
- *Known weaknesses for the rounds:* every ED admission goes to this one ward,
  so up to 200 hours a day are spent waiting for a bed (a tertiary ED admits to
  many wards); patients labelled "Going for an X-ray" while waiting for a
  porter; the site map shortens "Lahore General Hospital" to "Lahore".

**Round 1 — where the admissions went.**
- *Found:* every ED admission went to this one 36-bed ward, so up to 200
  hours a day were spent waiting for a bed. A tertiary ED admits to many wards.
  *Fixed:* each admission is medical (40%, this ward) or for another ward,
  which finds a bed after a drawn delay; a porter then takes the patient (and
  any pump on them) to the main block, where they leave the model.
- *Found while checking that fix — numbers got worse, not better:* still only 3
  admissions; three porters stood at the ward entrance from 09:00 to midnight
  holding all three trolleys. A walk whose last leg had zero length (the
  destination was the entrance itself) was consumed without resuming the
  walker's next step, so porter and patient both froze. *Fixed* in the
  movement step; a test now fails if any task is taken, reached and unfinished
  for over an hour — checked to fail on the old code.
- *Found:* a porter escorting a patient to X-ray waited through the queue and
  the scan, tying up one of only 1–2 porters for up to an hour; the board said
  "Going for an X-ray" throughout. *Fixed:* the porter drops the patient (the
  chair stays with them), a separate task brings them back; the X-ray room
  serves a first-come queue; labels say which stage they are at.
- *Found:* every minors couch and chair got a 10-min deep clean after each
  consult, burying the one ED cleaner (9 cleans open at midnight). Couches and
  chairs are wiped (2 min); cubicles and resus bays keep 10 min.
- *Found in the UI:* the site map called the main block "Lahore" (a replace
  applied in the wrong order); the bed KPI wrapped "2 · 2 dirty" over two lines.
  Both fixed.
- *Test fixed honestly:* "critical alarms reached in the same seconds under both
  rule sets" only held while nurses happened to stand in the same places; the
  test now checks the actual claim — critical alarms sound the second they
  start, sustained ones 15 s later.
- *Re-checked:* seed 7: 18 admitted (was 3), 23.7 h waiting for a ward bed
  (was 98); three other days 24–54 h. Leaving unseen stays 22%: about 165
  patients × ~24 doctor-minutes is 66 doctor-hours against 60 rostered — the
  doctors, not the sensors, are the bottleneck, and badges do not change that.
- Office and home replays regenerated: adding the hospital to `SOURCES` in
  export.py changed their digests (content unchanged). Tests 79 → 80.

**Round 2 — floors and a basement (user request, 2026-10-20).**
- *Asked for:* buildings with several floors and a basement, not one flat floor.
- *Engine:* `plan.py` takes `floors` (each laid out in its own area of one 2D
  space) and `portals` — stairs, lifts and ramps as routing edges whose cost is
  the real climb (stairs 9 m a level; a lift 4.5 m a level plus an 18 m-equivalent
  wait), not the gap on the drawing. A* drops its distance heuristic when the
  floors differ (the hop is shorter than the drawing). Walkers on a hop wait where
  they got on, then appear where they get off; `seg_len` gives every walker,
  `path_length` and the viewer (`TwinCore.setHops`) the same lengths, so replays
  stay in step. Single-floor plans are untouched (office and home tests pass).
- *Hospital:* the ED block gains a basement (central store with four spare pumps,
  CSSD, mortuary, generator, medical gas, water) by lift and stairs; the main
  block becomes ground floor (entrance hall, pharmacy, admissions, lab,
  radiology) with the medical ward on floor 2 by lift and stairs. Today's search
  for a pump now ends in the basement (96 min of searching on seed 7); Connected's
  par level brings spares up from the basement first and the ward second (1 drip
  without a pump, was 4).
- *Viewer:* a floor switcher showing how many people are on each floor, lifts
  and stairs drawn on every floor, and **Follow on the map** in the inspector: the
  camera keeps the chosen person in view across floors, buildings and the campus,
  as a game map does. The UI check follows a porter and requires the view to move
  on its own; it requires the basement's spare pumps to be drawn.
- *Test:* a floor change goes through exactly one hop at the stairs' cost.

## Phase 4 — Lahore traffic (real roads)

*User, 2026-10-20: the earlier traffic work (traffic-agents) was a square grid turned
into traffic — wrong. Mimic real roads: bridges and flyovers, underpasses, small
streets, single-lane and multi-lane, two-way and one-way; and a map that loads
around the car as it drives, like an in-game map. Moved ahead of the remaining
hospital rounds, which continue alongside.*

### Research notes

- **The roads come from OpenStreetMap**, Gulberg / Kalma Chowk / Canal Road
  (31.490–31.530 N, 74.310–74.355 E), fetched 2026-10-18: 2,279 ways — trunk,
  primary, secondary, tertiary, residential, living streets, service lanes and
  link roads — with 337 one-way segments, 70 lane counts, 21 bridge segments
  (Kalma Chowk Flyover, Ferozepur Road Flyover, Jinnah Bridge) and 13 tunnel
  segments (the Canal Road underpasses). ODbL; attribution on the map.
- **Signals are barely mapped**: 2 traffic-signal nodes in the whole area. Signals
  are placed at at-grade junctions of tertiary-or-bigger roads and said to be
  placed, not mapped. The Canal Road corridor is signal-free by design (U-turns
  and underpasses), which the network reproduces because its underpasses share no
  nodes with the roads above.
- **Vehicle mix (Punjab Excise, registered in Lahore, 30 Sep 2024):** about 70%
  motorcycles, 22% cars, 3% rickshaws; buses and vans make up the rest.
- **Driving models:** the Intelligent Driver Model for following, MOBIL for lane
  changes (politeness, threshold, safe deceleration); published values are for
  highways (1.5 s headway, 2 m jam gap), so urban values are assumptions:
  shorter headways for motorcycles, lower desired speeds by road class.
- **Delay causes in Lahore (JICA peak-hour survey, Mall Road area):** signal
  stops, lane encroachment and illegal parking.

### Simulation model

- Road graph: ways split at shared nodes into directed links with lanes (tag, or
  a default by class), speed limit by class, layer (bridge +1, tunnel −1). Roads
  on different layers never meet unless OSM joins them, so flyovers pass over.
- Vehicles with a type (motorcycle, car, rickshaw, bus), IDM following per lane,
  MOBIL-style lane changes; motorcycles take shorter gaps.
- Trips between the network's edges and interior streets, routed by travel time;
  a morning-peak demand curve.
- Junctions: signals (fixed-time vs adaptive from loop detectors), priority to the
  bigger road where unsignalised.
- Outputs: travel time, delay per junction (the hotspot list phase 5 starts from),
  queue lengths, stops per trip, throughput.

### UI

- A map drawn from the road geometry: lane markings, one-way arrows, flyovers
  drawn above with a shadow, underpasses dashed below, road names.
- **Streaming map**: the geometry is cut into tiles; only tiles near the camera
  are drawn, fading in as they arrive, like a game map. **Follow a vehicle**: the
  camera rides with it, a minimap shows where it is in the area.
- Junction inspector (signal phases, queue), hotspot list, the rule sets side by
  side, About panel, run-with-your-values (demand, signal plan).
- Same shared tokens; road colours by class, red/amber/green for signals only.

### Round log

**Build (2026-10-20).**
- *Network* (`roads.py`): 2,265 OSM ways → 5,395 road pieces, 9,698 directed links,
  lanes from tags or class, layers for flyovers (+1) and underpasses (−1); the
  largest strongly connected part kept. First load took 62 s (list membership in a
  loop) → 0.24 s. Signal sites: 132 at first (every node of every divided-road
  crossing), then 11 (secondary-only), then 39 → 33 controllers: two named roads,
  one secondary or bigger, nodes within 45 m grouped.
- *Found in the data*: OSM joins two residential streets to the middle of a flyover.
  A node inside a raised span now connects only links on the same layer; a test
  checks both directions. Printing a link recursed through its neighbours into a
  MemoryError; `out` no longer appears in its repr.
- *Simulation* (`traffic_sim.py`): IDM following, MOBIL-style lane changes, give way
  to the bigger road, red and amber, spillback, a morning peak of 7,078 trips routed
  on free-flow time; fixed vs adaptive (loop detectors) signals. Entry points: the
  ends of big roads where the extract cuts them (the bounding box was useless — whole
  ways come back from Overpass). 31 s per rule set.
- *Viewer* (`traffic.html` / `traffic.js`): tiles stream in around the camera with a
  fade, drag to pan, scroll to zoom, minimap, follow a vehicle (hops to another on
  arrival), lane markings, one-way arrows, flyovers on top with a shadow, underpasses
  dashed, signals per approach, hotspot list that flies to the junction. Replay
  13.4 MB → 8.1 MB: whole-metre deltas every 4 s, routes stored once.
- Adaptive vs fixed on the same trips: median delay 53 → 20 s, stops 3.7 → 2.2,
  vehicle-hours stopped at signals 53 → 10. Known weaknesses for the rounds: ~550
  vehicles still driving or never entered after 15 min of clearance; mean speed
  34–37 km/h is fast for a Lahore peak; one Urdu-only road name.

## One app (user request, 2026-10-20)

- `viewer/index.html` is the shell: overview cards with each module's headline
  numbers, About for every module (`about.js`), each module's own dashboard in a
  frame, hash routing, one theme. Module pages hide their own navigation inside it
  (`embed.js`) and keep an About button. `serve.py` serves the app and runs
  **Run with your values** (`/api/run/<module>`, inputs range-checked, cached by
  inputs, "Your run" label on the result). `run.bat` starts it; one Launchpad entry.
- `tools/ui_check_app.js` uses the whole app through the server: every card, About,
  module buttons and tabs, all four forms with typed values checked against the
  result, an out-of-range input refused, phone width. It found: the traffic run's
  label said "seed undefined"; the home form promised a minute for a 3–4 minute run;
  plus three bugs in the check itself (a tab's internal name, reading the frame's
  theme before the message arrived, a malformed select locator).
- Office: the sensor noise split into three streams (motion misses, waving, CO₂ and
  temperature readings), so one rule set's choices no longer reshuffle the other's
  motion misses; the 20-day sweep went from 1 problem to 0.
- Demo: `tools/demo_video.py` records a 41 s walkthrough (kept out of git) and 19
  screenshots in `docs/screenshots/`, embedded in the README.

### Traffic round log

**Round 1 — a metre of road that froze an avenue.**
- *Found:* after the hour plus 15 minutes of clearance, 318 vehicles were still on the
  map, every one of them stopped, and 227 had never got on — the same 227 under both
  signal plans, so not congestion. Following the queue from North Avenue to its head:
  a car 0.2 m from the end of its link, the next link on its route empty and 1.1 m
  long. Car-following looked only one link ahead, so the car saw 1.3 m of road, less
  than its jam gap, and stopped for good; North Avenue and Maqbool Road queued behind
  it all morning. OSM splits roads into stubs that short wherever two ways meet.
- *Fixed:* the look-ahead walks the route across links for up to 100 m until it finds
  a vehicle or a red light. All 7,078 trips now finish under both plans.
- *Test:* a 20-minute peak must leave nobody waiting to enter and nobody standing still
  at the end (a late long trip may still be driving: the first version of the test
  counted a rickshaw doing 34 km/h as stuck). Checked to fail on the old code.
- *Not fixed, stated:* peak speeds of 34–37 km/h are probably optimistic (no parking,
  pedestrians or lane indiscipline modelled); no measured peak-hour figure for Lahore
  was found to calibrate against, so none was invented. README says so.

**Round 2 — reading the map up close.**
- *Looked at:* Kalma Chowk at 0.8 m per pixel, a Canal Road underpass, the light theme,
  a phone.
- *Found:* the Kalma Chowk Flyover had the colour of the roads it crosses; its shadow
  was too faint to read as "above". *Fixed:* a flyover's deck gets a light outline.
- *Found:* at street zoom the vehicles were specks next to roads drawn at full lane
  width. *Fixed:* a minimum size (motorcycle 5 × 3 px, others 8 × 4) with a dark rim.
- *Found:* a hotspot was called "near Street 13" — the nearest named road of any size.
  *Fixed:* unnamed junctions take the nearest named tertiary-or-bigger road.
- *Found:* three roads are named only in Urdu in OSM, and two of them (MM Alam Road,
  Ali Zaib Road) are the same roads as English-named pieces — one road under two
  names looks like a crossing to the signal placer. *Fixed:* the three names map to
  their English forms. The signal count did not change (33), so no false crossing had
  been created; the hotspot list now reads "Canal Bank Road / Chaudhary Ali Anwar Road".
- Phone: no sideways scroll; the underpass reads as dashed and dimmed; light theme fine.

**Round 3 — three more mornings, three demand levels.**
- *Added:* `tools/sweep_traffic.py` — seeds 11–13 × 4,000 / 8,000 / 12,000 trips an
  hour × both rule sets; invariants: nobody gridlocked, nobody left off the map, nobody
  faster than road (×1.05) or vehicle allows, adaptive never holds vehicles at signals
  longer than fixed.
- *First run, 6 "problems" — none a bug:* the invariant was "standing still at the
  end". At 4,000 trips an hour the single "stuck" car had waited 50 s at a red light
  when the run ended; at 12,000 with fixed signals 672 vehicles were still on the map,
  none of them still for more than five minutes — the network over capacity and
  draining, not locked. *Fixed the measure, not the model:* each vehicle records when
  it last came to a standstill; "gridlocked" means still for over five minutes, in the
  sweep, the regression test (which could have failed on a red light) and the Compare
  tab.
- *Second run: 0 problems.* Adaptive beats fixed at every load; at 12,000 trips an hour
  fixed signals leave about 600 vehicles draining after the 15-minute clearance and
  adaptive about a tenth of that, with median delay 82–84 s → 41–48 s. In the README.

**Round 4 — watching it play.**
- *Measured:* a full redraw takes ~20 ms for the whole map and ~8 ms zoomed in; the
  junction panel updates while playing; a click on the timeline jumps there.
- *Found:* when the followed vehicle arrived, the camera jumped to another part of the
  city with no word of why. *Fixed:* the camera glides to the next vehicle over 0.7 s
  and the Follow panel says "Motorcycle #2302 arrived at 07:59; now riding with the
  next one."
- *Found (by making the streaming check strict):* the map opens on the whole area, so
  all 197 tiles were loaded on the first frame and nothing ever streamed again — the
  "game map" effect lasted one frame. *Fixed:* tiles out of view for two seconds are
  released and stream back in when the camera returns; zoomed in the map holds 80
  tiles and a pan streams in 32 new ones.
- *Added:* `tools/ui_check_traffic.js` — panning streams new tiles, a drag does not
  start following, following hops on arrival and says so, a hotspot opens its live
  junction, the comparison fills, a full redraw stays under 60 ms, light theme, phone.

**Round 5 — do the flyovers carry what they should?**
- *Counted:* trips per flyover and underpass. Kalma Chowk Flyover 1,180, Model Town
  Underpass 563 — but Ferozepur Road Flyover only 54. Routes were chosen on free-flow
  time, which ignores signal waits, so a flyover looked no faster than the signalled
  road under it. *Fixed:* routing adds half a fixed cycle (17.5 s) for every signalled
  approach — the trade a Lahore driver makes. Ferozepur Road Flyover 54 → 1,269 trips,
  now the busiest raised road; the delay baseline stays pure free-flow time (the
  routing cost must not become the yardstick). Delays fall under both rule sets
  (fixed median 54 → 35 s, adaptive 20 → 12 s); adaptive still about a third of fixed.
- *Found by the traffic UI check:* "junction panel did not update while playing" — an
  adaptive junction holding one phase showed the same text for 45 simulated seconds.
  *Fixed:* the panel is live — vehicles waiting on each phase's approaches and how long
  the current state has lasted.
- Unused raised pieces (Ali Zaib Road and Tipu Road underpasses, a Wahdat Road flyover
  piece) stay unused: no trip's best route crosses them in this demand.

**Round 6 — the sweep again, and the claims that went stale.**
- *Re-ran* `tools/sweep_traffic.py` against round 5's signal-aware routing: 0 problems in
  18 runs. At 12,000 trips an hour fixed signals leave 180–340 vehicles draining after
  the peak, adaptive 12–33; median delay 53–61 s → 27–35 s. README updated.
- *Found:* the traffic About panel still said adaptive signals "roughly halve" median
  delay (now about two-thirds: 35 → 12 s) and that Garden Town's Main Boulevard
  crossing stays worst under both rule sets. With drivers routing around signals the
  worst is Allama Shabbir Usmani Road / Kiramat Road under fixed and Ghalib Road / Main
  Boulevard Gulberg under adaptive. *Fixed:* both sentences now say what the data says —
  the same few junctions stay near the top under both.

**Round 7 — no mouse.**
- *Checked:* Space, ← →, + −, f and Esc all do what they say; every header control is
  in the Tab order with a visible focus ring.
- *Found:* the hotspot list was plain list items — a keyboard user could not open a
  junction — and there was no way to pan the map without dragging. *Fixed:* hotspots
  are focusable buttons (Enter or Space flies there), Shift + arrows pan a quarter
  screen, and the keys are listed in the module's About panel. The traffic UI check now
  opens a junction with Enter and pans with Shift + →.

**Round 8 — Run with your values at the edges.**
- Through the real server: 2,000 trips an hour simulated in 38 s, 12,000 in 104 s; the
  12,000 replay (10,745 trips, 12.6 MB) opens in the viewer in 0.8 s with no errors and
  is labelled "Your run · seed 5 · 12,000 trips/h". 50,000 and "lots" are refused with
  their reasons. No change needed; recorded so the numbers can be checked later.

## Watch the demo (user request, 2026-10-20)

- *Asked for:* open the projects with real inputs and let them run themselves — no clicking.
- *Built:* `viewer/demo.js` — **▶ Watch the demo** (or `/#demo`): asks the server to
  simulate all four modules from real inputs (office: day 11, 36 staff, 6 visitors;
  hospital: 120% arrivals, 3 ward nurses, 15 s alarm delay; traffic: 9,000 trips an hour;
  home: a June day of category V load-shedding), shows each as soon as its run is ready
  and drives it through its own buttons — play, floors, views, following a vehicle, the
  junction, the comparison — with a caption saying what is on screen. First time ~6
  minutes (the runs are real), then ~2.5 minutes from the cache.
- *Found while testing it:* the home viewer threw when the minute series said "grid down"
  a moment before the outage list did (an outage's edge) — guarded. Captions written in
  advance did not match some days (the pump ran at 07:16, not 11:00; one day had no
  pre-cool), so the home scenes now jump to the moments this run's controller actually
  acted and quote its own decision.
- Launchpad's server on 8860 was the old static one (no API); replaced by `run.bat`
  (serve.py) on the same port.

## Real-life logic (user request, 2026-10-20)

- *Asked for:* people coming and going at home (school, office, university, father back,
  grandparents and relatives visiting) and the IoT planned around it; thousands of cars
  with real stops (shops, pharmacy, shopping), queues at red, real signal timing (about
  60 s green, 30 s red), more signals where real ones are; the same real-life logic in
  every module, Pakistani roads with underpasses and flyovers.

**Home: who comes and goes.**
- *Built:* labelled reasons for every absence (at the office, at university, school van),
  the mother's market and pharmacy trip, evening tuition, the father's groceries;
  neighbours in the morning, 2–4 relatives in the evening (father and Dadi sit with them),
  Nana and Nani some afternoons (shares are assumptions). A beam counter on the gate
  publishes `home/gate/count` on every crossing. New **People** tab: at home / out (and
  why, since when) / visitors due, a head-count chart for the day, the gate log; click
  anyone to inspect them.
- *Found:* the mother's outing was added before her day was built, so `day_of` overwrote
  it and she never left the house on any seed (0 of 12). *Fixed:* planned after her day;
  a test now needs her market trip somewhere in 12 days. The old "people who go out are
  not at home" test looked for the label `"Out"` exactly — with reasons on every label it
  would have checked nobody; it now matches the prefix and only people out since morning.
- *Found:* "Bath 2" and the "Wash area" were the same 2.5 × 3.5 m rectangle, with the
  shower and the iron on the same point; their labels overprinted ("WBathrea"). *Fixed:*
  a 1.7 m bathroom and a 1.8 m wash area, each with its own door onto the passage.
- Checked in the browser: at 19:53 on day 7 the People tab says 9 at home, 0 out,
  3 guests — the same as the gate counter — and the drawing-room fan is on for them.

**Traffic: trips with reasons, real places, real signal plans.**
- *Built:* 433 shops and amenities from OpenStreetMap (Overpass, 2026-10-20), 432 snapped
  to the street they open onto. Evening (17:30) and morning (07:30) peaks with different
  purposes: evening — home, shopping, mall, takeaway, dinner out, pharmacy, bank, fuel,
  prayers, tuition pick-up; morning — work, school run, university, breakfast, fuel.
  Drivers pick the most convenient of four places that sell it. Drop-offs, pick-ups,
  pharmacy and takeaway stop in the kerb lane (blocking it, side friction as on Lahore's
  roads); fuel, banks, shops and long stops pull off to park; trips to the mall, a
  restaurant or the hospital end there. Rickshaws stop for passengers every 0.9–2.5 km
  and wagons every 0.7–1 km, anywhere along the kerb.
- Signals: a signal wherever two named through roads (tertiary or bigger) cross at grade
  — 59 controllers, was 33. Fixed plan 60 s green for the bigger road, 30 s for the side
  road, 3 s amber, 2 s all-red (a 100 s cycle); each junction starts at its own point of
  the cycle, so a light can turn red as you reach it. Adaptive: 10 s minimum, at most
  1.5 × the fixed green. Route choice uses each approach's own expected wait
  (red² / 2·cycle). Fixed signals show countdown timers, as Lahore's do.
- *Found:* "Shah Kamal Rd" and "Shah Kamal Road", and "Masood Faooqi Road", made one road
  look like a crossing of two; a way named "Liberty Roundabout" was not tagged as one.
  *Fixed:* names normalised (" Rd" → " Road", a spelling table), "Roundabout" in the name
  counts as a roundabout; a repeated junction name gets "(2)".
- *Found:* a motorcycle sat 5+ minutes behind a car stopped at the kerb for fuel — the
  gridlock test's own scenario. Fuel stations have forecourts. *Fixed:* only drop-offs,
  pharmacy and takeaway use the kerb; a driver stuck within 25 m of their stop does it
  there.
- *Found:* the acceleration pass walked all 15,000 lane lists every second. *Fixed:*
  only links with vehicles on them — identical results, 31 s → 13 s for 20 minutes.
- Viewer: shops on the map (hover: here now, visits this hour), a **Places** tab of the
  busiest, parked vehicles beside the kerb, an "At shops and stops" KPI, the Follow panel
  says why the trip is made and lists its stops with times, junction countdowns. Unnamed
  places (13) are called after their street ("Fuel station on Firozpur Road").
- Evening, 8,000 trips an hour (seed 7): 7,097 trips, 1,763 stops at real places, 322
  trips ended at one, 1,996 passenger stops; median delay 105 s fixed / 60 s adaptive,
  signal stops 90 → 21 vehicle-hours; nobody gridlocked. Worst junction: Firozpur Road /
  Wahdat Road.

**Office: going out and coming back.**
- *Built:* staff step out and return through the badge doors: lunch at a dhaba (15%), the
  bank (5%), the school pick-up (6%), client visits (8% of staff, 30% of managers); 3–6
  couriers and food-delivery riders a day hand over at the reception counter (most food at
  lunchtime) and never cross a badge door. All shares are assumptions.
- *Found:* with that much coming and going the roll-call got worse — mean error 0.7–1.0 →
  2.0 people, worst 7–9 (four days, against the committed code in a separate worktree).
  Traced person by person: everyone missing from the estimate was inside with a phone; they
  had tapped out of one floor's badge door and walked in behind a colleague at the other,
  and the beam counted the group as one. The problem was always there; real-life traffic
  made it show.
- *Fixed (an IoT change, not a tweak):* phones on the office Wi-Fi. An access point sees a
  phone 20–90 s after its owner arrives and drops it 5 minutes after they leave (93% of
  people carry one). First rule tried — "latest evidence wins" — barely helped (2.0 → 1.0–2.0):
  a stale badge-out outvoted a phone that had never left. The rule now: a phone on the Wi-Fi
  means inside, except in the 5 minutes after a badge-out; off the Wi-Fi, a newer badge-in
  decides. Mean error 0.2–0.4, worst 3, on four days. The attendance panel shows both
  estimates and the chart draws both lines.
- *Found:* "Run with your values" cached runs by their inputs alone, so after this round the
  home, hospital and office runs came back in 0 s from the old code (no gate counter, no
  outings). *Fixed:* the cache key includes the module's source digest; `tests/test_serve.py`
  fails on the old key.
- The overview card said "trips in the morning peak" for an evening run; it reads the
  period now, and shows the shop stops instead of the road count.

**Traffic sweep after the real-life changes** (`tools/sweep_traffic.py`, 3 days × 2 peaks ×
3 loads × 2 rule sets, 45-minute runs).
- Up to 8,000 trips an hour: 0 problems — nobody gridlocked, everyone entered, no parked car
  moved, nobody over the speed limit, adaptive always ahead. Median delay 62–72 → 18–23 s at
  4,000, 94–107 → 51–64 s at 8,000.
- At 12,000 the fixed plan gridlocked in 4 of 6 runs (21–336 vehicles still 5+ min). Traced
  every stuck queue to its head: one-lane North Avenue links packed end to end (58, 58, 31
  vehicles) back from a red at Lane 24 — no shop stop, parked or held vehicle in any chain,
  no simulator fault. Adaptive signals never gridlocked. The sweep now reports overload
  outcomes at 12,000 separately from problems; they are what the junction planner is for.

**Hospital: families.**
- *Built:* every emergency patient arrives with 1–3 relatives (2–3 with an ambulance or a red
  triage) who follow them to the waiting hall, the bay and across the campus to the ward;
  each ward patient has one relative staying the night, who goes down to the ground-floor
  pharmacy for the medicines after the morning round (70%); families visit together, 0–4 a
  patient, between 11:00 and 21:00. Connected adds one attendant card per patient (the others
  wait outside the ED door) and a pass desk in the ward lobby: 16:00–18:00, two per bed,
  early families wait downstairs, late ones are turned away. All shares are assumptions;
  the families draw from their own random stream, so every clinical result is unchanged
  (a test runs the day with and without them).
- *Found:* a "crowded bed minutes" metric read 0 under both rule sets — visitors arrived at
  independent random times and never met at a bed. Families visit together; once modelled
  that way Today reaches 4 at one bed and Connected never passes 2. The metric was dropped
  for "most visitors at one bed", checked every minute (the first test only looked at
  midnight).
- *Found:* attendants were drawn in the Orange triage colour. Now sand.
- Day 7: relatives in the ED bays 11.9 → 6.1 on average (peak 29 → 14); ward visitor-minutes
  outside visiting hours 3,010 → 19; most at one bed 4 → 2; costs counted: 32 on the ward at
  16:00 against 12, 40 families waiting downstairs, 18 turned away after 18:00.
