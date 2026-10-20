# Lahore Twin

IoT systems for a city like Lahore, simulated end to end in one app: an office tower,
a home on solar during load-shedding, a hospital, and the city's traffic on real roads.
Every device — badge readers, motion and CO₂ sensors, inverters, bedside monitors, fridge
probes, traffic signals — sits behind an MQTT-style topic, so a real sensor can replace a
simulated one without changing the rules.

![Overview: every module with its headline numbers](docs/screenshots/01-overview.png)

**Demo video (50 s):** [lahore-twin-demo.mp4](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-demo.mp4)

| Module | What it simulates | Headline result | Status |
|---|---|---|---|
| **Office tower** | 3 floors (basement car park, ground, first), about 50 people who also step out for lunch, the bank, a client or the school pick-up; couriers at reception; badge doors, office Wi-Fi, lights, AC, CO₂ | motion + CO₂ uses **31% less** light and AC energy than a fixed timetable; badges + Wi-Fi keep the evacuation roll-call within **0.3** people on average (badges alone: 2.0) | ready |
| **Home + GridSense** | double-storey house with roof solar (6 kWp), 10 kWh battery, a day of load-shedding; a family whose children take the school van, go to tuition, and whose relatives visit in the evening; a gate counter | GridSense keeps the house lit through every cut (**93 → 0** dark minutes); its eco setting costs about the same as the inverter default | ready |
| **Hospital** | Lahore General Hospital campus from OpenStreetMap; Emergency Department (2 floors) and a 36-bed ward on floor 2 | alarms nurses walk to **99 → 38**, equipment search **96 → 1 min**, bed turnaround **70 → 20 min** | ready |
| **Lahore traffic** | Gulberg, Kalma Chowk, Garden Town, Canal Road from OpenStreetMap: flyovers, underpasses, one-way streets, lanes, 59 signals on a 60 s / 30 s plan; 7,097 trips in the evening peak with 1,763 stops at 432 real shops and amenities | adaptive signals cut median delay **105 → 60 s** and time stopped at signals **90 → 21** vehicle-hours | ready |
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
python tools/sweep_traffic.py # traffic invariants over 3 mornings x 3 demand levels (~10 min)
```

Python 3.10+, standard library only. No network: the map data ships in `plans/osm/`.

## What you can put in, what comes out

| Module | Inputs (Run with your values) | Outputs |
|---|---|---|
| Office | day (seed), staff with desks, visitors | floor-by-floor plan with people, lights, AC and cars; energy and comfort per rule set; attendance, tailgating, roll-call from badges and from badges + Wi-Fi |
| Home | day, season, load-shedding category, solar kWp, battery kWh | each floor and the roof with fans, ACs, tank and panels; power flow; dark minutes, comfort, bill; every controller decision with its reason |
| Hospital | day, emergency arrivals (%), ward nurses per shift, alarm delay (s) | site, ED and ward floors with patients by triage colour; ED board, bed board, equipment list; waits, call and alarm response, search time, fridge excursions, bed turnaround |
| Traffic | evening or morning peak, day (seed), trips per hour | a streaming map that loads around the camera; follow any vehicle and see why it is driving and where it stops; the busiest shops; signals with countdowns; delay, stops, speed and the worst junctions per rule set |

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
![Who is home](docs/screenshots/07b-home-who-is-home.png)

**Hospital** — the emergency board, the ward's beds, the campus from OpenStreetMap, and Today vs Connected.

![Hospital emergency board](docs/screenshots/08-hospital-emergency-board.png)
![Hospital ward beds](docs/screenshots/09-hospital-ward-beds.png)
![Hospital campus](docs/screenshots/10-hospital-campus.png)
![Hospital comparison](docs/screenshots/11-hospital-compare.png)

**Lahore traffic** — the whole area, riding along with a motorcycle to the shop it parks at, the busiest places, a junction's signal phases with their countdowns, and fixed vs adaptive signals.

![Traffic map](docs/screenshots/12-traffic-map.png)
![Following a vehicle](docs/screenshots/13-traffic-follow-vehicle.png)
![Busiest places](docs/screenshots/13b-traffic-places.png)
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
| Lights + AC, kWh | 446.2 | 310.3 | 308.4 |
| Person-minutes in the dark | 34 | 8 | 4 |
| Lights switched off on someone | 6 | 27 | 12 |
| Room-minutes lit while empty | 16,766 | 4,650 | 4,475 |

People step out and come back all day (lunch at a dhaba, the bank, the school pick-up) and
tap out of one floor's door, then walk in behind a colleague at the other. The evacuation
roll-call, 08:30–18:30, people off from the truth (mean / worst), on day 7:

| Door counters | Badge register | Register + tailgate alerts | Badges + phones on the Wi-Fi |
|---|---|---|---|
| 1.79 / 7 | 1.79 / 6 | 1.99 / 7 | **0.27 / 3** |

A phone on the Wi-Fi means its owner is still in the building whatever the doors last said;
over four days the Wi-Fi estimate stays at 0.2–0.4 people off, against 1.1–2.0 for badges alone.
11 of 17 tailgates were caught, with no false alarms.

Home, a June day of category IV load-shedding, same family and outages:

| | Inverter default | UPS circuit | GridSense eco | GridSense |
|---|---|---|---|---|
| House dark, min | 93 | 0 | 0 | 0 |
| Too hot to sleep, person-min | 396 | 675 | 675 | 416 |
| Day's bill, Rs | 379 | 548 | 385 | 492 |

That day the school van leaves at 07:20, the mother is at the market and pharmacy from 10:32
to 11:49, the children are at tuition from 16:45 to 18:35, and the father, out for groceries
at 19:31, is back at 19:53 because three relatives arrived at 19:48. The gate counter logged
24 crossings; the drawing-room fan and light came on with the guests and went off when they
left at 22:04.

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

Traffic, the same 7,097 trips in an hour of evening peak (17:30–18:30) plus 15 minutes to
clear. People drive home, to shop, to the mall, for takeaway, to the pharmacy, the bank, fuel,
prayers and tuition pick-ups, at real places from OpenStreetMap; short stops block the kerb
lane, long ones pull off to park, rickshaws and wagons stop for passengers. Signals run 60 s
green for the bigger road and 30 s for the side road. Drivers pick routes on free-flow time plus
each approach's expected wait at red, so the flyovers and underpasses carry real loads (Kalma
Chowk Flyover 1,273 trips, Model Town Underpass 605):

| | Fixed signals | Adaptive signals |
|---|---|---|
| Trips finished | 6,589 | 6,820 |
| Median delay, s (time at the shop not counted) | 104.9 | 60.3 |
| Stops per trip | 7.5 | 5.6 |
| Stopped at signals, vehicle-hours | 89.8 | 20.7 |
| Mean speed, km/h | 28.8 | 32.3 |
| Stops at shops and amenities | 1,763 | 1,805 |
| Still on the road 15 min after the peak | 508 | 277 |

Over three other days, in both peaks, at 4,000, 8,000 and 12,000 trips an hour
(`tools/sweep_traffic.py`, 36 runs): nobody exceeds the road's or the vehicle's speed, no
parked car moves, and adaptive signals beat fixed ones every time. Up to 8,000 trips an hour
nobody is gridlocked and everyone gets onto the map; median delay falls from 62–72 s to
18–23 s at 4,000 and from 94–107 s to 51–64 s at 8,000. At 12,000 the area is past
saturation: the fixed plan gridlocks in 4 of 6 runs (21–336 vehicles still for five minutes
or more, in one-lane queues on North Avenue reaching back from a red light), adaptive signals
in none; some cars cannot enter the map under either (up to 36).

Kerb stops and rickshaws picking up passengers now slow the kerb lane, as on-street stopping
does in Lahore; pedestrians crossing and lane indiscipline are still not modelled, so the
simulated peak may run faster than the real one. The only published network figure found
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
  better, priority to the bigger road, fixed or adaptive signals, left-hand driving; trips with
  purposes and stops at real places (kerb stops and off-road parking).
- **Viewer** (`viewer/`): one offline page per module inside a single app shell; each replays
  the simulator's recording and re-simulates nothing. `serve.py` runs new days with your values.
- **Hardware path**: `mqtt.py` bridges the bus to a real broker; `solar_assistant.py` maps a
  SolarAssistant inverter box onto the home's topics.

## Data and licence

Map data, shops and amenities © OpenStreetMap contributors, ODbL 1.0. Code: MIT (see `LICENSE`).
