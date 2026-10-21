# Lahore Twin

IoT systems for a city like Lahore, simulated end to end in one app: an office tower,
a home on solar during load-shedding, a hospital, and the city's traffic on real roads.
Every device — badge readers, motion and CO₂ sensors, inverters, bedside monitors, fridge
probes, traffic signals — sits behind an MQTT-style topic, so a real sensor can replace a
simulated one without changing the rules.

![Overview: every module with its headline numbers](docs/screenshots/01-overview.png)

**Demo video (51 s):** [lahore-twin-demo.mp4](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-demo.mp4)

| Module | What it simulates | Headline result | Status |
|---|---|---|---|
| **Office tower** | 3 floors (basement car park, ground, first), about 50 people who also step out for lunch, the bank, a client or the school pick-up; couriers at reception; badge doors, office Wi-Fi, lights, AC, CO₂ | motion + CO₂ uses **31% less** light and AC energy than a fixed timetable; badges + Wi-Fi keep the evacuation roll-call within **0.3** people on average (badges alone: 2.0) | ready |
| **Home + GridSense** | double-storey house with roof solar (6 kWp), 10 kWh battery, a day of load-shedding; a family whose children take the school van, go to tuition, and whose relatives visit in the evening; a gate counter | GridSense keeps the house lit through every cut (**93 → 0** dark minutes); its eco setting costs about the same as the inverter default | ready |
| **Hospital** | Lahore General Hospital campus from OpenStreetMap; Emergency Department (2 floors) and a 36-bed ward on floor 2; patients' attendants and visitors | alarms nurses walk to **99 → 38**, equipment search **96 → 1 min**, bed turnaround **70 → 20 min** | ready |
| **Lahore traffic** | Gulberg, Kalma Chowk, Garden Town, Canal Road from OpenStreetMap: flyovers, underpasses, one-way streets, lanes, 59 signals on a 60 s / 30 s plan; 7,097 trips in the evening peak with 1,763 stops at 432 real shops and amenities | adaptive signals cut median delay **105 → 60 s** and time stopped at signals **90 → 21** vehicle-hours | ready |
| **Junction planner** | the evening's three worst junctions under five fixes (retime, adaptive, U-turn conversion, underpass), and ten Rescue 1122 calls from the real station | at Firozpur Road / Wahdat Road time lost falls **28.8 → 6.9–9.6** vehicle-hours; a green wave gets the ambulance to the call **11% sooner** (4:27 → 3:58) | ready |
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
| Junction planner | day (seed), trips per hour; then pick a junction, a fix, a call and a way on the page | a close map of each junction with the fix drawn; time lost, queue, delay, extra km and pedestrian cost per fix; the ambulance on its route with a time–distance diagram |
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
![Visiting hour on the ward](docs/screenshots/09b-hospital-visiting-hour.png)
![Hospital campus](docs/screenshots/10-hospital-campus.png)
![Hospital comparison](docs/screenshots/11-hospital-compare.png)

**Lahore traffic** — the whole area, riding along with a motorcycle to the shop it parks at, the busiest places, a junction's signal phases with their countdowns, and fixed vs adaptive signals.

![Traffic map](docs/screenshots/12-traffic-map.png)
![Following a vehicle](docs/screenshots/13-traffic-follow-vehicle.png)
![Busiest places](docs/screenshots/13b-traffic-places.png)
![Junction inspector](docs/screenshots/14-traffic-junction.png)
![Traffic comparison](docs/screenshots/15-traffic-compare.png)

**Junction planner** — a U-turn conversion drawn on the real roads, and an ambulance on a green wave with its time–distance diagram.

![Junction planner](docs/screenshots/15b-junction-planner.png)
![Ambulance green wave](docs/screenshots/15c-ambulance-green-wave.png)

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
| Relatives standing in the ED bays, mean | 11.9 | 6.1 |
| Ward visitor-minutes outside 16:00–18:00 | 3,010 | 19 |
| Most visitors at one bed | 4 | 2 |
| Families turned away after 18:00 (the cost of the pass desk) | 0 | 18 |

Nobody comes alone: 319 relatives came with the day's emergency patients, one stays each
night on the ward and goes down to the pharmacy for the medicines. One attendant card per
patient halves the relatives in the bays; the pass desk ends visiting outside hours but packs
the ward at 16:00 (32 visitors at once against 12) and turns late families away.

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

Junction planner, 30 minutes of the same evening (3,617 trips), every fix on the same trips.
Firozpur Road / Wahdat Road, vehicle-hours lost within 350 m:

| As today | Retime (Webster) | Adaptive | U-turn conversion | Underpass |
|---|---|---|---|---|
| 28.8 | 9.6 | 9.2 | **6.9** (+333 km driven, no pedestrian crossing) | 9.5 |

Retiming alone gives Wahdat Road the long green, because Firozpur Road's through traffic rides
the flyover above; the U-turn conversion does best at the junction but sends 759 trips 150–400 m
on to turn back through a gap in the median. At Ahmed Munir Shaheed Road no fix helps much
(16.0 → 12.8 at best).

Rescue 1122, ten calls in the half hour from the station on OpenStreetMap, ten minutes at each,
then to the nearest hospital with an emergency department:

| | No priority | Siren | Green wave |
|---|---|---|---|
| To the call, mean | 4:27 | 4:16 | **3:58** |
| On to hospital, mean (9 calls every way finished) | 2:23 | 2:17 | 2:09 |
| Red lights met | 10 | 11 | 0 |

Field studies of signal preemption report 14–23% shorter emergency trips; this is 11% (9–11% over three
evenings, seeds 7, 11 and 23). The calls
are short (1.5–8 km, one to four signals), so there is less to gain than on a long corridor.

## How it works, animated

Two isometric animations for every module and for every tool inside it, 38 in all, generated
from the committed replays by `tools/isometric.py` and `tools/isometric_tools.py`. Each one has a
video:

- **Overview**: the stages an input passes through, each with the code that does it.
- **Architecture**: the module or tool as layers of real components, with one real piece of data
  hopping between them, shown exactly as it was recorded. That is the bus message with its
  id, topic, payload and cause, the patient record, the vehicle's trip and the signal's
  phase log. Each tool follows its own data, so no two show the same path.

| Module / tool | Overview | Architecture |
|---|---|---|
| **The app**: from a typed value to a fresh simulation | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-app.mp4) · [page](docs/isometric/app.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-app-arch.mp4) · [page](docs/isometric/app-arch.html) |
| **Office tower** | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-office.mp4) · [page](docs/isometric/office.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-office-arch.mp4) · [page](docs/isometric/office-arch.html) |
| · lights & AC | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-office-lights.mp4) · [page](docs/isometric/office-lights.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-office-lights-arch.mp4) · [page](docs/isometric/office-lights-arch.html) |
| · attendance & roll-call | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-office-attendance.mp4) · [page](docs/isometric/office-attendance.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-office-attendance-arch.mp4) · [page](docs/isometric/office-attendance-arch.html) |
| **Home + GridSense** | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-home.mp4) · [page](docs/isometric/home.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-home-arch.mp4) · [page](docs/isometric/home-arch.html) |
| · GridSense | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-home-gridsense.mp4) · [page](docs/isometric/home-gridsense.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-home-gridsense-arch.mp4) · [page](docs/isometric/home-gridsense-arch.html) |
| · who's home | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-home-people.mp4) · [page](docs/isometric/home-people.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-home-people-arch.mp4) · [page](docs/isometric/home-people-arch.html) |
| **Hospital** | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-hospital.mp4) · [page](docs/isometric/hospital.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-hospital-arch.mp4) · [page](docs/isometric/hospital-arch.html) |
| · emergency department | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-hospital-ed.mp4) · [page](docs/isometric/hospital-ed.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-hospital-ed-arch.mp4) · [page](docs/isometric/hospital-ed-arch.html) |
| · ward alarms & calls | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-hospital-alarms.mp4) · [page](docs/isometric/hospital-alarms.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-hospital-alarms-arch.mp4) · [page](docs/isometric/hospital-alarms-arch.html) |
| · equipment locator | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-hospital-equipment.mp4) · [page](docs/isometric/hospital-equipment.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-hospital-equipment-arch.mp4) · [page](docs/isometric/hospital-equipment-arch.html) |
| · families & passes | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-hospital-families.mp4) · [page](docs/isometric/hospital-families.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-hospital-families-arch.mp4) · [page](docs/isometric/hospital-families-arch.html) |
| **Lahore traffic** | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-traffic.mp4) · [page](docs/isometric/traffic.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-traffic-arch.mp4) · [page](docs/isometric/traffic-arch.html) |
| · trips & shops | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-traffic-trips.mp4) · [page](docs/isometric/traffic-trips.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-traffic-trips-arch.mp4) · [page](docs/isometric/traffic-trips-arch.html) |
| · signals | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-traffic-signals.mp4) · [page](docs/isometric/traffic-signals.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-traffic-signals-arch.mp4) · [page](docs/isometric/traffic-signals-arch.html) |
| · the streaming map | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-traffic-map.mp4) · [page](docs/isometric/traffic-map.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-traffic-map-arch.mp4) · [page](docs/isometric/traffic-map-arch.html) |
| **Junction planner** | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-junctions.mp4) · [page](docs/isometric/junctions.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-junctions-arch.mp4) · [page](docs/isometric/junctions-arch.html) |
| · junction fixes | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-junctions-fixes.mp4) · [page](docs/isometric/junctions-fixes.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-junctions-fixes-arch.mp4) · [page](docs/isometric/junctions-fixes-arch.html) |
| · ambulance green wave | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-junctions-ambulance.mp4) · [page](docs/isometric/junctions-ambulance.html) | [video](https://github.com/hammasbuilds/lahore-twin/releases/download/v0.4.0/lahore-twin-junctions-ambulance-arch.mp4) · [page](docs/isometric/junctions-ambulance-arch.html) |

![Office architecture, hop by hop](docs/isometric/office-arch.png)

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
