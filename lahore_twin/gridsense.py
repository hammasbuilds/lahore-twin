"""Controllers for the house: two common setups and GridSense.

All three see the same things a real controller could: the bus (wants from
switches and remotes, presence sensors, grid state, voltage, battery SOC, solar
power, tank level, room temperatures) plus the published load-shedding schedule
and a day-ahead solar forecast. None sees unannounced cuts coming.

* ``default``  — every circuit on the inverter, fixed SBU settings, everything
                 runs when someone wants it, the pump on its float switch.
* ``ups``      — the common Lahore wiring: only fans, lights, fridge, router and
                 TV on the inverter; ACs, pump, washer, iron and microwave die in
                 an outage.
* ``gridsense``— plans around the published schedule: keeps a battery reserve
                 sized for the next outage, pre-cools, fills the tank first,
                 moves laundry and ironing into good hours, spends the battery in
                 the peak-tariff window, rations the ACs during an outage, and
                 protects the AC and fridge from low voltage.
"""

from __future__ import annotations

from .bus import Bus, Message
from .climate import hm
from .home import DAY
from .power import Inverter, InverterSettings

ESSENTIAL = ("fan", "light", "fridge", "router")
LOW_V, OK_V, OK_V_HOLD = 190.0, 200.0, 120


def _clock(t: int) -> str:
    t = int(t) % DAY
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}"


class Base:
    name = "base"

    def __init__(self, bus: Bus, sc, inverter: Inverter, apps: dict):
        self.bus, self.sc, self.inv, self.apps = bus, sc, inverter, apps
        self.on_inverter = set(apps)
        self.state: dict[str, bool] = {a: False for a in apps}
        self.wants: dict[str, bool] = {a: False for a in apps}
        self.want_msg: dict[str, int] = {}
        self.jobs: dict[str, dict] = {}
        self.grid = True
        self.grid_msg = None
        self.soc = inverter.battery.soc
        self.pv = 0.0
        self.load = 0.0
        self.load_t = None
        self.tank = 0.6
        self.tank_msg = None
        self.volts = 230.0
        self.volts_msg = None
        self.presence: dict[str, int] = {}
        self.temps: dict[str, float] = {}
        self.settings_sent = None
        bus.subscribe("home/+/+/want", self._on_want)
        bus.subscribe("home/+/+/request", self._on_request)
        bus.subscribe("home/+/+/done", self._on_done)
        bus.subscribe("home/grid/state", self._on_grid)
        bus.subscribe("home/battery/soc", lambda m: setattr(self, "soc", m.payload))
        bus.subscribe("home/pv/kw", lambda m: setattr(self, "pv", m.payload))
        bus.subscribe("home/house/load", self._on_load)
        bus.subscribe("home/tank/level", self._on_tank)
        bus.subscribe("home/grid/voltage", self._on_volts)
        bus.subscribe("home/+/presence", lambda m: self.presence.__setitem__(m.topic.split("/")[1], m.payload))
        bus.subscribe("home/+/temp", lambda m: self.temps.__setitem__(m.topic.split("/")[1], m.payload))
        self.command("fridge", True, None, "always on")
        self.command("router", True, None, "always on")

    # ---- inputs ----------------------------------------------------------

    def _aid(self, room: str, kind: str) -> str:
        return kind if kind in self.apps else f"{kind}:{room}"

    def _on_want(self, m: Message) -> None:
        _, room, kind, _ = m.topic.split("/")
        aid = self._aid(room, kind)
        self.wants[aid] = bool(m.payload)
        self.want_msg[aid] = m.id

    def _on_request(self, m: Message) -> None:
        _, room, kind, _ = m.topic.split("/")
        self.jobs[kind] = {"room": room, "duration": m.payload["duration"], "left": m.payload["duration"],
                           "deadline": m.payload["deadline"], "msg": m.id, "started": None, "done": False}

    def _on_done(self, m: Message) -> None:
        kind = m.topic.split("/")[2]
        if kind in self.jobs:
            self.jobs[kind]["done"] = True
            self.command(kind, False, m.id, "job finished")

    def _on_grid(self, m: Message) -> None:
        self.grid, self.grid_msg = bool(m.payload), m.id

    def _on_load(self, m: Message) -> None:
        self.load, self.load_t = m.payload, m.t

    def _on_tank(self, m: Message) -> None:
        self.tank, self.tank_msg = m.payload, m.id

    def _on_volts(self, m: Message) -> None:
        self.volts, self.volts_msg = m.payload, m.id

    # ---- outputs ---------------------------------------------------------

    def command(self, aid: str, on: bool, cause, why: str) -> None:
        if self.state.get(aid) == on:
            return
        self.state[aid] = on
        a = self.apps[aid]
        where = self.sc.plan.rooms[a.room].name
        self.bus.publish(f"home/{a.room}/{a.kind}", on, cause,
                         f"{a.kind.upper() if a.kind == 'ac' else a.kind.capitalize()} {'on' if on else 'off'}"
                         f" ({where}) — {why}")

    def set_inverter(self, s: InverterSettings, cause, why: str) -> None:
        key = (s.mode, round(s.back_to_grid_soc, 2), round(s.grid_charge_kw, 1))
        if key == self.settings_sent:
            return
        self.settings_sent = key
        self.inv.settings = s
        self.bus.publish("home/inverter/settings", {"mode": s.mode, "back_to_grid": round(s.back_to_grid_soc, 2),
                                                    "grid_charge_kw": round(s.grid_charge_kw, 1)}, cause,
                         f"Inverter: {s.mode}, battery used down to {s.back_to_grid_soc * 100:.0f}%"
                         + (f", charging from grid at {s.grid_charge_kw:.1f} kW" if s.grid_charge_kw else "")
                         + f" — {why}")

    def setpoint(self, room: str, t: int) -> float:
        return 26.0

    def precooling(self, room: str, t: int) -> bool:
        return False

    def finish(self, t: int) -> None:
        pass

    def mirror(self, kinds) -> None:
        for aid, a in self.apps.items():
            if a.kind in kinds:
                self.command(aid, self.wants.get(aid, False), self.want_msg.get(aid), "someone wants it")


class DefaultCtrl(Base):
    """The inverter as installed: fixed settings, no planning."""
    name = "default"

    def __init__(self, *a):
        super().__init__(*a)
        self.set_inverter(InverterSettings("SBU", 0.30, 0.0), None, "factory setting")

    def tick(self, t: int) -> None:
        self.mirror(("fan", "light", "ac", "tv", "microwave"))
        for kind, job in self.jobs.items():
            if not job["done"]:
                self.command(kind, True, job["msg"], "requested, started at once")
        # the float switch on the roof tank
        if self.tank < 0.30:
            self.command("pump", True, self.tank_msg, f"float switch: tank at {self.tank * 100:.0f}%")
        elif self.tank >= 0.95:
            self.command("pump", False, self.tank_msg, "float switch: tank full")


class UpsCtrl(DefaultCtrl):
    """The common wiring: only the essentials (and TV) are on the inverter."""
    name = "ups"

    def __init__(self, *a):
        super().__init__(*a)
        self.on_inverter = {aid for aid, ap in self.apps.items() if ap.kind in ESSENTIAL + ("tv",)}


class GridSense(Base):
    name = "gridsense"
    COMFORT = True               # pre-cool, solar soak, AC allowance in the night reserve
    AC_KW_OUTAGE = 0.75          # average draw of a 1.5-ton inverter AC holding 27 °C at night
    HEADROOM_KW = 5.5            # keep under the 6 kW rating with margin

    def __init__(self, *a):
        super().__init__(*a)
        self.published = sorted(self.sc.published(), key=lambda o: o.start)
        self.lowv_since = None
        self.lowv_cut = False
        self.precool_rooms: set[str] = set()
        self.soak_rooms: set[str] = set()
        self.soak_prev: set[str] = set()
        self.soak_decided_at = None
        self.outage_began = None
        self.kwp = 6.0

    # ---- planning --------------------------------------------------------

    def next_outage(self, t: int):
        for o in self.published:
            if o.end > t:
                return o
        return None

    def essential_kw(self, at_night: bool) -> float:
        fans = sum(1 for rid, n in self.presence.items() if n and f"fan:{rid}" in self.apps)
        if at_night:
            fans = max(fans, 3)            # three bedrooms asleep
        return 0.08 * fans + 0.06 + 0.015 + (0.06 if at_night else 0.02)

    def solar_kwh_between(self, a: int, b: int) -> float:
        s = self.sc.season
        scale = self.kwp * s.pv_kwh_per_kwp / s.shape_integral_hours() * self.sc.forecast_factor
        return sum(s.clear_sky_shape(t) * scale for t in range(int(a), int(b), 300)) * 300 / 3600

    def projected_soc(self, t: int, until: int) -> float:
        """Battery level expected at `until` with no intervention: sun minus the present load."""
        b = self.inv.battery
        sun = self.solar_kwh_between(t, until)
        use = max(self.load, 0.3) * (until - t) / 3600
        return min(1.0, self.soc + (sun - use) / b.capacity_kwh)

    def reserve_soc(self, t: int) -> tuple[float, object]:
        """SOC to hold for the next published outage: essentials for its length,
        plus one AC for the sleepers if it falls at night."""
        o = self.next_outage(t)
        b = self.inv.battery
        if o is None or o.start - t > 8 * 3600:
            return b.min_soc + 0.10, None
        night = o.start % DAY >= hm("21:00") or o.start % DAY < hm("06:00")
        dur_h = (o.end - max(o.start, t)) / 3600
        e = self.essential_kw(night) * dur_h + (self.AC_KW_OUTAGE * dur_h if night and self.COMFORT else 0.0)
        return min(0.95, b.min_soc + 1.15 * e / b.capacity_kwh), o

    # ---- the loop --------------------------------------------------------

    def tick(self, t: int) -> None:
        b = self.inv.battery
        target, o = self.reserve_soc(t)
        soon = o is not None and 0 <= o.start - t <= 4 * 3600
        why_o = f"outage {_clock(o.start)}–{_clock(o.end)}" if o else ""
        peak = self.sc.season.is_peak(t)

        # battery strategy
        if self.grid:
            self.outage_began = None
            s = self.sc.season
            # the reserve must be in place before the peak window when the outage comes after it,
            # so it is bought at the off-peak price
            before_peak = o is not None and t < s.peak[0] <= o.start
            ready_by = s.peak[0] if before_peak else (o.start if o is not None else t)
            if soon and self.soc < target and not (peak and self.soc >= target - 0.08):
                hours = max(0.25, (ready_by - t) / 3600)
                need_kwh = (target - self.soc) * b.capacity_kwh - 0.8 * self.solar_kwh_between(t, o.start)
                rate = min(3.0, max(0.0, need_kwh / hours * 1.2))
                self.set_inverter(InverterSettings("UTI", target, round(rate, 1)), None,
                                  f"hold {target * 100:.0f}% for the {why_o}"
                                  + (" — charged before the peak window" if before_peak and rate else ""))
            elif (before_peak and o is not None and o.start % DAY >= s.peak[0] and t >= hm("14:00")
                  and self.projected_soc(t, s.peak[0]) < target + 0.15):
                # a night outage ahead: bank the afternoon sun, let the afternoon run on the grid at
                # off-peak price, and arrive at the peak window with the battery full
                hold = min(0.95, target + 0.30)
                self.set_inverter(InverterSettings("SBU", hold, 0.0), None,
                                  f"bank the afternoon sun for the evening and the {why_o}: keep {hold * 100:.0f}%")
            elif peak:
                self.set_inverter(InverterSettings("SBU", max(target, 0.20), 0.0), None,
                                  f"peak tariff {_clock(self.sc.season.peak[0])}–{_clock(self.sc.season.peak[1])}: "
                                  f"run on battery, keep {max(target, 0.2) * 100:.0f}%"
                                  + (f" for the {why_o}" if o else ""))
            else:
                self.set_inverter(InverterSettings("SBU", max(target, 0.25), 0.0), None,
                                  f"solar first, keep {max(target, 0.25) * 100:.0f}%" + (f" for the {why_o}" if o else ""))
        elif self.outage_began is None:
            self.outage_began = t

        # low-voltage protection for compressors
        if self.grid and self.volts and self.volts < LOW_V:
            if not self.lowv_cut:
                self.lowv_cut = True
                self.lowv_since = None
            self.lowv_since = None
        elif self.lowv_cut:
            if self.lowv_since is None:
                self.lowv_since = t
            elif t - self.lowv_since >= OK_V_HOLD:
                self.lowv_cut = False

        # the light loads simply follow wants
        self.mirror(("fan", "light", "tv"))
        if self.lowv_cut:
            self.command("fridge", False, self.volts_msg, f"protecting the compressor: {self.volts:.0f} V")
        else:
            self.command("fridge", True, self.volts_msg, "voltage normal")

        self._acs(t, o, why_o)
        self._pump(t, o, why_o, soon)
        self._jobs(t, o, peak)
        self._microwave(t)

    def committed_kw(self, exclude: str | None = None) -> float:
        """What the switched-on loads could draw together (an AC counted at full output)."""
        return sum(self.apps[a].watts for a, on in self.state.items() if on and a != exclude) / 1000

    def headroom_ok(self, aid: str) -> bool:
        return self.committed_kw(exclude=aid) + self.apps[aid].watts / 1000 <= self.HEADROOM_KW

    def _outage_hours_left(self, t: int) -> float:
        cur = next((x for x in self.published if x.start <= t < x.end), None)
        if cur:
            return (cur.end - t) / 3600
        return 1.0                 # an unannounced cut: assume an hour more

    def _acs(self, t: int, o, why_o: str) -> None:
        self.precool_prev, self.precool_rooms = self.precool_rooms, set()
        self.soak_prev, self.soak_rooms = self.soak_rooms, set()
        acs = [aid for aid, a in self.apps.items() if a.kind == "ac"]
        if self.lowv_cut:
            for aid in acs:
                self.command(aid, False, self.volts_msg, f"protecting the compressor: {self.volts:.0f} V")
            return
        if self.grid:
            soak_now = self._soak_plan(acs)
            for aid in acs:
                room = self.apps[aid].room
                # a pre-cool in progress keeps going: the gate is "warm when it started", or the
                # AC would stop as soon as it had done its job and restart when the room warmed
                warm = room in self.precool_prev or (
                    self.temps.get(room, 30.0) > 26.0 and self.sc.season.outdoor_temp(o.start if o else t) > 28.0)
                pre = self.COMFORT and warm and (o is not None and 0 <= o.start - t <= 2400 and
                       (self.presence.get(room, 0) or (o.start % DAY >= hm("21:30") and room.startswith("bed"))))
                if pre and (self.state.get(aid) or self.headroom_ok(aid)):
                    self.precool_rooms.add(room)
                    self.command(aid, True, None, f"pre-cool to 23.5 °C before the {why_o}")
                elif room in soak_now and (self.state.get(aid) or self.headroom_ok(aid)):
                    self.soak_rooms.add(room)
                    self.command(aid, True, None, f"battery full, sun would be exported at Rs 11 — "
                                                  f"cool the room with it instead")
                else:
                    self.command(aid, self.wants.get(aid, False), self.want_msg.get(aid), "someone wants it")
            return
        # outage: ration by the energy left
        b = self.inv.battery
        hours = self._outage_hours_left(t)
        night = t % DAY >= hm("21:00") or t % DAY < hm("06:00")
        energy = b.usable_kwh - (self.inv.settings.cutoff_soc - b.min_soc) * b.capacity_kwh \
            - self.essential_kw(night) * hours - 0.4 + self.pv * hours * 0.5
        per_ac = self.AC_KW_OUTAGE * hours
        wanted = [aid for aid in acs if self.wants.get(aid)]
        # sleepers first (the elderly and children sleep in the bedrooms), the lounge last
        wanted.sort(key=lambda aid: (self.apps[aid].room == "lounge", aid))
        running = [aid for aid in wanted if self.state.get(aid)]
        spare = energy - per_ac * len(running)
        # drop the lowest-priority running AC only when the plan is clearly short ...
        while running and spare < -0.25:
            drop = running.pop()
            spare += per_ac
            self.command(drop, False, self.grid_msg,
                         f"outage: battery would run short ({spare:.1f} kWh spare after this, {hours:.1f} h left)")
        # ... and add one only when there is clear room for it, so the decision does not flap
        for aid in wanted:
            if aid in running:
                continue
            if spare >= per_ac + 0.25 and self.headroom_ok(aid):
                spare -= per_ac
                running.append(aid)
                self.command(aid, True, self.grid_msg,
                             f"outage: battery covers it ({spare + per_ac:.1f} kWh spare, {hours:.1f} h left)")
            else:
                self.command(aid, False, self.grid_msg, "outage: battery reserved for fans, lights and fridge")
        for aid in acs:
            if aid not in wanted:
                self.command(aid, False, self.want_msg.get(aid), "not wanted")

    SOAK_KW = 1.65              # a soaking AC pulls the room down at full output first

    def _soak_plan(self, acs) -> set[str]:
        """Share the spare sun among occupied rooms, one AC at a time.

        Each soaking AC is charged SOAK_KW against the surplus; the ones already soaking
        are kept first (while the sun roughly covers them), then new rooms join only on
        a clear margin. Deciding rooms independently let three ACs start on one surplus,
        overdraw it together, and all stop — a flap every minute.
        """
        if not self.COMFORT or self.soc < 0.90:
            return set()
        # the house load is measured once a minute: decide only on a fresh reading, or the plan
        # acts six times on a number taken before its own last change
        if self.load_t == self.soak_decided_at:
            return set(self.soak_prev)
        self.soak_decided_at = self.load_t
        running = [a for a in acs if self.apps[a].room in self.soak_prev and self.state.get(a)]
        budget = self.pv - self.load + self.SOAK_KW * len(running)
        keep: set[str] = set()
        # only rooms that are actually warm: in October a 24 °C room needs no cooling, free sun or not
        candidates = [a for a in acs if self.presence.get(self.apps[a].room, 0) and not self.wants.get(a)
                      and (self.temps.get(self.apps[a].room, 30.0) > 28.0 or self.apps[a].room in self.soak_prev)]
        candidates.sort(key=lambda a: (a not in running, -self.presence.get(self.apps[a].room, 0)))
        started = False
        for aid in candidates:
            room = self.apps[aid].room
            if aid in running and budget >= self.SOAK_KW - 0.5:
                keep.add(room)
                budget -= self.SOAK_KW
            elif aid not in running and not started and self.soc > 0.97 and budget >= self.SOAK_KW + 0.5:
                keep.add(room)                  # at most one new room per reading
                budget -= self.SOAK_KW
                started = True
        return keep

    def _pump(self, t: int, o, why_o: str, soon: bool) -> None:
        surplus = self.pv - self.load
        if not self.grid:
            if self.tank < 0.15 and self.inv.battery.usable_kwh > 2.0:
                self.command("pump", True, self.tank_msg, f"outage, but the tank is at {self.tank * 100:.0f}%")
            else:
                self.command("pump", False, self.grid_msg, "outage: pump waits for the grid or the sun")
            return
        if self.tank >= 0.98:
            self.command("pump", False, self.tank_msg, "tank full")
        elif not self.state.get("pump") and not self.headroom_ok("pump"):
            pass                        # waits for headroom on the inverter
        elif o is not None and 0 <= o.start - t <= 3600 and self.tank < 0.85:
            self.command("pump", True, self.tank_msg, f"fill the tank before the {why_o}")
        elif surplus > 0.8 and self.tank < 0.92:
            self.command("pump", True, None, f"solar surplus {surplus:.1f} kW — pump now")
        elif self.tank < 0.30:
            self.command("pump", True, self.tank_msg, f"tank at {self.tank * 100:.0f}%")
        elif self.state.get("pump") and surplus < 0.2 and self.tank > 0.6 and not (o and o.start - t <= 3600):
            self.command("pump", False, None, "no surplus, tank comfortable")

    def _jobs(self, t: int, o, peak: bool) -> None:
        for kind, job in self.jobs.items():
            if job["done"]:
                continue
            kw = self.apps[kind].watts / 1000
            latest = job["deadline"] - job["left"] - 600
            clash = o is not None and o.start - t < job["left"] and o.end > t
            surplus = self.pv - self.load + (kw if self.state.get(kind) else 0)
            if not self.grid:
                if self.state.get(kind) and surplus >= kw:
                    continue
                self.command(kind, False, self.grid_msg, "outage: paused until power returns")
                continue
            if self.state.get(kind):
                continue
            if not self.headroom_ok(kind):
                continue                # e.g. three ACs running: the iron waits a few minutes
            if surplus >= 0.6 * kw and not clash:
                self.command(kind, True, job["msg"], f"solar surplus {surplus:.1f} kW covers it")
            elif t >= latest and not clash:
                self.command(kind, True, job["msg"], f"latest start to finish by {_clock(job['deadline'])}")
            elif t >= latest + 600:
                self.command(kind, True, job["msg"], "deadline: cannot wait any longer")

    def _microwave(self, t: int) -> None:
        want = self.wants.get("microwave", False)
        if want and not self.state.get("microwave") and not self.headroom_ok("microwave"):
            # a short job: the pump or iron yields to it rather than the meal waiting
            for yielder in ("pump", "iron", "washer"):
                if self.state.get(yielder):
                    self.command(yielder, False, self.want_msg.get("microwave"), "paused for the microwave")
                    break
            if not self.headroom_ok("microwave"):
                self.command("microwave", False, self.want_msg.get("microwave"),
                             f"would overload the inverter ({self.committed_kw('microwave') + 1.2:.1f} kW)")
                return
        self.command("microwave", want, self.want_msg.get("microwave"), "someone wants it")

    def setpoint(self, room: str, t: int) -> float:
        if room in self.precool_rooms:
            return 23.5
        if room in self.soak_rooms:
            return 25.0
        return 27.0 if not self.grid else 26.0

    def precooling(self, room: str, t: int) -> bool:
        return room in self.precool_rooms or room in self.soak_rooms


class GridSenseEco(GridSense):
    """Same guarantees (never dark while the battery can carry the essentials, compressors
    protected, inside the inverter's rating), but no comfort extras: the reserve covers fans,
    lights, fridge and router only; no pre-cooling, no solar soak. ACs in an outage still run
    when the battery has energy beyond the reserve."""
    name = "gridsense_eco"
    COMFORT = False


CONTROLLERS = {"default": DefaultCtrl, "ups": UpsCtrl, "gridsense_eco": GridSenseEco, "gridsense": GridSense}
