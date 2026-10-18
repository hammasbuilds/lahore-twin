"""The home simulation: 24 hours, one second per tick, physics every ten.

People live their day and *want* things (a fan, the AC, the lights, the TV, a
cycle of laundry). Wants go on the bus; a controller answers with commands; the
inverter decides what actually gets power. The simulator alone knows the truth
and measures it: who sat in the heat, who lost the fan, when the tank ran dry,
what came from the grid at peak price.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field

from .bus import Bus, Message
from .climate import Season, hm
from .devices import RoomEnv
from .gridsense import CONTROLLERS, ESSENTIAL
from .home import DAY, HomeScenario
from .people import ROLE_COLOURS, Person
from .plan import path_length
from .power import APPLIANCES, Inverter, RoofTank

PHYS_DT = 10
SAMPLE_DT = 60
AC_THERMAL_W = 5300.0     # 1.5 ton
AC_COP = 3.2
HOME_SETPOINT = 26.0
FAN_RELIEF = 2.0          # a ceiling fan feels about 2 °C cooler
HOT_SLEEP = 30.0          # effective temperature above which sleep suffers
HOT_AWAKE = 32.0

# tariff assumptions (Rs/kWh), stated: NEPRA residential slabs vary; these are round figures
TARIFF = {"offpeak": 42.0, "peak": 50.0, "export": 11.0}

HOME_COLOURS = {"father": "#60a5fa", "mother": "#f472b6", "grandmother": "#c084fc",
                "school": "#fbbf24", "student": "#34d399", "helper": "#2dd4bf"}


@dataclass
class Appliance:
    id: str
    kind: str
    room: str
    watts: float
    essential: bool


def appliances_for(plan) -> list[Appliance]:
    out = []
    for r in plan.rooms.values():
        if r.kind == "outdoor":
            continue
        out.append(Appliance(f"light:{r.id}", "light", r.id, APPLIANCES["light"][0], True))
    for rid in plan.raw.get("fan_rooms", []):
        out.append(Appliance(f"fan:{rid}", "fan", rid, APPLIANCES["fan"][0], True))
    for rid in plan.ac_rooms:
        out.append(Appliance(f"ac:{rid}", "ac", rid, APPLIANCES["ac"][0], False))
    extra = [("fridge", "kitchen"), ("router", "lounge"), ("tv", "lounge"), ("pump", "yard"),
             ("washer", "yard"), ("iron", "spine"), ("microwave", "kitchen")]
    for kind, rid in extra:
        w, ess, _ = APPLIANCES[kind]
        out.append(Appliance(kind, kind, rid, w, ess))
    return out


def run_day(sc: HomeScenario, mode: str) -> "HomeSim":
    """Simulate the day after a warm-up run of the same day, so each controller starts at
    00:00 with the battery it left the night before rather than a level nobody chose."""
    warm = HomeSim(sc, mode).run()
    return HomeSim(sc, mode, soc_start=warm.inverter.battery.soc).run()


class HomeSim:
    def __init__(self, sc: HomeScenario, mode: str, soc_start: float | None = None):
        self.sc, self.plan, self.season, self.mode = sc, sc.plan, sc.season, mode
        self.rng_people = random.Random(sc.seed * 1000 + 11)
        self.people: list[Person] = copy.deepcopy(sc.people)
        self.by_id = {p.id: p for p in self.people}
        for p in self.people:
            p.pos = p.entry
            p.room = self.plan.room_at(*p.pos)
            p.on_site = p.arrive == 0
        # telemetry is matched on the last topic segment (home/pv/kw -> "kw"); kept only when it causes something
        self.bus = Bus(quiet=("voltage", "soc", "kw", "level", "temp", "load", "presence"))
        self.apps = {a.id: a for a in appliances_for(self.plan)}
        self.inverter = Inverter()
        if soc_start is not None:
            self.inverter.battery.soc = soc_start
        self.tank = RoofTank()
        self.env = {}
        for rid, r in self.plan.rooms.items():
            if r.kind == "outdoor":
                continue
            e = RoomEnv(rid, r.kind, r.area, rid in self.plan.ac_rooms, temp=31.5 if sc.season.t_max > 36 else 26.0,
                        climate=sc.season, setpoint=HOME_SETPOINT, mass_scale=2.0,
                        ac_capacity_w=AC_THERMAL_W if rid in self.plan.ac_rooms else 0.0)
            self.env[rid] = e
        self.ctrl = CONTROLLERS[mode](self.bus, sc, self.inverter, self.apps)
        self.cmd: dict[str, bool] = {a: False for a in self.apps}
        self.cmd["fridge"] = self.cmd["router"] = True
        self.bus.subscribe("home/+/+", self._on_cmd)
        self.wants: dict[str, bool] = {a: False for a in self.apps}
        self.jobs: dict[str, dict] = {}              # appliance -> {request, left}
        self.pending_requests = sorted(sc.requests, key=lambda r: r.t)
        self.water = list(sc.water)
        self.water_short_l = 0.0
        self.grid_was = None
        self.presence: dict[str, int] = {}
        self.ac_w: dict[str, float] = {rid: 0.0 for rid in self.plan.ac_rooms}
        self.trips: list[list] = []
        self.dev_changes: list[list] = []
        self.trips_log: list[dict] = []
        self.labels: list[list] = []
        self.served: set[str] = set()
        self.last_result = None
        self.house_kw = 0.0
        self.meter_kw = 0.0
        self.acc = {"pv_kwh": 0.0, "pv_used_kwh": 0.0, "curtailed_kwh": 0.0, "grid_peak_kwh": 0.0,
                    "grid_offpeak_kwh": 0.0,
                    "export_kwh": 0.0, "load_kwh": 0.0, "dark_s": 0, "no_fan_ps": 0, "hot_sleep_ps": 0,
                    "hot_awake_ps": 0, "lowv_stress_s": 0}
        self.soc_start = self.inverter.battery.soc
        self.series = {"t": [], "pv_kw": [], "load_kw": [], "grid_kw": [], "batt_kw": [], "soc": [],
                       "curtailed_kw": [], "dark_reason": [],
                       "tank": [], "volts": [], "grid_up": [], "out_temp": [], "dark": [],
                       "temp": {r: [] for r in self.env}, "occ": {r: [] for r in self.env}}

    # ---- bus ------------------------------------------------------------

    def _on_cmd(self, m: Message) -> None:
        parts = m.topic.split("/")
        if len(parts) != 3 or parts[2] in ("want", "presence", "request", "done"):
            return
        aid = parts[2] if parts[2] in self.apps else f"{parts[2]}:{parts[1]}"
        if aid in self.apps and isinstance(m.payload, bool):
            if self.cmd.get(aid) != m.payload:
                self.cmd[aid] = m.payload
                self.dev_changes.append([m.t, aid, int(m.payload), m.id])

    def _want(self, aid: str, on: bool, t: int) -> None:
        if self.wants.get(aid) == on:
            return
        self.wants[aid] = on
        a = self.apps[aid]
        self.bus.publish(f"home/{a.room}/{a.kind}/want", on, None,
                         f"{'Wants' if on else 'No longer wants'} the {a.kind} in {self.plan.rooms[a.room].name}")

    # ---- people ---------------------------------------------------------

    def _label(self, p: Person, t: int, label: str) -> None:
        if p.label != label:
            p.label = label
            self.labels.append([t, p.id, label])

    def _step_person(self, p: Person, t: int) -> None:
        if p.gone:
            return
        if not p.on_site:
            # someone who went out stays out until their next stay brings them back through
            # the street (_off_site_return); without this they "arrived" again at their bed
            if getattr(p, "away", False) or t < p.arrive:
                return
            p.on_site = True
            p.pos = p.entry
            p.room = self.plan.room_at(*p.pos)
        while p.idx + 1 < len(p.day) and p.day[p.idx + 1].t <= t:
            p.idx += 1
            s = p.day[p.idx]
            spot = s.spot
            if s.pool:
                taken = {tuple(q.target) for q in self.people if q is not p and getattr(q, "target", None)}
                free = [tuple(x) for x in self.plan.spots[s.pool] if tuple(x) not in taken]
                spot = self.rng_people.choice(free) if free else s.spot
            p.target = spot
            p.leaving = s.kind == "leave" or s.label == "Out"
            self._label(p, t, s.label)
            pts = self.plan.route(p.pos, spot)
            if len(pts) >= 2 and path_length(pts) > 0.05:
                p.set_path(pts)
                self.trips_log.append({"p": p.id, "t": t, "v": round(p.speed, 3),
                                       "pts": [[round(x, 2), round(y, 2)] for x, y in pts]})
            else:
                p.path = []
                p.pos = spot
        if p.path:
            done = p.advance(1.0)
            room = self.plan.room_at(*p.pos)
            if room:
                p.room = room
            if done and getattr(p, "leaving", False):
                p.on_site = False
                p.away = True
                if p.day[p.idx].kind == "leave":
                    p.gone = True
                p.room = None
        elif not p.on_site:
            return

    def _off_site_return(self, p: Person, t: int) -> None:
        # someone "Out" comes back when their next stay begins: re-enter from the street
        if getattr(p, "away", False) and not p.gone and p.idx + 1 < len(p.day) and p.day[p.idx + 1].t <= t:
            p.away = False
            p.on_site = True
            p.pos = self.plan.spots["street"][0]
            p.room = self.plan.room_at(*p.pos)

    # ---- wants: what the people in each room would switch on -------------

    def _update_wants(self, t: int) -> None:
        occ: dict[str, list[Person]] = {}
        for p in self.people:
            if p.on_site and p.room and p.room in self.env:
                occ.setdefault(p.room, []).append(p)
        for rid in self.env:
            n = len(occ.get(rid, []))
            if self.presence.get(rid, 0) != n:
                self.presence[rid] = n
                self.bus.publish(f"home/{rid}/presence", n)
        dark_out = not (self.season.sunrise + 1800 < t % DAY < self.season.sunset - 1800)
        for aid, a in self.apps.items():
            people = occ.get(a.room, [])
            asleep = [p for p in people if p.label in ("Asleep", "Afternoon nap")]
            awake = [p for p in people if p not in asleep]
            temp = self.env[a.room].temp if a.room in self.env else 30
            # wants have hysteresis, like the people holding the remote: switched on when it
            # gets hot, left on until the room is clearly cool or they leave
            on = self.wants.get(aid, False)
            if a.kind == "fan":
                self._want(aid, bool(people) and (temp > 25.0 if not on else temp > 23.0), t)
            elif a.kind == "light":
                interior = self.plan.rooms[a.room].kind in ("corridor", "bath", "store", "kitchen")
                self._want(aid, bool(awake) and (dark_out or interior), t)
            elif a.kind == "ac":
                lounge_hours = hm("13:00") <= t % DAY < hm("23:30")
                in_use = bool(asleep) or (a.room == "lounge" and lounge_hours and bool(people))
                self._want(aid, in_use and (temp > 28.0 if not on else temp > 22.0), t)
            elif a.kind == "tv":
                self._want(aid, any(p.label == "TV" for p in people), t)
        self._want("microwave", any(mt <= t % DAY < mt + dur for mt, dur in self.sc.meals), t)
        while self.pending_requests and self.pending_requests[0].t <= t:
            r = self.pending_requests.pop(0)
            self.jobs[r.appliance] = {"request": r, "left": r.duration, "done": None}
            self.bus.publish(f"home/{r.room}/{r.appliance}/request",
                             {"id": r.id, "duration": r.duration, "deadline": r.deadline}, None,
                             f"{r.label}: {r.duration // 60} min of {r.appliance}, needed by "
                             f"{r.deadline // 3600:02d}:{r.deadline % 3600 // 60:02d}")

    # ---- physics --------------------------------------------------------

    def _demand(self, t: int) -> dict[str, float]:
        d = {}
        for aid, on in self.cmd.items():
            if not on:
                continue
            a = self.apps[aid]
            if a.kind in ("fan", "light", "tv", "microwave", "router"):
                if a.kind in ("microwave",) and not self.wants.get(aid):
                    continue
                if a.kind in ("fan", "light", "tv") and not self.wants.get(aid):
                    continue
                d[aid] = a.watts / 1000
            elif a.kind == "fridge":
                if (t // 60) % 30 < 12:          # compressor ~40% duty
                    d[aid] = a.watts / 1000
            elif a.kind == "ac":
                if self.wants.get(aid) or self.ctrl.precooling(a.room, t):
                    d[aid] = max(0.45, self.ac_w.get(a.room, 0.0) / 1000) if self.env[a.room].temp > 23.6 else 0.15
            elif a.kind == "pump":
                if self.tank.level_l < self.tank.capacity_l - 1:
                    d[aid] = a.watts / 1000
            elif a.kind in ("washer", "iron"):
                job = self.jobs.get(aid)
                if job and job["left"] > 0:
                    d[aid] = a.watts / 1000
        return d

    def _physics(self, t: int) -> None:
        sc = self.sc
        grid = sc.grid_up(t)
        volts = sc.voltage(t) if grid else 0.0
        kwp = 6.0
        pv = kwp * sc.season.pv_kwh_per_kwp / sc.season.shape_integral_hours() * sc.season.clear_sky_shape(t) \
            * sc.cloud_factor(t)
        demand = self._demand(t)
        r = self.inverter.step(t, PHYS_DT, demand, self.ctrl.on_inverter, grid, pv)
        self.last_result = r
        prev = self.served
        self.served = r.served
        # rooms
        occ = {}
        for p in self.people:
            if p.on_site and p.room in self.env:
                occ[p.room] = occ.get(p.room, 0) + 1
        for rid, env in self.env.items():
            env.setpoint = self.ctrl.setpoint(rid, t)
            lit = f"light:{rid}" in r.served
            ac_on = f"ac:{rid}" in r.served
            electric_at_office_cop = env.step(PHYS_DT, t, occ.get(rid, 0), lit, ac_on)
            if rid in self.ac_w:
                # RoomEnv reports electrical watts at the office COP (3.0); a split unit runs at AC_COP
                self.ac_w[rid] = electric_at_office_cop * 3.0 / AC_COP
        # water
        use = 0.0
        while self.water and self.water[0][0] <= t:
            use += self.water.pop(0)[1]
        supplied = self.tank.step(PHYS_DT, use, "pump" in r.served)
        self.water_short_l += use - supplied
        # jobs
        for aid, job in self.jobs.items():
            if job["left"] > 0 and aid in r.served:
                job["left"] -= PHYS_DT
                if job["left"] <= 0:
                    job["done"] = t
                    req = job["request"]
                    self.bus.publish(f"home/{req.room}/{aid}/done", req.id, None,
                                     f"{req.label} finished at {t // 3600:02d}:{t % 3600 // 60:02d}"
                                     + (" — LATE" if t > req.deadline else ""))
        # energy accounting, at the meter: grid-only loads are fed first by solar the inverter
        # pushes out, then by the grid; only what is left over leaves the house as export
        h = PHYS_DT / 3600
        grid_only_kw = sum(demand[a] for a in r.served if a not in self.ctrl.on_inverter)
        meter_kw = grid_only_kw + r.grid_in_kw - r.pv_out_kw
        imp, exp = max(0.0, meter_kw), max(0.0, -meter_kw)
        self.house_kw = r.load_kw + grid_only_kw
        self.meter_kw = meter_kw
        self.acc["pv_kwh"] += pv * h
        self.acc["curtailed_kwh"] += r.curtailed_kw * h
        self.acc["pv_used_kwh"] += (pv - exp - r.curtailed_kw) * h    # used at home, behind the meter
        self.acc["load_kwh"] += self.house_kw * h
        self.acc["grid_peak_kwh" if self.season.is_peak(t) else "grid_offpeak_kwh"] += imp * h
        self.acc["export_kwh"] += exp * h
        if not grid and r.dark:
            self.acc["dark_s"] += PHYS_DT
        for p in self.people:
            if not (p.on_site and p.room in self.env):
                continue
            fan = f"fan:{p.room}"
            fan_on = fan in r.served
            if self.wants.get(fan) and not fan_on:
                self.acc["no_fan_ps"] += PHYS_DT
            eff = self.env[p.room].temp - (FAN_RELIEF if fan_on else 0.0)
            asleep = p.label in ("Asleep", "Afternoon nap")
            if asleep and eff > HOT_SLEEP:
                self.acc["hot_sleep_ps"] += PHYS_DT
            elif not asleep and eff > HOT_AWAKE:
                self.acc["hot_awake_ps"] += PHYS_DT
        if grid and volts < 190 and any(a in r.served for a in ("fridge",) + tuple(f"ac:{x}" for x in self.plan.ac_rooms)):
            self.acc["lowv_stress_s"] += PHYS_DT
        # sensors for the controller
        if grid != self.grid_was:
            self.grid_was = grid
            self.bus.publish("home/grid/state", grid, None, "Grid is back" if grid else "Power cut — grid is down")
        if r.tripped and (not self.trips or t - self.trips[-1][0] > 60):
            asked = sum(demand.get(a, 0) for a in demand if a in self.ctrl.on_inverter)
            cap = self.inverter.capacity_kw(grid, pv)
            self.trips.append([t, asked])
            self.bus.publish("home/alert/overload", round(asked, 2), None,
                             f"Inverter overloaded: {asked:.1f} kW asked, it can carry {cap:.1f} kW"
                             + ("" if grid else " (battery limit + sun)") + " — output off for a minute")
        if not prev.issubset(r.served) and r.dark and not getattr(self, "_dark_said", False):
            self._dark_said = True
            why = (f"battery at {self.inverter.battery.soc * 100:.0f}%, its cut-off" if r.dark_reason == "cutoff"
                   else "inverter overloaded")
            self.bus.publish("home/alert/dark", self.inverter.battery.soc, None, f"House dark: {why}")
        if not r.dark:
            self._dark_said = False
        self._volts = volts
        self._pv = pv

    def _report(self, t: int) -> None:
        r = self.last_result
        b = self.inverter.battery
        self.bus.publish("home/battery/soc", round(b.soc, 4))
        self.bus.publish("home/pv/kw", round(self._pv, 3))
        self.bus.publish("home/tank/level", round(self.tank.fraction, 3))
        self.bus.publish("home/grid/voltage", round(self._volts, 1))
        self.bus.publish("home/house/load", round(self.house_kw, 3))
        for rid, env in self.env.items():
            self.bus.publish(f"home/{rid}/temp", round(env.temp, 2))
        s = self.series
        s["t"].append(t)
        s["pv_kw"].append(round(self._pv, 3))
        s["load_kw"].append(round(self.house_kw, 3))
        s["grid_kw"].append(round(self.meter_kw, 3))
        s["curtailed_kw"].append(round(r.curtailed_kw, 3))
        s["dark_reason"].append(r.dark_reason)
        s["batt_kw"].append(round(r.batt_kw, 3))
        s["soc"].append(round(b.soc, 4))
        s["tank"].append(round(self.tank.fraction, 3))
        s["volts"].append(round(self._volts, 1))
        s["grid_up"].append(int(self.sc.grid_up(t)))
        s["out_temp"].append(round(self.season.outdoor_temp(t), 2))
        s["dark"].append(int(r.dark))
        for rid, env in self.env.items():
            s["temp"][rid].append(round(env.temp, 2))
            s["occ"][rid].append(self.presence.get(rid, 0))

    def run(self) -> "HomeSim":
        for t in range(0, DAY):
            self.bus.now = t
            for p in self.people:
                self._off_site_return(p, t)
                self._step_person(p, t)
            if t % PHYS_DT == 0:
                self._update_wants(t)
                self.ctrl.tick(t)
                self._physics(t)
            if t % SAMPLE_DT == 0:
                self._report(t)
        self.bus.now = DAY - 1
        self.ctrl.finish(DAY - 1)
        return self

    # ---- results --------------------------------------------------------

    def metrics(self) -> dict:
        a = self.acc
        b = self.inverter.battery
        soc_delta_kwh = (b.soc - self.soc_start) * b.capacity_kwh
        bill = a["grid_peak_kwh"] * TARIFF["peak"] + a["grid_offpeak_kwh"] * TARIFF["offpeak"] \
            - a["export_kwh"] * TARIFF["export"]
        late = [j["request"].id for j in self.jobs.values() if (j["done"] or DAY) > j["request"].deadline]
        return {
            "mode": self.mode,
            "house_dark_min": round(a["dark_s"] / 60),
            "no_fan_person_min": round(a["no_fan_ps"] / 60),
            "hot_sleep_person_min": round(a["hot_sleep_ps"] / 60),
            "hot_awake_person_min": round(a["hot_awake_ps"] / 60),
            "tank_empty_min": round(self.tank.empty_s / 60),
            "water_short_l": round(self.water_short_l),
            "grid_peak_kwh": round(a["grid_peak_kwh"], 2),
            "grid_offpeak_kwh": round(a["grid_offpeak_kwh"], 2),
            "export_kwh": round(a["export_kwh"], 2),
            "pv_kwh": round(a["pv_kwh"], 2),
            # solar used at home (loads + battery), not counting what was exported or wasted
        "solar_used_pct": round(100 * a["pv_used_kwh"] / max(a["pv_kwh"], 1e-9), 1),
        "solar_wasted_kwh": round(a["curtailed_kwh"], 2),
            "battery_throughput_kwh": round(b.throughput_kwh, 2),
            "soc_end": round(b.soc, 3),
            # the day's bill, with the battery's end-of-day change valued at the off-peak rate,
            # so a controller cannot look cheap by leaving the battery flat
            "bill_rs": round(bill - soc_delta_kwh * TARIFF["offpeak"]),
            "overload_trips": len(self.trips),
            "low_voltage_stress_min": round(a["lowv_stress_s"] / 60),
            "jobs_late": late,
        }

    def replay(self) -> dict:
        return {
            "metrics": self.metrics(),
            "devices": self.dev_changes,
            "log": [{"id": m.id, "t": m.t, "topic": m.topic, "text": m.text, "cause": m.cause,
                     **({"payload": m.payload} if isinstance(m.payload, (int, float, str, bool)) else {})}
                    for m in self.bus.log],
            "series": self.series,
            "trips": self.trips,
        }
