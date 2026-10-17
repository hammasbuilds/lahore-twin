# lahore-twin

A 2D simulated world for building and testing IoT automation without owning a
single sensor. Every device is simulated behind an MQTT-style topic, so a real
ESP32 or Zigbee sensor can replace a simulated one without touching the rules.

| # | Phase | What it simulates | Status |
|---|---|---|---|
| 1 | [Office tower](#phase-1--office-tower) | 34 people, badge gate, meeting rooms, lights, AC, CO₂, attendance | built, in review |
| 2 | Home + GridSense | load-shedding-aware home energy manager | planned |
| 3 | Hospital | staff, patients, IoT devices, management panel | planned |
| 4 | Lahore traffic | OpenStreetMap road network, smart signals, hotspot finder | planned |
| 5 | Junction fix planner | test underpass / U-turn / flyover options; ambulance green wave | planned |
| 6 | City systems | smog, underpass flooding, streetlights | planned |

```bash
python demo.py               # simulate the office day three ways, write the replay
# then open viewer/index.html in a browser — no server, no network
python -m pytest -q          # 38 tests, including the viewer's core under node
python tools/sweep.py         # invariants over 20 simulated days (~5 min)
```

Python 3.10+, standard library only. The viewer is one offline HTML page.
`run.bat` serves it on http://127.0.0.1:8860 (the Launchpad entry "Lahore Twin — office" starts it).

## Phase 1 — Office tower

A ground floor of 21 rooms: reception, lobby, two meeting rooms, an open
workspace with 24 desks, three phone booths, two manager cabins, cafeteria,
washrooms, prayer room, electrical room, storage, and a 12-bay car park.

**People.** 24 staff, 2 managers, a receptionist, an office boy, a guard, a
cleaner and visitors. Each gets a generated day: arrive (60% drive; the car
park fills and the rest walk in from the gate), badge in, desk work, meetings
from a booking calendar, the lunch queue, congregational prayer, washroom and
coffee breaks, the office boy's tea rounds, the guard's patrols, the cleaner's
morning round. Some people forget their badge, tailgate through the gate,
forget to badge out, or sit so still a motion sensor stops seeing them.

**Devices.** Per room: motion sensor (sees a walking person 90% of seconds, a
still one about once in five minutes), CO₂ (mass balance, ±10 ppm noise),
temperature (first-order thermal model, Lahore October outdoor curve), lights,
inverter AC holding 24 °C, demand-controlled ventilation. At each badge door: a reader and a beam counter. A
sensor in every parking bay.

**Rules.** The same day runs three times with identical people:

| rule set | what it does |
|---|---|
| Fixed schedule | lights and AC on 08:30–18:30 everywhere — what most offices do |
| Motion | rooms follow motion sensors (10 minute hold that adapts per room), AC pre-cools booked rooms and prayer times from their measured temperature |
| Motion + CO₂ | as Motion, but a room is declared empty only when its CO₂ is falling or near outdoor level |

Plus: tailgate detection (door counter vs badge reads), late arrivals, meeting
no-shows released after 10 minutes, cafeteria queue alerts, CO₂ ventilation
boost, missing badge-outs. Every command records the message that caused it,
so the viewer can answer "why is this light on?".

### Output

`python demo.py`, seed 7 (a simulated building, not a measurement):

```
                                      Fixed schedule          Motion    Motion + CO2
Lights + AC (kWh)                             198.35           169.4          168.63
  lights                                       75.03           53.62           53.02
  AC                                          123.33          115.78          115.62
Person-minutes in the dark                        23               8               6
Person-minutes too warm (>26 C)                  252              24              21
Person-minutes stuffy (CO2 >1000)                 25              25              25
Lights switched off on someone                     3              28              16
Wall-switch presses                               23               2               2
Room-minutes lit while empty                    9044            2737            2643
```

**Energy.** Occupancy control uses 15% less lighting and AC energy than the
fixed schedule (15.0–16.3% across five days, `python demo.py --week`; ahead on
every one of 20 days, `python tools/sweep.py`). The schedule is not a straw man:
everyone has wall switches, so early arrivals switch lights on by hand — which
then burn all day.

**Comfort.** Occupancy control is cooler for the people in the rooms (21 vs 252
person-minutes above 26 °C) because pre-cooling starts from each room's measured
temperature: with a fixed 15-minute lead, the heat-soaked prayer room was still
27 °C when the Zuhr congregation walked in. The schedule's heat is overtime
staff after the 18:30 switch-off.

**Lights going off on people.** Motion sensors alone switch lights off on
someone sitting still 28 times a day; requiring CO₂ to confirm the room is
empty brings it to 16, and an adaptive hold (motion within a minute of a
switch-off doubles that room's hold; a switch-off nobody contradicts halves it)
keeps the energy saving.

**Air.** Ventilation boosts from 800 ppm CO₂ (demand-controlled), not 1000:
stuffy person-minutes fall from 333 to 25 for 3.4 kWh more, because outdoor air
in a Lahore afternoon has to be cooled — the model charges that load.

**Evacuation roll-call.** The attendance tab estimates who is behind the badge
doors: the register, plus entries nobody badged for, minus exits nobody tapped
out for. Over 20 days (08:30–18:30) it is off by 0.23 people on average and
never by more than 1; the register alone is off by 0.91 (people forget to tap
out going home — 6 too many by 17:30), door counters by 0.58 (missed counts pile
up). The residual is tailgaters the door beam merged with the person ahead.

**Tailgating.** Over five days the counter-vs-badge check caught 5 of 7
tailgates (71%) with no false alarms. The two misses are followers the beam
counted as one with the person in front; a follower in the very same second as
an explained pass is flagged "check the camera" rather than called a tailgate,
because someone lingering in the beam looks identical.

### The viewer

`viewer/index.html` replays the day: people walking, cars parking, rooms lit
and cooled, a timeline with alerts, and four map layers (devices, occupancy,
temperature, CO₂). Switch the rule set mid-replay. Click a room for its
sensors and the cause chain behind each device; click a person for their day;
the attendance tab compares the badge register with who was really there; the
compare tab puts the three rule sets side by side.

### Swapping in hardware

`lahore_twin/mqtt.py` is a standard-library MQTT 3.1.1 client and a bridge.

```bash
python -m lahore_twin.live --broker 192.168.1.10 --speed 60          # whole day, 60x
python -m lahore_twin.live --broker localhost --start 09:00 --hours 1 --speed 1
```

Every bus message is published to `lahore-twin/<topic>` as JSON
`{"t", "payload", "cause", "text"}`, so Home Assistant or any MQTT dashboard sees
the building. A real device publishes into the same rules on these topics
(anything else — commands, alerts — is refused):

| topic | payload | from |
|---|---|---|
| `lahore-twin/office/<room>/motion` | `1` | PIR |
| `lahore-twin/office/<room>/co2` | ppm, e.g. `812.0` | CO₂ sensor (SCD40, MH-Z19) |
| `lahore-twin/office/<room>/temp` | °C, e.g. `25.4` | temperature sensor |
| `lahore-twin/office/<room>/switch` | `true` | wall switch |
| `lahore-twin/office/gate/badge` | `{"person", "dir", "gate"}` | badge reader |
| `lahore-twin/office/gate/beam` | `{"dir", "gate"}` | door beam counter |

The rules answer on `lahore-twin/office/<room>/light` and `.../ac` (`true` /
`false`), which a relay node subscribes to. Tested against a fake broker that
speaks the wire protocol (`tests/test_mqtt.py`); not yet run against a physical
board.

## Layout

```
lahore_twin/   plan.py (rooms, doors, A* routing) · bus.py (MQTT-style bus with cause ids)
               office.py (people, calendar, schedules) · people.py · devices.py (room physics)
               rules.py (automation, attendance) · sim.py (1 s loop) · export.py (replay)
plans/         office.json — the floor plan as data
viewer/        index.html, app.js — offline replay viewer; replay.js is generated
tools/         ui_check.js — drives the viewer in headless Chromium for review rounds
PLAN.md        research notes, design, and the review-round log
```
