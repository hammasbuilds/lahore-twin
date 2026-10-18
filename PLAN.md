# Lahore Twin — build plan and round log

One 2D world, six phases, built in this order. No phase starts before the one
above it has finished its build **and** ten review rounds.

| # | Phase | Status |
|---|---|---|
| 1 | Office tower — people, attendance, IoT, energy | done: build + 10 review rounds |
| 2 | Home + GridSense — load-shedding energy manager | review round 7 of 10 done |
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
