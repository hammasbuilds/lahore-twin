# Lahore Twin — build plan and round log

One 2D world, six phases, built in this order. No phase starts before the one
above it has finished its build **and** ten review rounds.

| # | Phase | Status |
|---|---|---|
| 1 | Office tower — people, attendance, IoT, energy | review round 9 of 10 done |
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
