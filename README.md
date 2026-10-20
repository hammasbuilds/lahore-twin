# Lahore Twin

IoT systems for a city like Lahore, simulated end to end in one app: an office tower,
a home on solar during load-shedding, a hospital, and the city's traffic on real roads.
Every device — badge readers, motion and CO₂ sensors, inverters, bedside monitors, fridge
probes, traffic signals — sits behind an MQTT-style topic, so a real sensor can replace a
simulated one without changing the rules.

![Overview: every module with its headline numbers](docs/screenshots/01-overview.png)

**Demo video (41 s):** [lahore-twin-demo.mp4](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-demo.mp4)

| Module | What it simulates | Headline result | Status |
|---|---|---|---|
| **Office tower** | 3 floors (basement car park, ground, first), 46 people, badge doors, lights, AC, CO₂ | motion + CO₂ uses **29.5% less** light and AC energy than a fixed timetable; 9 of 11 tailgates caught, no false alarms | ready |
| **Home + GridSense** | double-storey house with roof solar (6 kWp), 10 kWh battery, a day of load-shedding | GridSense keeps the house lit through every cut (**94 → 0** dark minutes); its eco setting costs about the same as the inverter default | ready |
| **Hospital** | Lahore General Hospital campus from OpenStreetMap; Emergency Department (2 floors) and a 36-bed ward on floor 2 | alarms nurses walk to **99 → 38**, equipment search **96 → 1 min**, bed turnaround **70 → 20 min** | ready |
| **Lahore traffic** | Gulberg, Kalma Chowk, Garden Town, Canal Road from OpenStreetMap: flyovers, underpasses, one-way streets, lanes; 7,078 trips | adaptive signals cut median delay **54 → 20 s** and stops per trip **3.9 → 2.3** | ready |
| Junction planner | tests underpasses, U-turns and signal plans at the worst junctions; ambulance green wave | | planned |
| City systems | smog sensors, underpass flooding alarms, smart streetlights | | planned |

## Run it

```bash
run.bat                      # Windows: serves the app on http://127.0.0.1:8860
python serve.py              # anywhere: the same, standard library only
```

Open http://127.0.0.1:8860, pick a module, press Play. Opening `viewer/index.html` straight
from disk also works for everything except **Run with your values**, which needs the server.

```bash
python demo.py               # office    — writes viewer/replay.js
python demo_home.py          # home      — viewer/home_replay.js
python demo_hospital.py      # hospital  — viewer/hospital_replay.js
python demo_traffic.py       # traffic   — viewer/traffic_replay.js
python -m pytest -q          # 90 tests
```

Python 3.10+, standard library only. No network: the map data ships in `plans/osm/`.

## What you can put in, what comes out

| Module | Inputs (Run with your values) | Outputs |
|---|---|---|
| Office | day (seed), staff with desks, visitors | floor-by-floor plan with people, lights, AC and cars; energy and comfort per rule set; attendance, tailgating, roll-call accuracy |
| Home | day, season, load-shedding category, solar kWp, battery kWh | each floor and the roof with fans, ACs, tank and panels; power flow; dark minutes, comfort, bill; every controller decision with its reason |
| Hospital | day, emergency arrivals (%), ward nurses per shift, alarm delay (s) | site, ED and ward floors with patients by triage colour; ED board, bed board, equipment list; waits, call and alarm response, search time, fridge excursions, bed turnaround |
| Traffic | morning (seed), trips per hour | a streaming map that loads around the camera; follow any vehicle; signals on every approach; delay, stops, speed and the worst junctions per rule set |

Every module has an **About** panel with the same information, and a **Compare** tab that
puts its rule sets side by side for the whole day.

## Screenshots

**Office tower** — ground floor, the basement car park, attendance and the energy comparison.

![Office ground floor](docs/screenshots/03-office-ground-floor.png)
![Office basement car park](docs/screenshots/04-office-basement-car-park.png)
![Office attendance](docs/screenshots/05-office-attendance.png)
![Office comparison](docs/screenshots/05b-office-compare.png)

**Home + GridSense** — the roof's panels and tank at midday, and the four controllers compared.

![Home roof with solar](docs/screenshots/06-home-roof-solar.png)
![Home controllers compared](docs/screenshots/07-home-controllers-compare.png)

**Hospital** — the emergency board, the ward's beds, the campus from OpenStreetMap, and Today vs Connected.

![Hospital emergency board](docs/screenshots/08-hospital-emergency-board.png)
![Hospital ward beds](docs/screenshots/09-hospital-ward-beds.png)
![Hospital campus](docs/screenshots/10-hospital-campus.png)
![Hospital comparison](docs/screenshots/11-hospital-compare.png)

**Lahore traffic** — the whole area, riding along with a motorcycle, a junction's signal phases, and fixed vs adaptive signals.

![Traffic map](docs/screenshots/12-traffic-map.png)
![Following a vehicle](docs/screenshots/13-traffic-follow-vehicle.png)
![Junction inspector](docs/screenshots/14-traffic-junction.png)
![Traffic comparison](docs/screenshots/15-traffic-compare.png)

**Run with your values** — typed inputs, and the hospital day they produced (150% arrivals, 4 ward nurses, no alarm delay).

![Run with your values](docs/screenshots/16-run-with-your-values.png)
![Your run's result](docs/screenshots/17-your-run-result.png)

**About panels and the light theme.**

![About panel](docs/screenshots/02-about-panel.png)
![Light theme](docs/screenshots/18-light-theme.png)

## Results

Office, one working day, same people under every rule set:

| | Fixed schedule | Motion | Motion + CO₂ |
|---|---|---|---|
| Lights + AC, kWh | 446.2 | 314.9 | 314.7 |
| Person-minutes in the dark | 34 | 10 | 5 |
| Lights switched off on someone | 5 | 27 | 16 |
| Room-minutes lit while empty | 16,432 | 4,694 | 4,576 |

Home, a June day of category IV load-shedding, same family and outages:

| | Inverter default | UPS circuit | GridSense eco | GridSense |
|---|---|---|---|---|
| House dark, min | 94 | 0 | 0 | 0 |
| Too hot to sleep, person-min | 514 | 792 | 792 | 533 |
| Day's bill, Rs | 348 | 542 | 357 | 465 |

Hospital, same patients and events:

| | Today | Connected |
|---|---|---|
| HDU alarms that sounded | 99 | 38 |
| Brief real events that never sounded (the cost of the 15 s delay) | 0 | 15 |
| Minutes searching for equipment | 96.4 | 0.9 |
| Drips run without a pump | 16 | 1 |
| Fridge minutes above 8 °C | 551 | 42 |
| Bed turnaround, median min | 70.4 | 20.4 |
| Hand hygiene: true / as reported, % | 36.3 / 62.5 | 36.5 / 36.1 |
| Door to doctor, median min | 16.7 | 18.0 |

Badges and sensors do not add doctors, so emergency waits barely move; a one-hour audit
reports hand hygiene at about twice its true rate, while counting dispensers reports it as it is.

Traffic, the same 7,078 trips in an hour of morning peak:

| | Fixed signals | Adaptive signals |
|---|---|---|
| Trips finished | 7,078 | 7,078 |
| Median delay, s | 54.3 | 19.5 |
| Stops per trip | 3.92 | 2.27 |
| Stopped at signals, vehicle-hours | 68.0 | 13.9 |
| Mean speed, km/h | 33.7 | 37.0 |

The simulated peak is probably faster than Lahore's real one: on-street parking, pedestrians
crossing and lane indiscipline are not modelled, and the only published network figure found
(JICA's master plan) is a daily average above 30 km/h, not a peak-hour speed.

Everything is simulated; rates and parameters that are assumptions are marked as such in the code.

## How it works

- **Engine** (`lahore_twin/`): a 1-second simulation per module on an MQTT-style bus in which
  every message carries its cause, so the viewer can answer "why did this happen".
- **Buildings**: rooms, doors and named spots as data (`plans/*.json`); floors are connected by
  stairs, lifts and ramps that cost their real climb; A* routes people through doors only.
- **Map data**: OpenStreetMap — the hospital campus outline and buildings, and the road network
  with lanes, one-way streets and bridge/tunnel layers.
- **Traffic**: Intelligent Driver Model following, lane changes when another lane is clearly
  better, priority to the bigger road, fixed or adaptive signals, left-hand driving.
- **Viewer** (`viewer/`): one offline page per module inside a single app shell; each replays
  the simulator's recording and re-simulates nothing. `serve.py` runs new days with your values.
- **Hardware path**: `mqtt.py` bridges the bus to a real broker; `solar_assistant.py` maps a
  SolarAssistant inverter box onto the home's topics.

## Data and licence

Map data © OpenStreetMap contributors, ODbL 1.0. Code: MIT (see `LICENSE`).
