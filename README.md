# lahore-twin

A 2D simulated world for building and testing IoT automation without owning a
single sensor. Every device is simulated behind an MQTT-style topic, so a real
ESP32 or Zigbee sensor can replace a simulated one without touching the rules.

| # | Phase | What it simulates | Status |
|---|---|---|---|
| 1 | [Office tower](#phase-1--office-tower) | 34 people, badge gate, meeting rooms, lights, AC, CO₂, attendance | built, in review |
| 2 | [Home + GridSense](#phase-2--home--gridsense) | a Lahore family, 6 kWp solar, 10 kWh battery, load-shedding | built, in review |
| 3 | Hospital | staff, patients, IoT devices, management panel | planned |
| 4 | Lahore traffic | OpenStreetMap road network, smart signals, hotspot finder | planned |
| 5 | Junction fix planner | test underpass / U-turn / flyover options; ambulance green wave | planned |
| 6 | City systems | smog, underpass flooding, streetlights | planned |

```bash
python demo.py               # simulate the office day three ways, write the replay
# then open viewer/index.html in a browser — no server, no network
python -m pytest -q          # 68 tests, including the viewer's core under node
python tools/sweep.py         # invariants over 20 simulated days (~5 min)
python demo_home.py           # the house under four controllers; writes viewer/home_replay.js
python tools/sweep_home.py    # home invariants: 2 seasons x 3 feeder categories x 5 days (~11 min)
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
still one about once in five minutes) and lights. In the 12 air-conditioned
rooms also: CO₂ (mass balance, ±10 ppm noise), temperature (first-order thermal
model with ventilation load, Lahore October outdoor curve), and
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
Lights + AC (kWh)                              202.7           169.4          168.63
  lights                                       75.03           53.62           53.02
  AC                                          127.68          115.78          115.62
Person-minutes in the dark                        23               8               6
Person-minutes too warm (>26 C)                  128              24              21
Person-minutes stuffy (CO2 >1000)                 25              25              25
Lights switched off on someone                     3              28              16
Wall-switch presses                               23               2               2
AC turned on by hand                               2               0               0
Room-minutes lit while empty                    9044            2737            2643
```

**Energy.** Occupancy control uses 17% less lighting and AC energy than the
fixed schedule on this day (15.8–17.1% across five days, `python demo.py
--week`; ahead on every one of 20 days, `python tools/sweep.py`). The schedule is not a straw man:
everyone has wall switches, so early arrivals switch lights on by hand — which
then burn all day.

**Comfort.** Everyone has an AC remote under every rule set: someone settled in
a room above 26.5 °C for five minutes turns the AC on. The schedule's remaining
heat (128 person-minutes above 26 °C, against 21) is overtime staff after the
18:30 switch-off — the workspace warms before anyone reaches for the remote, and
the hourly after-hours sweep switches it off again. Occupancy control keeps the
AC on while a room is occupied until 20:00, and pre-cools booked rooms and the
prayer congregations from each room's measured temperature (with a fixed
15-minute lead the heat-soaked prayer room was still 27 °C at Zuhr).

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
up). The days split in two: on 15 the estimate is exact or nearly (median 0.01);
on 5 it is about 0.8 off all day, each because one tailgater was merged by the
door beam with the person ahead and never counted. Seed 7, the demo day, is one
of those.

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

Every bus message is published to `lahore-twin/state/<topic>` as JSON
`{"t", "payload", "cause", "text"}`, so Home Assistant or any MQTT dashboard sees
the building. A real device publishes into the same rules under
`lahore-twin/device/` (anything else — commands, alerts — is refused). The two
prefixes never overlap: a broker echoes a client's own publishes back, and with
one shared prefix every simulated reading returned as a "device" reading.

| topic | payload | from |
|---|---|---|
| `lahore-twin/device/office/<room>/motion` | `1` | PIR |
| `lahore-twin/device/office/<room>/co2` | ppm, e.g. `812.0` | CO₂ sensor (SCD40, MH-Z19) |
| `lahore-twin/device/office/<room>/temp` | °C, e.g. `25.4` | temperature sensor |
| `lahore-twin/device/office/<room>/switch` | `true` | wall switch |
| `lahore-twin/device/office/gate/badge` | `{"person", "dir", "gate"}` | badge reader |
| `lahore-twin/device/office/gate/beam` | `{"dir", "gate"}` | door beam counter |

The rules answer on `lahore-twin/state/office/<room>/light` and `.../ac`
(`true` / `false`), which a relay node subscribes to. Tested against a fake broker that
speaks the wire protocol (`tests/test_mqtt.py`); not yet run against a physical
board.

## Phase 2 — Home + GridSense

A single-storey 10-marla house in Lahore: car porch, drawing room, TV lounge,
kitchen, inverter store, dining, three bedrooms, two baths, back yard with the
water pump. A family of six and a part-time helper live a June day: school and
office, cooking, prayer, an afternoon nap, TV, laundry and ironing.

**Power.** 6 kWp of panels (Lahore June ≈ 6.3 kWh per kWp per day, NASA POWER),
a 10 kWh LFP battery (90% usable), a 6 kW hybrid inverter that trips for a minute
when overloaded, three 1.5-ton inverter ACs, fans, lights, fridge, router, TV,
a 1 hp pump filling a 1000 L roof tank, washer, iron, microwave. Mains voltage
sags toward 200 V in the evening, with dips below 190 V.

**The grid.** A LESCO-style feeder category sets the published load-shedding
(category IV: 5 hours, one block at night); one or two unannounced cuts come on
top. All four controllers see the published schedule (today's and tomorrow's) and a day-ahead solar
forecast; none sees an unannounced cut coming.

| controller | what it is |
|---|---|
| Inverter default | every circuit on the inverter, fixed settings, everything runs when wanted, pump on its float switch |
| UPS circuit | the common Lahore wiring: fans, lights, fridge, router and TV on the inverter; ACs, pump, washer, iron and microwave die in an outage |
| GridSense eco | GridSense's guarantees without the comfort extras: a reserve for fans, lights, fridge and router, off-peak charging, battery in the peak window, compressor protection |
| GridSense | holds a battery reserve sized for the next published outage (tomorrow's schedule included), pre-cools bedrooms and fills the tank before it, cools occupied rooms with sun that would otherwise be exported at Rs 11, moves laundry and ironing into solar hours, spends the battery above that reserve in the peak-tariff window, rations ACs during an outage by the energy left (sleepers first), keeps every heavy load inside the inverter's rating, and cuts the AC and fridge below 190 V |

`python demo_home.py`, June, seed 7 (a simulated house, not a measurement):

```
                                   Inverter default      UPS circuit    GridSense eco        GridSense
House dark (min)                                 61                0                0                0
No fan when wanted (person-min)                 356                0                0                0
Too hot to sleep (person-min)                   392              892              848              380
Too hot awake (person-min)                      729             1125              729              494
Roof tank empty (min)                             0                0                0                0
Grid at peak price (kWh)                        0.0             4.97              0.0             1.53
Grid off-peak (kWh)                            7.18             8.55             7.87             7.77
Exported (kWh)                                 8.54            15.94             10.0             7.38
Solar used at home (%)                         63.4             36.6             59.5             67.4
Solar wasted (kWh)                             5.32             8.04              5.3             4.94
Day's bill (Rs)                                 208              432              221              322
Inverter overload trips                           0                0                0                0
AC/fridge below 190 V (min)                      16               16                0                0
Jobs finished late                                0                0                0                0
```

Each controller starts the day with the battery it left the night before (a
warm-up run of the same day), not a level nobody chose. Over ten June days
(`python demo_home.py --days 10`, mean per day):

| | Inverter default | UPS circuit | GridSense eco | GridSense |
|---|---:|---:|---:|---:|
| house dark, minutes | 70 | 0 | 0 | 0 |
| person-minutes without a fan when wanted | 417 | 0 | 0 | 0 |
| person-minutes too hot to sleep | 521 | 688 | 628 | **391** |
| person-minutes too hot awake | 733 | 1,024 | 733 | **555** |
| grid at peak price, kWh | 1.9 | 4.4 | **1.5** | 4.1 |
| solar used at home | 80% | 50% | 78% | 83% |
| solar wasted (curtailed), kWh | 1.7 | 5.5 | 1.9 | 1.8 |
| bill, Rs | 380 | 543 | 382 | 539 |

The default setup goes dark when the battery reaches cut-off in a night outage
(70 minutes a day on average, 173 on the worst). The UPS circuit never goes dark
but cannot run an AC in an outage, and with its big loads grid-only it curtails
the most sun when the battery is full during a cut. **GridSense eco** keeps the
lights and fans on through every outage for the same money as the default — but
it sleeps hotter (628 vs 521 person-minutes), because the default runs the ACs
until the battery dies while eco keeps the battery for fans, lights and fridge.
**GridSense** is the coolest house asleep and awake and never dark, at Rs 539:
it buys a reserve big enough to run an AC in every sleeping bedroom through a
night outage, partly at peak price (4.1 kWh) — the cost of its comfort, stated.

Over 2 seasons × 3 feeder categories × 5 days (`tools/sweep_home.py`) neither
profile is ever darker than the default, trips the inverter, flaps an AC,
empties the tank or finishes a job late. In October nobody is too hot under any
setup and the houses export more than they buy: daily bills are negative for
GridSense eco (Rs −57 to −75), the default (−43 to −63) and GridSense (−19 to
−50); the UPS circuit still pays Rs 69–107, because its big loads cannot use the
inverter's sun or battery.

Tariff assumptions: off-peak Rs 42, peak Rs 50, export Rs 11 per kWh (the
proposed gross-metering buyback). The bill values each controller's end-of-day
battery change at the off-peak rate, so leaving the battery flat does not look
cheap. Appliance wattages are nameplate assumptions; no measured Pakistani
appliance dataset was found.

`viewer/home.html` replays the day: people, spinning fans, AC and light state,
a power-flow card (solar, battery, grid, house), battery and tank gauges, an
outage strip with unannounced cuts hatched, the day's power and battery charts,
every decision with its cause, and the four controllers side by side.

## Layout

```
lahore_twin/   plan.py (rooms, doors, A* routing) · bus.py (MQTT-style bus with cause ids)
               office.py (people, calendar, schedules) · people.py · devices.py (room physics)
               rules.py (automation, attendance) · sim.py (1 s loop) · export.py (replay)
               climate.py · home.py (family, outages) · power.py (PV, battery, inverter, tank)
               gridsense.py (four home controllers) · home_sim.py · export_home.py
plans/         office.json, home.json — the floor plans as data
viewer/        index.html + app.js (office), home.html + home.js (home), core.js + twin.css shared;
               replay.js and home_replay.js are generated
tools/         ui_check.js — drives the viewer in headless Chromium for review rounds
PLAN.md        research notes, design, and the review-round log
```
