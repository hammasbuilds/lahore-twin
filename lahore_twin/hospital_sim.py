"""Second-by-second simulation of the Emergency Department and the medical ward.

Every person is a generator that yields what it wants next — walk somewhere,
wait, or wait until something is true — so a patient's journey and a nurse's
shift read as straight-line code. Work is a pool of tasks; who learns about a
task, and when, is what the two rule sets change:

* ``today`` — what a busy public hospital does now: alarms sound for everyone,
  a call light is seen only from the corridor or the station (or when a
  relative walks over), equipment is found by looking in the usual places,
  beds are reported clean by phone, the ED hears about ward beds by phone, and
  hand hygiene is audited for an hour.
* ``connected`` — the same people and events with room-level badges and
  sensors: calls and alarms go to the nurse assigned to the bed and escalate,
  non-critical alarms wait 15 s before sounding, equipment is fetched from where
  the locator shows it, an emptied bed pages the cleaner, the ED sees the live
  bed board, pumps below par in the ED are fetched back from the ward, and
  every dispenser use is counted.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field

from .bus import Bus
from .hospital import DAY, H, HospitalScenario
from .hospital_site import site
from .office import clock
from .plan import Plan, path_length

MODES = ("today", "connected")
PATIENT_ROOMS = {"bay", "hdu", "side", "cubicle", "resus", "treat"}
COLOUR_PRIO = {"red": 0, "orange": 1, "yellow": 2, "green": 3, "blue": 4}
ALARM_DELAY = 15
SEARCH_ORDER = {"ed": ["store", "amb", "majors", "resus", "xray", "waiting", "minors", "m1", "m2", "m3", "m4", "m5", "m6"],
                "ward": ["store", "corridor", "station", "bay_a", "bay_b", "bay_c", "hdu", "side1", "side2", "lobby"]}
STORE = {"ed": (26.2, 7.0), "ward": (31.0, 33.0)}


@dataclass
class Task:
    id: int
    kind: str
    unit: str
    spot: tuple
    prio: int
    created: int
    dur: int
    skill: str
    patient: object = None
    asset: str | None = None
    assignee: str | None = None
    visible: int | None = None          # when staff learn of it (None = nobody yet)
    escalate: int | None = None
    taken: str | None = None
    arrived: int | None = None
    done: int | None = None
    cancelled: bool = False
    cause: int | None = None
    on_done: object = None
    meta: dict = field(default_factory=dict)


class Agent:
    def __init__(self, aid, name, role, unit, speed):
        self.id, self.name, self.role, self.unit, self.speed = aid, name, role, unit, speed
        self.building = None
        self.pos = (0.0, 0.0)
        self.path: list = []
        self.legs: list = []
        self.seg = 0
        self.seg_done = 0.0
        self.gen = None
        self.wait_until = None
        self.pred = None
        self.pred_deadline = None
        self.on = False
        self.walked = 0.0
        self.skill = role
        self.base = None
        self.task = None
        self.carrying = None
        self.end = DAY

    def advance(self, dt: float) -> bool:
        budget = self.speed * dt
        while budget > 0 and self.seg < len(self.path) - 1:
            a, b = self.path[self.seg], self.path[self.seg + 1]
            left = math.dist(a, b) - self.seg_done
            if budget < left:
                self.seg_done += budget
                self.walked += budget
                f = self.seg_done / math.dist(a, b)
                self.pos = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                return False
            budget -= left
            self.walked += left
            self.seg += 1
            self.seg_done = 0.0
            self.pos = b
        self.path = []
        return True


@dataclass
class Bed:
    id: str
    unit: str
    room: str
    spot: tuple
    state: str = "ready"                # ready | reserved | occupied | dirty | cleaning
    patient: str | None = None
    since: int = 0
    known_ready: int | None = 0         # when the ED learns this ward bed is ready


class HospitalSim:
    def __init__(self, sc: HospitalScenario, ed: Plan, ward: Plan, mode: str):
        assert mode in MODES
        self.sc, self.mode, self.conn = sc, mode, mode == "connected"
        self.plans = {"ed": ed, "ward": ward}
        self.site = site()
        self.bus = Bus(quiet=("temp", "location", "census"))
        self.rng = random.Random(sc.seed * 7 + 3)          # rule-set-specific draws (phone delays etc.)
        self.hh_rng = random.Random(sc.seed * 7 + 5)
        self.t = 0
        self.agents: dict[str, Agent] = {}
        self.tasks: list[Task] = []
        self.open: list[Task] = []
        self._tid = 0
        self.trips: list = []
        self.presence: list = []            # [aid, t_on, t_off, building, x, y]
        self.labels: list = []              # [t, aid, text]
        self.asset_ev: list = []            # [t, asset, building, x, y, holder]
        self.records: dict[str, dict] = {}
        self.beds: dict[str, Bed] = {}
        for bid, (room, spot) in sc.beds.items():
            self.beds[bid] = Bed(bid, "ward", room, spot)
        for key in ("bed_resus", "bed_majors", "bed_minors", "chair_majors"):
            for i, p in enumerate(ed.spots[key], 1):
                self.beds[f"{key[4:] if key.startswith('bed_') else 'chair'}-{i}"] = Bed(
                    f"{key[4:] if key.startswith('bed_') else 'chair'}-{i}", "ed", ed.room_at(*p), tuple(p))
        self.seats = {i: None for i in range(len(ed.spots["seat"]))}
        self.reg_queue: list = []
        self.xray_busy = None
        self.assets = {a.id: dict(id=a.id, kind=a.kind, building=a.building, pos=a.spot, room=a.room,
                                  holder=None, attached=None) for a in sc.assets}
        self.fridges = {"ward": dict(temp=5.0, open=False, opened=None, over_since=None, alerted=False,
                                     spot=ward.spots["meds_fridge"][0], building="ward"),
                        "ed": dict(temp=5.0, open=False, opened=None, over_since=None, alerted=False,
                                   spot=ed.spots["fridge"][0], building="ed")}
        self.fridge_series = {"ward": [], "ed": []}
        self.fridge_events: list = []
        self.hh: list = []                   # hand-hygiene opportunities
        self.alarm_log: list = []
        self.call_log: list = []
        self.fetch_log: list = []
        self.bed_log: list = []
        self.bed_ev: list = []               # [t, bed, state]
        self.census: list = []               # per-minute snapshot
        self.pending_admit: list = []
        self.nurse_beds: dict[str, str] = {}
        self._on_duty_key = None
        self.ward_occupant: dict[str, str] = {}
        self.ward_patients: dict[str, object] = {}

    # ---------------------------------------------------------------- helpers
    def say(self, a: Agent, text: str) -> None:
        self.labels.append([self.t, a.id, text])

    def room(self, a: Agent) -> str | None:
        if a.building in self.plans:
            return self.plans[a.building].room_at(*a.pos)
        return None

    def task(self, kind, unit, spot, prio, dur, skill, **kw) -> Task:
        self._tid += 1
        tk = Task(self._tid, kind, unit, tuple(spot), prio, self.t, dur, skill, **kw)
        self.tasks.append(tk)
        self.open.append(tk)
        return tk

    def bed_state(self, bed: Bed, state: str, patient=None, cause=None, text=""):
        bed.state, bed.since = state, self.t
        if patient is not None or state in ("ready", "dirty", "cleaning"):
            bed.patient = patient
        self.bed_ev.append([self.t, bed.id, state])
        return self.bus.publish(f"hospital/{bed.unit}/{bed.id}/state", state, cause, text or f"{bed.id}: {state}")

    def asset_moved(self, asset: dict, holder=None):
        self.asset_ev.append([self.t, asset["id"], asset["building"], round(asset["pos"][0], 2),
                              round(asset["pos"][1], 2), holder])

    # ---------------------------------------------------------------- movement
    def _start_leg(self, a: Agent) -> None:
        while a.legs:
            b, pts = a.legs.pop(0)
            if len(pts) >= 2 and path_length(pts) > 0.05:
                a.building, a.path, a.seg, a.seg_done = b, pts, 0, 0.0
                a.pos = pts[0]
                self.trips.append([a.id, b, self.t, a.speed, [[round(x, 2), round(y, 2)] for x, y in pts]])
                return
            a.building, a.pos = b, pts[-1]
        a.path = []

    def go(self, a: Agent, building: str, spot) -> None:
        spot = tuple(spot)
        legs = []
        if a.building == building:
            legs.append((building, self.plans[building].route(a.pos, spot)))
        else:
            s = self.site
            if a.building == "ed":
                legs.append(("ed", self.plans["ed"].route(a.pos, self.plans["ed"].spots["campus_exit"][0])))
            elif a.building == "ward":
                legs.append(("ward", self.plans["ward"].route(a.pos, self.plans["ward"].spots["entry"][0])))
            path = s["path"] if building == "ward" else s["path"][::-1]
            legs.append(("campus", [tuple(p) for p in path]))
            entry = self.plans[building].spots["campus_exit" if building == "ed" else "entry"][0]
            legs.append((building, self.plans[building].route(entry, spot)))
        a.legs = legs
        self._start_leg(a)

    def walk_length(self, b0: str, p0, b1: str, p1) -> float:
        """Metres walked from (b0, p0) to (b1, p1), across the campus if the buildings differ."""
        if b0 == b1:
            return path_length(self.plans[b0].route(p0, p1))
        exit0 = self.plans[b0].spots["campus_exit" if b0 == "ed" else "entry"][0]
        entry1 = self.plans[b1].spots["campus_exit" if b1 == "ed" else "entry"][0]
        return (path_length(self.plans[b0].route(p0, exit0)) + self.site["path_m"]
                + path_length(self.plans[b1].route(entry1, p1)))

    def spawn(self, a: Agent, building: str, spot, gen) -> None:
        a.building, a.pos, a.on, a.gen = building, tuple(spot), True, gen
        self.agents[a.id] = a
        self.presence.append([a.id, self.t, None, building, round(spot[0], 2), round(spot[1], 2)])
        self._resume(a)

    def _resume(self, a: Agent) -> None:
        for _ in range(50):
            a.wait_until = a.pred = a.pred_deadline = None
            try:
                cmd = next(a.gen)
            except StopIteration:
                a.on = False
                for row in reversed(self.presence):
                    if row[0] == a.id and row[2] is None:
                        row[2] = self.t
                        break
                return
            op = cmd[0]
            if op == "go":
                self.go(a, cmd[1], cmd[2])
                if a.path:
                    return
            elif op == "wait":
                if cmd[1] > 0:
                    a.wait_until = self.t + int(cmd[1])
                    return
            elif op == "until":
                if not cmd[1]():
                    a.pred = cmd[1]
                    a.pred_deadline = self.t + cmd[2] if len(cmd) > 2 else None
                    return

    def _step(self, a: Agent) -> None:
        if a.path:
            if a.advance(1.0):
                if a.legs:
                    self._start_leg(a)
                    return
                self._resume(a)
            return
        if a.wait_until is not None:
            if self.t >= a.wait_until:
                self._resume(a)
        elif a.pred is not None:
            if a.pred() or (a.pred_deadline is not None and self.t >= a.pred_deadline):
                self._resume(a)

    # ---------------------------------------------------------------- staff
    def visible_to(self, tk: Task, a: Agent) -> bool:
        if tk.taken or tk.done is not None or tk.cancelled or tk.skill != a.skill or tk.unit != a.unit:
            return False
        if tk.visible is None or tk.visible > self.t:
            return False
        if tk.assignee and tk.assignee != a.id and not (tk.escalate is not None and self.t >= tk.escalate):
            # an assignee who has left the shift, or (badges show it) is busy elsewhere,
            # does not hold the task back: it goes to whoever is free
            other = self.agents.get(tk.assignee)
            if other is not None and other.on and self.t < other.end and other.task is None:
                return False
        if tk.kind == "assess" and tk.meta.get("couch") and tk.patient.call is None and not self.free_bed("minors"):
            return False
        return True

    def pick(self, a: Agent) -> Task | None:
        best = None
        for tk in self.open:
            if self.visible_to(tk, a):
                key = (tk.prio, tk.created, tk.id)
                if best is None or key < best[0]:
                    best = (key, tk)
        return best[1] if best else None

    def free_bed(self, kind: str):
        for b in self.beds.values():
            if b.unit == "ed" and b.id.startswith(kind + "-") and b.state == "ready":
                return b
        return None

    def staff_loop(self, a: Agent):
        while True:
            if self.t >= a.end:
                break
            tk = self.pick(a)
            if tk is None:
                if math.dist(a.pos, a.base) > 0.5 or a.building != a.unit:
                    self.say(a, "Back to " + ("the station" if a.role == "nurse" else "base"))
                    yield ("go", a.unit, a.base)
                    continue
                yield ("until", lambda: self.pick(a) is not None or self.t >= a.end, 60)
                continue
            tk.taken, a.task = a.id, tk
            if tk.meta.get("couch") and tk.patient.call is None:
                bed = self.free_bed("minors")
                self.bed_state(bed, "reserved", tk.patient.id)
                tk.patient.call = bed
                tk.spot = tk.meta["pspot"] = bed.spot
            if tk.kind == "register":
                tk.spot = a.base
                tk.patient.call = tk.meta["pspot"] = (a.base[0], a.base[1] + 1.3)
            if tk.kind == "triage":
                tk.spot = a.base
                tk.meta["pspot"] = tuple(self.plans["ed"].spots["triage_patient"][0 if a.base[0] < 7 else 1])
            self.say(a, tk.meta.get("label", tk.kind))
            if tk.asset:
                got = yield from self.fetch(a, tk.asset, tk.unit if tk.asset != "pump_retrieve" else "ward")
                if got is None and tk.kind == "drip":
                    # no pump anywhere: the drip runs by gravity, counted
                    self.say(a, "No free pump — gravity drip")
                    tk.meta["no_pump"] = True
                    tk.asset = None
                elif got is None:
                    self.say(a, f"No free {tk.asset} found")
                    tk.taken, a.task = None, None
                    tk.meta["failed"] = tk.meta.get("failed", 0) + 1
                    yield ("wait", 300)
                    continue
                else:
                    tk.meta["asset_id"] = got["id"]
            yield ("go", tk.unit if tk.kind not in ("transfer",) else tk.unit, tk.spot)
            tk.arrived = self.t
            self.hand_hygiene(a)
            if tk.meta.get("wait_patient"):
                yield ("until", lambda: tk.patient.ready_for(tk), 1800)
            tk.meta.setdefault("start", self.t)          # door-to-doctor counts to here, not to the end
            paused = yield from self.perform(a, tk)
            if paused:
                # a red patient came in: this consult goes back on the board with the time it still needs
                self.say(a, "Called away to a red patient")
                tk.taken, tk.arrived, a.task = None, None, None
                tk.meta["paused"] = tk.meta.get("paused", 0) + 1
                continue
            tk.done = self.t
            if tk in self.open:
                self.open.remove(tk)
            a.task = None
            if tk.on_done:
                tk.on_done(tk, a)
        self.say(a, "Shift over")
        yield ("go", a.unit, self.plans[a.unit].spots["campus_exit" if a.unit == "ed" else "entry"][0])

    def perform(self, a: Agent, tk: Task):
        if tk.kind == "transfer":
            p = tk.patient
            asset = self.assets[tk.meta["asset_id"]]
            p.escort = a
            yield ("until", lambda: p.following, 600)
            bed = self.beds[p.ward_bed]
            yield ("go", "ward", bed.spot)
            yield ("until", lambda: p.arrived_ward, 900)
            # the porter takes the trolley or chair back, or the ED runs out of them
            self.say(a, f"Taking the {asset['kind']} back to the ED")
            yield ("go", "ed", (28.0 if asset["kind"] == "trolley" else 23.5, 46.5))
            asset["holder"], asset["building"], asset["pos"] = None, "ed", a.pos
            asset["room"] = self.plans["ed"].room_at(*a.pos)
            self.asset_moved(asset)
            a.carrying = None
            return
        if tk.kind == "xray_escort":
            p = tk.patient
            asset = self.assets[tk.meta["asset_id"]]
            p.escort = a
            yield ("until", lambda: p.following, 600)
            yield ("go", "ed", (5.0, 9.0))
            yield ("until", lambda: p.xray_done, 3600)
            yield ("go", "ed", tk.spot)
            yield ("until", lambda: not p.following, 900)
            asset["holder"], asset["pos"], asset["building"] = None, a.pos, "ed"
            asset["room"] = self.plans["ed"].room_at(*a.pos)
            self.asset_moved(asset)
            a.carrying = None
            return
        if tk.kind == "pump_retrieve":
            asset = self.assets[tk.meta["asset_id"]]
            yield ("go", "ed", STORE["ed"])
            asset["holder"], asset["pos"], asset["building"] = None, a.pos, "ed"
            asset["room"] = self.plans["ed"].room_at(*a.pos)
            self.asset_moved(asset)
            a.carrying = None
            return
        if a.role == "doctor" and a.unit == "ed" and tk.prio > 0:
            left = tk.dur
            while left > 0:
                step = min(20, left)
                yield ("wait", step)
                left -= step
                if left > 0 and any(o.prio == 0 and o.skill == "doctor" and o.unit == "ed" and not o.taken
                                    and o.done is None and not o.cancelled for o in self.open):
                    tk.dur = left
                    return True
        else:
            yield ("wait", tk.dur)
        if tk.asset and tk.kind == "drip":
            asset = self.assets[tk.meta["asset_id"]]
            asset["holder"], asset["attached"] = None, tk.patient.id
            tk.patient.pumps.append(asset["id"])
            self.asset_moved(asset, tk.patient.id)
            a.carrying = None
        fr = next((f for k, f in self.fridges.items() if f["building"] == a.unit and math.dist(f["spot"], a.pos) < 2.5), None)
        if fr and fr["open"]:
            self.close_fridge(fr, a)

    def hand_hygiene(self, a: Agent) -> None:
        r = self.room(a)
        if r is None or self.plans[a.building].rooms[r].kind not in PATIENT_ROOMS:
            return
        audit = (not self.conn) and a.building == "ward" and self.sc.audit[0] <= self.t < self.sc.audit[1]
        p = self.sc.audited_hand_hygiene if audit else self.sc.true_hand_hygiene
        washed = self.hh_rng.random() < p
        detected = self.conn and self.hh_rng.random() < 0.92
        self.hh.append(dict(t=self.t, staff=a.id, room=r, washed=washed, observed=audit, detected=detected))

    # ---------------------------------------------------------------- equipment
    def free_assets(self, kind: str, building: str):
        return [x for x in self.assets.values()
                if x["kind"] == kind and x["building"] == building and x["holder"] is None and x["attached"] is None]

    def fetch(self, a: Agent, kind: str, building: str):
        kind = "pump" if kind == "pump_retrieve" else kind
        plan = self.plans[building]
        t0, start, start_bld, walked0 = self.t, a.pos, a.building, a.walked
        found = None
        if self.conn:
            cands = self.free_assets(kind, building)
            if cands:
                if a.building == building:
                    found = min(cands, key=lambda x: path_length(plan.route(a.pos, x["pos"])))
                else:
                    found = cands[0]
        else:
            for rid in SEARCH_ORDER[building]:
                here = [x for x in self.free_assets(kind, building) if plan.room_at(*x["pos"]) == rid]
                if not here:
                    r = plan.rooms[rid]
                    self.say(a, f"Looking for a {kind} in {r.name}")
                    yield ("go", building, ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
                    here = [x for x in self.free_assets(kind, building) if plan.room_at(*x["pos"]) == rid]
                if here:
                    found = here[0]
                    break
        if found is None:
            self.fetch_log.append(dict(t=t0, staff=a.id, kind=kind, unit=building, secs=self.t - t0, found=False,
                                       direct=0, walked=a.walked - walked0))
            return None
        found["holder"] = a.id
        yield ("go", building, found["pos"])
        found["holder"] = a.id
        a.carrying = found["id"]
        self.asset_moved(found, a.id)
        direct = self.walk_length(start_bld, start, building, found["pos"])
        self.fetch_log.append(dict(t=t0, staff=a.id, kind=kind, unit=building, secs=self.t - t0, found=True,
                                   direct=round(direct / a.speed), walked=round(a.walked - walked0, 1)))
        return found

    # ---------------------------------------------------------------- fridges
    def close_fridge(self, fr: dict, a: Agent):
        fr["open"] = False
        key = "ward" if fr is self.fridges["ward"] else "ed"
        ev = next(e for e in reversed(self.fridge_events) if e["fridge"] == key and e["closed"] is None)
        ev["closed"], ev["by"] = self.t, a.id
        self.bus.publish(f"hospital/{key}/fridge/door", "closed", ev.get("alert_id"),
                         f"{a.name} closed the {key} medicine fridge (open {(self.t - ev['opened']) // 60} min, peak {ev['peak']:.1f} °C)")
        fr["alerted"] = False

    def fridge_tick(self) -> None:
        for key, fr in self.fridges.items():
            target, tau = (18.0, 1800) if fr["open"] else (5.0, 1200)
            fr["temp"] += (target - fr["temp"]) * (60 / tau)
            m = self.bus.publish(f"hospital/{key}/fridge/temp", round(fr["temp"], 2))
            ev = next((e for e in reversed(self.fridge_events) if e["fridge"] == key), None)
            if ev and (ev["closed"] is None or fr["temp"] > 8):
                ev["peak"] = max(ev["peak"], fr["temp"])
                if fr["temp"] > 8:
                    ev["minutes_over"] += 1
            if fr["temp"] > 8:
                fr["over_since"] = fr["over_since"] or self.t
            else:
                fr["over_since"] = None
            if self.conn and fr["open"] and not fr["alerted"] and fr["over_since"] and self.t - fr["over_since"] >= 300:
                fr["alerted"] = True
                al = self.bus.publish(f"hospital/{key}/fridge/alert", round(fr["temp"], 1), m.id,
                                      f"{key.title()} medicine fridge {fr['temp']:.1f} °C for 5 min — door?")
                ev["alerted"], ev["alert_id"] = self.t, al.id
                tk = self.task("fridge", key, fr["spot"], 2, 20, "nurse", visible=self.t, cause=al.id,
                               meta={"label": "Fridge alert: check the door"})
                tk.meta["fridge"] = key
            self.fridge_series[key].append(round(fr["temp"], 2))

    # ---------------------------------------------------------------- ward
    def assign_nurses(self) -> None:
        on = sorted(a.id for a in self.agents.values() if a.on and a.unit == "ward" and a.role == "nurse" and self.t < a.end)
        key = tuple(on)
        if key == self._on_duty_key or not on:
            return
        self._on_duty_key = key
        beds = [b for b in self.beds.values() if b.unit == "ward"]
        per = math.ceil(len(beds) / len(on))
        self.nurse_beds = {b.id: on[i // per] for i, b in enumerate(beds)}

    def ward_alarm(self, al) -> None:
        bed = self.beds[al.bed]
        if bed.state != "occupied":
            return
        m = self.bus.publish(f"hospital/ward/{al.bed}/alarm", al.kind, None,
                             f"Monitor alarm at {al.bed} ({'critical' if al.kind == 'critical' else 'yellow'})")
        rec = dict(t=al.t, bed=al.bed, kind=al.kind, dur=al.dur, annunciated=None, arrived=None, task=None)
        self.alarm_log.append(rec)
        if self.conn and al.kind != "critical":
            rec["pending_until"] = al.t + ALARM_DELAY
            rec["cause"] = m.id
            return
        self._alarm_task(rec, m.id)

    def _alarm_task(self, rec, cause) -> None:
        rec["annunciated"] = self.t
        bed = self.beds[rec["bed"]]
        true = rec["kind"] in ("sustained", "critical")
        care = next(a.care_s for a in self.sc.alarms if a.t == rec["t"] and a.bed == rec["bed"])
        dur = care if true else 30
        assignee = self.nurse_beds.get(rec["bed"]) if self.conn and rec["kind"] != "critical" else None
        tk = self.task("alarm", "ward", bed.spot, 0 if rec["kind"] == "critical" else 1, dur, "nurse",
                       visible=self.t, assignee=assignee, escalate=self.t + 120 if assignee else None, cause=cause,
                       meta={"label": f"Alarm at {rec['bed']}", "rec": rec})
        tk.on_done = lambda t_, a: self.bus.publish(f"hospital/ward/{rec['bed']}/alarm/answered", rec["kind"], cause,
                                                   f"{a.name} answered the alarm at {rec['bed']} after {(t_.arrived - rec['t'])} s"
                                                   + ("" if rec["kind"] in ("sustained", "critical") else " — nothing wrong"))
        rec["task"] = tk

    def ward_call(self, c) -> None:
        bed = self.beds[c.bed]
        if bed.state != "occupied" or self.ward_occupant.get(c.bed) is None:
            return
        m = self.bus.publish(f"hospital/ward/{c.bed}/call", True, None, f"Call button at {c.bed}")
        rec = dict(t=c.t, bed=c.bed, noticed=None, arrived=None)
        self.call_log.append(rec)
        assignee = self.nurse_beds.get(c.bed) if self.conn else None
        tk = self.task("call", "ward", bed.spot, 2, c.care_s, "nurse",
                       visible=self.t if self.conn else None, assignee=assignee,
                       escalate=self.t + 180 if assignee else None, cause=m.id,
                       meta={"label": f"Call at {c.bed}", "rec": rec, "room": bed.room})
        if self.conn:
            rec["noticed"] = self.t
        tk.on_done = lambda t_, a: self.bus.publish(f"hospital/ward/{c.bed}/call/answered", True, m.id,
                                                   f"{a.name} answered {c.bed} after {(t_.arrived - c.t) // 60} min {(t_.arrived - c.t) % 60} s")

    def notice_calls(self) -> None:
        """Today: a call light is seen from the corridor, the station or the room itself;
        failing that, a relative walks to the station after five minutes."""
        rooms = {self.room(a) for a in self.agents.values()
                 if a.on and a.unit == "ward" and a.role == "nurse" and a.building == "ward"}
        for tk in self.open:
            if tk.kind == "call" and tk.visible is None:
                if rooms & {"corridor", "station", tk.meta["room"]} or self.t - tk.created >= 300:
                    tk.visible = self.t
                    tk.meta["rec"]["noticed"] = self.t
                    tk.meta["rec"]["how"] = "seen" if self.t - tk.created < 300 else "relative"

    def ward_patient(self, a: Agent, wp, bed: Bed):
        self.ward_occupant[bed.id] = wp.id
        self.say(a, "In bed")
        if wp.discharge is None:
            yield ("until", lambda: False)
        yield ("until", lambda: self.t >= wp.discharge)
        self.say(a, "Discharged — going home")
        self.ward_occupant[bed.id] = None
        dm = self.bed_state(bed, "dirty", None, text=f"{wp.name} discharged; {bed.id} needs cleaning")
        self.request_clean(bed, dm.id)
        yield ("go", "ward", self.plans["ward"].spots["entry"][0])

    def request_clean(self, bed: Bed, cause) -> None:
        delay = 0 if self.conn else (int(self.rng.uniform(20, 90) * 60) if bed.unit == "ward" else int(self.rng.uniform(5, 20) * 60))
        rec = dict(bed=bed.id, unit=bed.unit, dirty=self.t, requested=self.t + delay, ready=None)
        self.bed_log.append(rec)
        tk = self.task("clean", bed.unit, bed.spot, 3, 1200 if bed.unit == "ward" else 600, "cleaner",
                       visible=self.t + delay, cause=cause, meta={"label": f"Clean {bed.id}"})

        def done(t_, a, bed=bed, rec=rec):
            rec["ready"] = self.t
            m = self.bed_state(bed, "ready", None, cause, f"{bed.id} clean and ready ({a.name})")
            if bed.unit == "ward":
                bed.known_ready = self.t if self.conn else self.t + int(self.rng.uniform(10, 40) * 60)
            del m
        tk.on_done = done
        if delay:
            self.bus.publish(f"hospital/{bed.unit}/{bed.id}/clean_request", delay, cause,
                             f"{bed.id}: housekeeping told {delay // 60} min later (by phone)")
        else:
            self.bus.publish(f"hospital/{bed.unit}/{bed.id}/clean_request", 0, cause,
                             f"{bed.id}: empty-bed sensor paged the cleaner")

    # ---------------------------------------------------------------- ED patients
    def ed_patient(self, a: Agent, p):
        sim, ed = self, self.plans["ed"]
        rec = self.records[p.id] = dict(id=p.id, name=p.name, colour=p.colour, ambulance=p.ambulance, arrive=self.t,
                                        registered=None, triaged=None, placed=None, place=None, seen=None,
                                        results=None, reviewed=None, decision=None, left=None, outcome=None,
                                        boarding=None, ward_bed=None)
        a.call = None
        a.escort = None
        a.following = False
        a.arrived_ward = False
        a.xray_done = False
        a.pumps = []
        # the patient is ready when standing (or lying) where this task expects them
        a.ready_for = lambda tk: not a.path and math.dist(a.pos, tk.meta.get("pspot", tk.spot)) < 0.6
        cause = self.bus.publish(f"hospital/ed/{p.id}/arrival", p.colour if p.ambulance else None, None,
                                 f"{p.name} arrived {'by ambulance (' + p.colour + ')' if p.ambulance else 'on foot'}").id
        seat = None

        def take_seat():
            nonlocal seat
            free = [i for i, who in self.seats.items() if who is None]
            if free:
                seat = free[0]
                self.seats[seat] = p.id
                return ed.spots["seat"][seat]
            return (17.5 + self.rng.uniform(-3, 3), 47.5)

        def leave_seat():
            nonlocal seat
            if seat is not None:
                self.seats[seat] = None
                seat = None

        def walk_out(outcome, text):
            rec["left"], rec["outcome"] = self.t, outcome
            self.bus.publish(f"hospital/ed/{p.id}/left", outcome, cause, text)

        bed = None
        if not p.ambulance:
            self.say(a, "Queueing to register")
            yield ("go", "ed", ed.spots["reg_queue"][min(len(self.reg_queue), len(ed.spots["reg_queue"]) - 1)])
            self.reg_queue.append(p.id)
            tk = self.task("register", "ed", ed.spots["reg_desk_staff"][0], 1, p.reg_s, "clerk", visible=self.t,
                           patient=a, meta={"label": f"Register {p.name}", "wait_patient": True})
            yield ("until", lambda: a.call is not None)
            yield ("go", "ed", a.call)
            yield ("until", lambda: tk.done is not None)
            self.reg_queue.remove(p.id)
            a.call = None
            rec["registered"] = self.t
            self.say(a, "Waiting for triage")
            yield ("go", "ed", take_seat())
            tk = self.task("triage", "ed", (0, 0), 1, p.triage_s, "triage", visible=self.t, patient=a,
                           meta={"label": f"Triage {p.name}"})
            tk.meta["wait_patient"] = True
            yield ("until", lambda: tk.taken is not None or self.t - p.arrive > p.patience)
            if tk.taken is None:
                tk.cancelled = True
                self.open.remove(tk)
                leave_seat()
                self.say(a, "Left without being seen")
                walk_out("left unseen", f"{p.name} left before triage after {(self.t - p.arrive) // 60} min")
                yield ("go", "ed", ed.spots["walkin"][0])
                return
            nurse = self.agents[tk.taken]
            k = 0 if nurse.base[0] < 7 else 1
            leave_seat()
            yield ("go", "ed", ed.spots["triage_patient"][k])
            yield ("until", lambda: tk.done is not None)
            rec["triaged"] = tk.meta["start"]
        else:
            rec["triaged"] = self.t
        self.bus.publish(f"hospital/ed/{p.id}/triage", p.colour, cause, f"{p.name} triaged {p.colour.upper()}")

        order = {"red": ["resus", "majors", "chair"], "orange": ["majors", "chair"], "yellow": ["majors", "chair"]}.get(p.colour, [])
        for kind in order:
            bed = self.free_bed(kind)
            if bed:
                break
        if bed:
            self.bed_state(bed, "occupied", p.id, cause, f"{p.name} placed in {bed.id}")
            rec["placed"], rec["place"] = self.t, bed.id
            self.say(a, f"In {bed.id}")
            yield ("go", "ed", bed.spot)
        else:
            rec["place"] = "waiting"
            self.say(a, "Waiting to see a doctor")
            if seat is None:
                yield ("go", "ed", take_seat())

        def await_task(tk, may_leave):
            while True:
                yield ("until", lambda: tk.taken is not None or (may_leave and self.t - p.arrive > p.patience), 120)
                if tk.taken is not None:
                    return True
                if may_leave and self.t - p.arrive > p.patience:
                    return False

        may_leave = p.colour in ("yellow", "green", "blue")
        tk = self.task("assess", "ed", bed.spot if bed else a.pos, COLOUR_PRIO[p.colour], p.consult_s, "doctor",
                       visible=self.t, patient=a, meta={"label": f"Assess {p.name} ({p.colour})", "couch": bed is None,
                                                         "wait_patient": True})
        ok = yield from await_task(tk, may_leave)
        if not ok:
            tk.cancelled = True
            self.open.remove(tk)
            leave_seat()
            self.say(a, "Left without being seen")
            walk_out("left unseen", f"{p.name} left unseen after {(self.t - p.arrive) // 60} min")
            yield ("go", "ed", ed.spots["walkin"][0])
            return
        if bed is None:
            yield ("until", lambda: a.call is not None, 600)
            couch = a.call
            leave_seat()
            self.say(a, "Called to Minors")
            yield ("go", "ed", couch.spot)
            self.bed_state(couch, "occupied", p.id)
        yield ("until", lambda: tk.done is not None)
        rec["seen"] = tk.meta["start"]
        self.bus.publish(f"hospital/ed/{p.id}/seen", p.colour, cause, f"{p.name} seen by a doctor {(rec['seen'] - p.arrive) // 60} min after arriving")
        if bed is None:
            couch = a.call
            a.call = None
            dm = self.bed_state(couch, "dirty", None, cause)
            self.request_clean(couch, dm.id)
            self.say(a, "Waiting for results")
            yield ("go", "ed", take_seat())
        here = a.pos
        result_at = self.t
        if p.drip:
            self.task("drip", "ed", here, COLOUR_PRIO[p.colour], 360, "nurse", visible=self.t, patient=a,
                      asset="pump", meta={"label": f"Start a drip for {p.name}"})
        if p.blood:
            def got_sample(t_, nurse, p=p):
                nonlocal result_at
                result_at = self.t + p.lab_tat
            self.task("sample", "ed", here, COLOUR_PRIO[p.colour], 300, "nurse", visible=self.t, patient=a,
                      on_done=got_sample, meta={"label": f"Blood sample from {p.name}"})
            result_at = DAY * 2
        if p.xray:
            self.say(a, "Going for an X-ray")
            if p.colour in ("red", "orange"):
                tk2 = self.task("xray_escort", "ed", here, COLOUR_PRIO[p.colour], 0, "porter", visible=self.t, patient=a,
                                asset="wheelchair", meta={"label": f"Take {p.name} to X-ray"})
                yield ("until", lambda: a.escort is not None and math.dist(a.escort.pos, a.pos) < 2 and not a.escort.path)
                a.following = True
                a.speed = min(a.speed, a.escort.speed)
                yield ("go", "ed", (5.6, 9.0))
            else:
                yield ("go", "ed", (5.6, 9.0))
            yield ("until", lambda: self.xray_busy is None)
            self.xray_busy = p.id
            yield ("go", "ed", ed.spots["xray_table"][0])
            yield ("wait", 480)
            self.xray_busy = None
            a.xray_done = True
            yield ("go", "ed", here)
            a.following = False
        yield ("until", lambda: self.t >= result_at)
        rec["results"] = self.t
        tk = self.task("review", "ed", a.pos, COLOUR_PRIO[p.colour], p.review_s, "doctor", visible=self.t, patient=a,
                       meta={"label": f"Review {p.name}'s results", "wait_patient": True, "pspot": a.pos})
        yield ("until", lambda: tk.done is not None)
        rec["reviewed"] = self.t
        if p.admit:
            rec["decision"] = self.t
            m = self.bus.publish(f"hospital/ed/{p.id}/admit", True, cause, f"{p.name}: admit to the medical ward")
            self.say(a, "Waiting for a ward bed")
            a.ward_bed = None
            self.pending_admit.append((COLOUR_PRIO[p.colour], self.t, a, rec, m.id))
            yield ("until", lambda: a.ward_bed is not None)
            on_bed = bed is not None and not bed.id.startswith("chair")
            tk = self.task("transfer", "ed", a.pos, 1, 0, "porter", visible=self.t, patient=a,
                           asset="trolley" if on_bed else "wheelchair", meta={"label": f"Take {p.name} to the ward"})
            yield ("until", lambda: a.escort is not None and math.dist(a.escort.pos, a.pos) < 2 and not a.escort.path)
            a.following = True
            a.speed = a.escort.speed
            leave_seat()
            if bed:
                dm = self.bed_state(bed, "dirty", None, cause, f"{p.name} left {bed.id} for the ward")
                self.request_clean(bed, dm.id)
            walk_out("admitted", f"{p.name} left the ED for the ward ({a.ward_bed})")
            rec["boarding"] = self.t - rec["decision"]
            self.say(a, "Going to the ward")
            for pid in a.pumps:
                self.assets[pid]["attached"] = p.id
            wb = self.beds[a.ward_bed]
            yield ("go", "ward", wb.spot)
            for pid in a.pumps:
                x = self.assets[pid]
                x["building"], x["pos"] = "ward", wb.spot
                self.asset_moved(x, p.id)
            a.arrived_ward = True
            self.bed_state(wb, "occupied", p.id, cause, f"{p.name} arrived in {wb.id}")
            self.ward_occupant[wb.id] = p.id
            self.say(a, "In bed on the ward")
            yield ("until", lambda: False)
        else:
            leave_seat()
            if bed:
                dm = self.bed_state(bed, "dirty", None, cause, f"{p.name} discharged from {bed.id}")
                self.request_clean(bed, dm.id)
            for pid in a.pumps:
                x = self.assets[pid]
                x["attached"], x["pos"], x["building"] = None, a.pos, "ed"
                x["room"] = ed.room_at(*a.pos)
                self.asset_moved(x)
            walk_out("home", f"{p.name} went home after {(self.t - p.arrive) // 60} min")
            self.say(a, "Going home")
            yield ("go", "ed", ed.spots["walkin"][0])

    def allocate_ward_beds(self) -> None:
        if not self.pending_admit:
            return
        self.pending_admit.sort(key=lambda x: (x[0], x[1]))
        for item in list(self.pending_admit):
            _, _, a, rec, cause = item
            bed = next((b for b in self.beds.values() if b.unit == "ward" and b.state == "ready"
                        and b.known_ready is not None and b.known_ready <= self.t), None)
            if bed is None:
                return
            self.bed_state(bed, "reserved", rec["id"], cause, f"{bed.id} reserved for {rec['name']}")
            a.ward_bed, rec["ward_bed"] = bed.id, bed.id
            self.pending_admit.remove(item)

    def par_level(self) -> None:
        """Connected: keep at least two free pumps in the ED by fetching them back from the ward."""
        if not self.conn:
            return
        pending = sum(1 for tk in self.open if tk.kind == "pump_retrieve")
        if len(self.free_assets("pump", "ed")) + pending < 2 and len(self.free_assets("pump", "ward")) > pending:
            m = self.bus.publish("hospital/ed/pumps/below_par", len(self.free_assets("pump", "ed")), None,
                                 "ED below par on infusion pumps — porter sent to the ward")
            self.task("pump_retrieve", "ed", STORE["ed"], 3, 0, "porter", visible=self.t, asset="pump_retrieve",
                      cause=m.id, meta={"label": "Bring a pump back from the ward"})

    # ---------------------------------------------------------------- the day
    def _staff_agent(self, s) -> Agent:
        a = Agent(s.id, s.name, s.role, s.unit, s.speed)
        a.end = s.end
        plan = self.plans[s.unit]
        idx = int(s.id[-1]) - 1 if s.id[-1].isdigit() else int(s.id[-2]) - 1
        if s.role == "nurse" and s.unit == "ed" and idx == 0:
            a.skill = "triage"
            a.base = plan.spots["triage_nurse"][0]
        elif s.role == "nurse" and s.unit == "ed" and idx == 3:
            a.skill = "triage"
            a.base = plan.spots["triage_nurse"][1]
        else:
            key = {"nurse": "nurse_station", "doctor": "doctor_desk", "clerk": "reg_desk_staff", "porter": "porter_base",
                   "cleaner": "cleaner_base", "radiographer": "xray_staff", "guard": "guard_post"}[s.role]
            pts = plan.spots[key]
            a.base = tuple(pts[idx % len(pts)])
        return a

    def run(self) -> "HospitalSim":
        sc, ed, ward = self.sc, self.plans["ed"], self.plans["ward"]
        starts = sorted(sc.staff, key=lambda s: max(0, s.start))
        arrivals = list(sc.ed_patients)
        calls, alarms = list(sc.calls), list(sc.alarms)
        fridge = list(sc.fridge_open)
        # the ward at midnight
        for bid, b in self.beds.items():
            self.bed_ev.append([0, bid, b.state])
        for wp in sc.ward_patients:
            bed = self.beds[wp.bed]
            self.bed_state(bed, "occupied", wp.id)
            a = Agent(wp.id, wp.name, "patient", "ward", 0.8)
            self.ward_patients[wp.id] = wp
            self.spawn(a, "ward", bed.spot, self.ward_patient(a, wp, bed))
        for x in self.assets.values():
            self.asset_moved(x)
        si = ai = ci = li = fi = 0
        for t in range(DAY):
            self.t = self.bus.now = t
            while si < len(starts) and max(0, starts[si].start) <= t:
                s = starts[si]
                si += 1
                if s.end <= 0:
                    continue
                a = self._staff_agent(s)
                plan = self.plans[s.unit]
                where = a.base if s.start <= 0 else plan.spots["campus_exit" if s.unit == "ed" else "entry"][0]
                self.spawn(a, s.unit, where, self.staff_loop(a))
            while ai < len(arrivals) and arrivals[ai].arrive <= t:
                p = arrivals[ai]
                ai += 1
                a = Agent(p.id, p.name, "patient", "ed", p.speed)
                self.spawn(a, "ed", ed.spots["ambulance_bay" if p.ambulance else "walkin"][0], self.ed_patient(a, p))
            while ci < len(calls) and calls[ci].t <= t:
                self.ward_call(calls[ci])
                ci += 1
            while li < len(alarms) and alarms[li].t <= t:
                self.ward_alarm(alarms[li])
                li += 1
            while fi < len(fridge) and fridge[fi][1] <= t:
                key = fridge[fi][0]
                fi += 1
                fr = self.fridges[key]
                fr["open"] = True
                m = self.bus.publish(f"hospital/{key}/fridge/door", "ajar", None, f"{key.title()} medicine fridge door left ajar")
                self.fridge_events.append(dict(fridge=key, opened=t, closed=None, by=None, alerted=None, peak=fr["temp"],
                                               minutes_over=0, cause=m.id))
            for rec in self.alarm_log:
                if rec.get("pending_until") == t:
                    rec.pop("pending_until")
                    if rec["dur"] > ALARM_DELAY:
                        self._alarm_task(rec, rec["cause"])
                    else:
                        rec["hidden"] = True
            if t % 5 == 0:
                self.assign_nurses()
                if not self.conn:
                    self.notice_calls()
                self.allocate_ward_beds()
            if t % 600 == 0:
                self.par_level()
                if not self.conn and t in (8 * H, 20 * H):
                    for key, fr in self.fridges.items():
                        self.task("fridge_log", key, fr["spot"], 4, 60, "nurse", visible=t,
                                  meta={"label": "Fridge temperature log"})
                if t in (6 * H, 14 * H, 22 * H):
                    for b in self.beds.values():
                        if b.unit == "ward" and b.state == "occupied":
                            self.task("vitals", "ward", b.spot, 4, 120, "nurse", visible=t,
                                      assignee=self.nurse_beds.get(b.id) if self.conn else None,
                                      meta={"label": f"Vitals {b.id}"})
                if t in (9 * H, 13 * H, 21 * H):
                    self.task("meds", "ward", ward.spots["meds_fridge"][0], 3, 300, "nurse", visible=t,
                              meta={"label": "Medicine round: fetch from the store"})
                if t == 9 * H:
                    for b in self.beds.values():
                        if b.unit == "ward" and b.state == "occupied":
                            self.task("round", "ward", b.spot, 5, 180, "doctor", visible=t, meta={"label": f"Ward round {b.id}"})
            if t % 60 == 0:
                self.fridge_tick()
                self._census()
            for a in list(self.agents.values()):
                if a.on:
                    if a.carrying:
                        x = self.assets[a.carrying]
                        x["pos"], x["building"] = a.pos, a.building
                    self._step(a)
        self.t = self.bus.now = DAY - 1
        return self

    def _census(self) -> None:
        ed_in = sum(1 for r in self.records.values() if r["left"] is None)
        waiting = sum(1 for r in self.records.values() if r["left"] is None and r["seen"] is None)
        board = sum(1 for it in self.pending_admit)
        self.census.append([self.t, ed_in, waiting, board,
                            sum(1 for b in self.beds.values() if b.unit == "ward" and b.state == "occupied"),
                            sum(1 for b in self.beds.values() if b.unit == "ward" and b.state in ("dirty", "cleaning"))])

    # ---------------------------------------------------------------- results
    def metrics(self) -> dict:
        def med(xs):
            return round(statistics.median(xs) / 60, 1) if xs else None

        def p90(xs):
            if not xs:
                return None
            xs = sorted(xs)
            return round(xs[min(len(xs) - 1, int(0.9 * len(xs)))] / 60, 1)

        recs = list(self.records.values())
        walk = [r for r in recs if not r["ambulance"] and r["triaged"]]
        seen = [r for r in recs if r["seen"]]
        done = [r for r in recs if r["left"] is not None and r["outcome"] != "left unseen"]
        for c in self.call_log:
            tk = next((t for t in self.tasks if t.kind == "call" and t.meta.get("rec") is c), None)
            if tk and tk.arrived:
                c["arrived"] = tk.arrived
        calls = [c["arrived"] - c["t"] for c in self.call_log if c.get("arrived")]
        for r in self.alarm_log:
            if r.get("task") is not None and r["task"].arrived:
                r["arrived"] = r["task"].arrived
        true_resp = [r["arrived"] - r["t"] for r in self.alarm_log if r["kind"] in ("sustained", "critical") and r.get("arrived")]
        crit = [r["arrived"] - r["t"] for r in self.alarm_log if r["kind"] == "critical" and r.get("arrived")]
        annunciated = [r for r in self.alarm_log if r["annunciated"] is not None]
        nurse_hours = sum((min(DAY, max(0, s.end)) - max(0, s.start)) for s in self.sc.staff
                          if s.unit == "ward" and s.role == "nurse") / H
        found = [f for f in self.fetch_log if f["found"]]
        hh = self.hh
        audited = [h for h in hh if h["observed"]]
        detected = [h for h in hh if h["detected"]]
        fr = self.fridge_events
        turn = [b["ready"] - b["dirty"] for b in self.bed_log if b["unit"] == "ward" and b["ready"]]
        ward_nurses = [a for a in self.agents.values() if a.unit == "ward" and a.role == "nurse"]
        out = {
            "ed_arrivals": len(recs),
            "door_to_triage_min": med([r["triaged"] - r["arrive"] for r in walk]),
            "door_to_doctor_min": {c: med([r["seen"] - r["arrive"] for r in seen if r["colour"] == c])
                                   for c in ("red", "orange", "yellow", "green", "blue")},
            "door_to_doctor_all_min": med([r["seen"] - r["arrive"] for r in seen]),
            "los_min": med([r["left"] - r["arrive"] for r in done]),
            "left_unseen": sum(1 for r in recs if r["outcome"] == "left unseen"),
            "still_in_ed": sum(1 for r in recs if r["left"] is None),
            "admitted": sum(1 for r in recs if r["outcome"] == "admitted"),
            "boarding_min": med([r["boarding"] for r in recs if r["boarding"] is not None]),
            # everyone told "admit", including those still waiting at midnight
            "boarding_hours": round(sum(((r["left"] or DAY) - r["decision"]) for r in recs if r["decision"]) / H, 1),
            "red_consults_paused": sum(t.meta.get("paused", 0) for t in self.tasks),
            "waiting_for_bed_at_midnight": len(self.pending_admit),
            "call_response_min": med(calls), "call_response_p90_min": p90(calls), "calls": len(self.call_log),
            "alarms_raised": len(self.alarm_log), "alarms_sounded": len(annunciated),
            "alarms_per_nurse_hour": round(len(annunciated) / nurse_hours, 2) if nurse_hours else None,
            "false_alarm_trips": sum(1 for r in annunciated if r["kind"] == "artefact"),
            "true_alarm_response_min": med(true_resp), "critical_response_s": [int(x) for x in crit],
            "brief_true_events_not_sounded": sum(1 for r in self.alarm_log if r["kind"] == "brief" and r.get("hidden")),
            "equipment_fetches": len(found),
            "drips_without_pump": sum(1 for t in self.tasks if t.kind == "drip" and t.meta.get("no_pump")),
            "drips": sum(1 for t in self.tasks if t.kind == "drip"), "equipment_not_found": sum(1 for f in self.fetch_log if not f["found"]),
            "equipment_fetch_min_total": round(sum(f["secs"] for f in self.fetch_log) / 60, 1),
            "equipment_search_min": round(sum(max(0, f["secs"] - f["direct"]) for f in found) / 60, 1),
            "ed_free_pumps_at_end": len(self.free_assets("pump", "ed")),
            "hand_hygiene_true_pct": round(100 * sum(h["washed"] for h in hh) / len(hh), 1) if hh else None,
            "hand_hygiene_reported_pct": (round(100 * sum(h["washed"] for h in audited) / len(audited), 1) if audited else None)
            if not self.conn else (round(100 * sum(h["washed"] for h in detected) / len(detected), 1) if detected else None),
            "hand_hygiene_reported_n": len(audited) if not self.conn else len(detected),
            "hand_hygiene_opportunities": len(hh),
            "fridge_minutes_over_8C": sum(e["minutes_over"] for e in fr),
            "fridge_open_min": [((e["closed"] or DAY) - e["opened"]) // 60 for e in fr],
            "bed_turnaround_min": med(turn),
            "ward_nurse_km": round(sum(a.walked for a in ward_nurses) / 1000, 1),
        }
        return out


def run_mode(sc, ed, ward, mode) -> HospitalSim:
    return HospitalSim(sc, ed, ward, mode).run()
