"""The simulation loop: one second per tick, 07:00 to 21:00.

People move, sensors read the world (with their real failure modes), sensors
publish on the bus, rules react, actuators change the world. The simulator is
the only thing that knows the truth; it keeps it separately so every metric
compares what the building *believed* with what actually happened.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field

from .bus import Bus, Message
from .devices import RoomEnv, outdoor_temp
from .office import Scenario, clock, hm
from .people import ROLE_COLOURS, Person, Stay
from .plan import path_length
from .rules import Attendance, Automation

T0, T1 = hm("07:00"), hm("21:00")
P_MOVING = 0.9          # PIR detects a walking person in a given second
P_STILL = 1 / 300       # ... a person sitting still (typing, reading)
PIR_BLIND = 5           # seconds a PIR stays latched after a trigger
PHYS_DT = 10
SAMPLE_DT = 60


@dataclass
class Truth:
    tailgates: list = field(default_factory=list)       # (t, person)
    beam_misses: int = 0
    passes_in: int = 0
    present_secs: dict = field(default_factory=dict)


class Sim:
    def __init__(self, scenario: Scenario, mode: str, seed: int | None = None):
        self.sc = scenario
        self.plan = scenario.plan
        self.mode = mode
        seed = scenario.seed if seed is None else seed
        # one stream for people (identical across modes), one for sensors
        self.rng_people = random.Random(seed * 1000 + 1)
        self.rng_sense = random.Random(seed * 1000 + 2)
        self.people: list[Person] = copy.deepcopy(scenario.people)
        self.by_id = {p.id: p for p in self.people}
        self.bus = Bus()
        self.auto = Automation(self.bus, self.plan, mode, scenario.bookings)
        self.att = Attendance(self.bus, self.by_id)
        self.env = {
            rid: RoomEnv(rid, r.kind, r.area, rid in self.plan.ac_rooms)
            for rid, r in self.plan.rooms.items() if r.kind != "outdoor"
        }
        self.light = {rid: False for rid in self.env}
        self.ac = {rid: False for rid in self.env}
        self.bus.subscribe("office/+/light", self._on_light)
        self.bus.subscribe("office/+/ac", self._on_ac)
        self.bus.subscribe("office/+/vent", self._on_vent)

        self.truth = Truth()
        self.trips: list[dict] = []
        self.labels: list[list] = []
        self.cars: list[dict] = []
        self.dev_changes: list[list] = []
        self.series = {"t": [], "light_kw": [], "ac_kw": [], "out_temp": [], "on_site": [],
                       "occ": {r: [] for r in self.env}, "temp": {r: [] for r in self.env},
                       "co2": {r: [] for r in self.env}}
        self.energy = {"light_kwh": 0.0, "ac_kwh": 0.0}
        self.metrics_acc = {"dark_person_s": 0, "hot_person_s": 0, "empty_lit_s": 0,
                            "false_off": 0, "stuffy_person_s": 0}
        self.queue: list[str] = []
        self.serving: tuple[str, int] | None = None
        self.seat_taken: dict[tuple, str] = {}
        self.pir_latch: dict[str, int] = {}
        self.last_in_pass = -10**9
        self.last_beam = -10**9
        self.ac_w = {rid: 0.0 for rid in self.env}
        self.queue_reported = 0

    # ---- actuator subscriptions ----------------------------------------

    def _on_light(self, m: Message) -> None:
        rid = m.topic.split("/")[1]
        if rid in self.light:
            if not m.payload and self._occupancy().get(rid, 0) > 0:
                self.metrics_acc["false_off"] += 1
            self.light[rid] = bool(m.payload)
            self.dev_changes.append([m.t, rid, "light", int(bool(m.payload)), m.id])

    def _on_ac(self, m: Message) -> None:
        rid = m.topic.split("/")[1]
        if rid in self.ac:
            self.ac[rid] = bool(m.payload)
            self.dev_changes.append([m.t, rid, "ac", int(bool(m.payload)), m.id])

    def _on_vent(self, m: Message) -> None:
        rid = m.topic.split("/")[1]
        if rid in self.env:
            self.env[rid].vent_boost = bool(m.payload)
            self.dev_changes.append([m.t, rid, "vent", int(bool(m.payload)), m.id])

    # ---- people ---------------------------------------------------------

    def _occupancy(self) -> dict[str, int]:
        occ: dict[str, int] = {}
        for p in self.people:
            if p.on_site and p.room:
                occ[p.room] = occ.get(p.room, 0) + 1
        return occ

    def _walk(self, p: Person, goal, t: int, label: str | None = None) -> None:
        if label:
            self._label(p, t, label)
        pts = self.plan.route(p.pos, goal)
        if len(pts) < 2 or path_length(pts) < 0.05:
            p.path = []
            p.pos = goal
            self._arrived(p, t)
            return
        p.set_path(pts)
        p.mode = "walking" if p.mode not in ("queue", "eat", "round") else p.mode
        self.trips.append({"p": p.id, "t": t, "v": round(p.speed, 3),
                           "pts": [[round(x, 2), round(y, 2)] for x, y in pts]})

    def _label(self, p: Person, t: int, label: str) -> None:
        if p.label != label:
            p.label = label
            self.labels.append([t, p.id, label])

    def _start_stay(self, p: Person, s: Stay, t: int) -> None:
        self._leave_lunch(p)
        if s.kind == "lunch":
            p.mode = "queue"
            self.queue.append(p.id)
            self._label(p, t, "Lunch queue")
            return
        if s.kind == "round":
            p.mode = "round"
            p.round_left = list(s.stops)
            self._label(p, t, s.label)
            self._next_round_stop(p, t)
            return
        p.mode = "walking"
        self._walk(p, s.spot, t, s.label)

    def _leave_lunch(self, p: Person) -> None:
        if p.id in self.queue:
            self.queue.remove(p.id)
        if self.serving and self.serving[0] == p.id:
            self.serving = None
        for seat, who in list(self.seat_taken.items()):
            if who == p.id:
                del self.seat_taken[seat]

    def _next_round_stop(self, p: Person, t: int) -> None:
        if not p.round_left:
            p.mode = "walking"
            self._walk(p, p.desk, t)
            return
        spot, dwell = p.round_left.pop(0)
        p.hold_until = -1
        p._dwell = dwell
        self._walk(p, tuple(spot), t)

    def _arrived(self, p: Person, t: int) -> None:
        s = p.day[p.idx] if 0 <= p.idx < len(p.day) else None
        if p.mode == "round":
            p.hold_until = t + getattr(p, "_dwell", 10)
            return
        if p.mode == "eat":
            return
        if p.mode == "queue":
            return
        p.mode = "idle"
        if s is None:
            return
        if s.kind == "leave":
            p.on_site = False
            p.gone = True
            p.room = None
            self._label(p, t, "Gone home")
            for c in self.cars:
                if c["p"] == p.id and c.get("out") is None:
                    c["out"] = t
                    self.bus.publish(f"office/parking/bay{c['bay'] + 1}", False, None,
                                     f"Bay {c['bay'] + 1} free")
            return
        if s.on_arrive == "manual_checkin":
            self.bus.publish("office/reception/manual", p.id, None,
                             f"Reception checked in {p.name} by hand (forgot badge)")
        elif s.on_arrive == "kiosk_checkin":
            self.bus.publish("office/lobby/kiosk", p.id, None, f"Visitor {p.name} checked in at the kiosk")

    def _step_person(self, p: Person, t: int) -> None:
        if p.gone:
            return
        if not p.on_site:
            if t < p.arrive:
                return
            p.on_site = True
            p.pos = p.entry
            p.room = self.plan.room_at(*p.entry)
            if p.car_bay is not None:
                self.cars.append({"p": p.id, "bay": p.car_bay, "in": t - 25, "out": None})
                self.bus.publish(f"office/parking/bay{p.car_bay + 1}", True, None,
                                 f"Bay {p.car_bay + 1} taken")
            self._label(p, t, "Arriving")
        while p.idx + 1 < len(p.day) and p.day[p.idx + 1].t <= t:
            p.idx += 1
            self._start_stay(p, p.day[p.idx], t)
        if p.path:
            old = p.room
            done = p.advance(1.0)
            new = self.plan.room_at(*p.pos)
            if new is not None and new != old:
                p.room = new
                self._room_change(p, old, new, t)
            if done:
                self._arrived(p, t)
        elif p.mode == "round" and p.hold_until >= 0 and t >= p.hold_until:
            self._next_round_stop(p, t)
        elif p.mode == "eat" and t >= p.hold_until:
            self._leave_lunch(p)
            p.mode = "walking"
            self._walk(p, p.desk, t, _home(p))

    def _room_change(self, p: Person, old: str | None, new: str, t: int) -> None:
        if {old, new} != {"lobby", "corr1"}:
            return
        direction = "in" if old == "lobby" else "out"
        if direction == "in":
            self.truth.passes_in += 1
            tailgate = False
            if p.has_badge and t - self.last_in_pass <= 4 and self.rng_people.random() < 0.3:
                tailgate = True
                self.truth.tailgates.append((t, p.id))
            close = t - self.last_in_pass <= 1
            self.last_in_pass = t
            if p.has_badge and not tailgate:
                self.bus.publish("office/gate/badge", {"person": p.id, "dir": "in"}, None,
                                 f"{p.name} badged in")
            # the beam: misses ~1%, and merges two people passing within a second half the time
            missed = self.rng_sense.random() < 0.01 or (close and self.rng_sense.random() < 0.5)
            if missed:
                self.truth.beam_misses += 1
            else:
                self.bus.publish("office/gate/beam", "in", None, "Door counter: 1 in")
            if self.rng_sense.random() < 0.004:      # someone lingers in the doorway
                self.bus.publish("office/gate/beam", "in", None, "Door counter: 1 in")
        else:
            if self.rng_people.random() < p.badge_out_habit and p.has_badge:
                self.bus.publish("office/gate/badge", {"person": p.id, "dir": "out"}, None,
                                 f"{p.name} badged out")
            if self.rng_sense.random() > 0.01:
                self.bus.publish("office/gate/beam", "out", None, "Door counter: 1 out")

    def _step_queue(self, t: int) -> None:
        spots = self.plan.spots["queue"]
        for i, pid in enumerate(self.queue):
            p = self.by_id[pid]
            target = tuple(spots[min(i, len(spots) - 1)])
            if getattr(p, "_qtarget", None) != target:
                p._qtarget = target
                self._walk(p, target, t)
        if self.queue:
            head = self.by_id[self.queue[0]]
            at_counter = not head.path
            if self.serving is None and at_counter:
                self.serving = (head.id, t + self.rng_people.randint(40, 90))
            elif self.serving and self.serving[0] == head.id and t >= self.serving[1]:
                self.serving = None
                self.queue.pop(0)
                head._qtarget = None
                seats = [tuple(s) for s in self.plan.spots["cafe_seat"] if tuple(s) not in self.seat_taken]
                head.mode = "eat"
                eat = self.rng_people.randint(900, 1500)
                if seats:
                    seat = self.rng_people.choice(seats)
                    self.seat_taken[seat] = head.id
                    head.hold_until = t + eat
                    self._walk(head, seat, t, "Eating lunch")
                else:      # no seat: eat at the desk
                    head.hold_until = t
                    self._label(head, t, "Took lunch to desk")
        n = len(self.queue)
        if n != self.queue_reported:
            self.queue_reported = n
            self.bus.publish("office/cafe/queue", n, None, f"Cafeteria queue: {n}")

    # ---- sensors --------------------------------------------------------

    def _pir(self, t: int) -> None:
        moving: dict[str, int] = {}
        still: dict[str, float] = {}     # sum of 1/still_bias: a stiller sitter counts for less
        for p in self.people:
            if not (p.on_site and p.room):
                continue
            if p.path:
                moving[p.room] = moving.get(p.room, 0) + 1
            else:
                still[p.room] = still.get(p.room, 0.0) + 1.0 / p.still_bias
        for rid in sorted(set(moving) | set(still)):   # sorted: set order varies per process
            if rid not in self.env:
                continue
            if t < self.pir_latch.get(rid, -1):
                continue
            miss = (1 - P_MOVING) ** moving.get(rid, 0)
            miss *= (1 - P_STILL) ** still.get(rid, 0.0)
            if self.rng_sense.random() > miss:
                self.pir_latch[rid] = t + PIR_BLIND
                self.bus.publish(f"office/{rid}/motion", 1)

    def _physics(self, t: int) -> None:
        occ = self._occupancy()
        for rid, env in self.env.items():
            self.ac_w[rid] = env.step(PHYS_DT, t, occ.get(rid, 0), self.light[rid], self.ac[rid])
        light_w = sum(env.light_watts for rid, env in self.env.items() if self.light[rid])
        self.energy["light_kwh"] += light_w * PHYS_DT / 3.6e6
        self.energy["ac_kwh"] += sum(self.ac_w.values()) * PHYS_DT / 3.6e6
        for rid, n in occ.items():
            if rid not in self.env or n == 0:
                continue
            if not self.light[rid]:
                self.metrics_acc["dark_person_s"] += n * PHYS_DT
            if rid in self.plan.ac_rooms and self.env[rid].temp > 26.0:
                self.metrics_acc["hot_person_s"] += n * PHYS_DT
            if self.env[rid].co2 > 1000:
                self.metrics_acc["stuffy_person_s"] += n * PHYS_DT
        for rid in self.env:
            if self.light[rid] and occ.get(rid, 0) == 0:
                self.metrics_acc["empty_lit_s"] += PHYS_DT

    def _report(self, t: int) -> None:
        occ = self._occupancy()
        for rid, env in self.env.items():
            if rid in self.plan.ac_rooms:
                self.bus.publish(f"office/{rid}/co2", round(env.co2 + self.rng_sense.gauss(0, 10), 1))
                self.bus.publish(f"office/{rid}/temp", round(env.temp + self.rng_sense.gauss(0, 0.15), 2))
        s = self.series
        s["t"].append(t)
        s["light_kw"].append(round(sum(e.light_watts for r, e in self.env.items() if self.light[r]) / 1000, 3))
        s["ac_kw"].append(round(sum(self.ac_w.values()) / 1000, 3))
        s["out_temp"].append(round(outdoor_temp(t), 2))
        s["on_site"].append(sum(1 for p in self.people if p.on_site))
        for rid, env in self.env.items():
            s["occ"][rid].append(occ.get(rid, 0))
            s["temp"][rid].append(round(env.temp, 2))
            s["co2"][rid].append(round(env.co2))

    # ---- run ------------------------------------------------------------

    def run(self, t0: int = T0, t1: int = T1) -> "Sim":
        for p in self.people:
            p.pos = p.entry
        for t in range(t0, t1):
            self.bus.now = t
            for p in self.people:
                self._step_person(p, t)
                if p.on_site:
                    self.truth.present_secs[p.id] = self.truth.present_secs.get(p.id, 0) + 1
            self._step_queue(t)
            self._pir(t)
            if t % PHYS_DT == 0:
                self._physics(t)
            if t % SAMPLE_DT == 0:
                self._report(t)
            if t % 5 == 0:
                self.auto.tick(t)
                self.att.tick(t)
            elif t in (hm("08:30"), hm("18:30")):
                self.auto.tick(t)
        self.bus.now = t1
        self.att.tick(t1 + 10)
        self.att.finish(t1)
        return self

    # ---- results --------------------------------------------------------

    def metrics(self) -> dict:
        m = self.metrics_acc
        staff = [p for p in self.people if p.role in ("staff", "manager")]
        truly_in = {p.id for p in self.people if p.id in self.truth.present_secs and p.role != "visitor"}
        register = set(self.att.checkin) - {p.id for p in self.people if p.role == "visitor"}
        tg_true = [t for t, _ in self.truth.tailgates]
        caught = sum(1 for t in tg_true if any(abs(a - t) <= 6 for a in self.att.tailgate_alerts))
        false_alarms = sum(1 for a in self.att.tailgate_alerts if not any(abs(a - t) <= 6 for t in tg_true))
        alerts: dict[str, int] = {}
        for msg in self.bus.log:
            if msg.topic.startswith("office/alert/"):
                k = msg.topic.split("/")[2]
                alerts[k] = alerts.get(k, 0) + 1
        return {
            "mode": self.mode,
            "light_kwh": round(self.energy["light_kwh"], 2),
            "ac_kwh": round(self.energy["ac_kwh"], 2),
            "total_kwh": round(self.energy["light_kwh"] + self.energy["ac_kwh"], 2),
            "person_min_in_dark": round(m["dark_person_s"] / 60),
            "person_min_too_warm": round(m["hot_person_s"] / 60),
            "person_min_stuffy": round(m["stuffy_person_s"] / 60),
            "room_min_lit_empty": round(m["empty_lit_s"] / 60),
            "false_offs": m["false_off"],
            "people_on_site": len(truly_in),
            "register_count": len(register),
            "missing_from_register": sorted(truly_in - register),
            "tailgates_true": len(tg_true),
            "tailgates_caught": caught,
            "tailgate_false_alarms": false_alarms,
            "beam_misses": self.truth.beam_misses,
            "staff": len(staff),
            "alerts": alerts,
        }

    def replay_mode(self) -> dict:
        """Device timeline, log and series for this rule set."""
        return {
            "metrics": self.metrics(),
            "devices": self.dev_changes,
            "log": [{"id": m.id, "t": m.t, "topic": m.topic, "text": m.text, "cause": m.cause,
                     **({"payload": m.payload} if isinstance(m.payload, (int, float, str)) else {})}
                    for m in self.bus.log],
            "series": self.series,
            "register": {pid: {"in": self.att.checkin.get(pid), "out": self.att.checkout.get(pid)}
                         for pid in self.by_id},
        }

    def replay_people(self) -> dict:
        """What is identical across rule sets: people, trips, labels, cars."""
        return {
            "people": [{"id": p.id, "name": p.name, "role": p.role, "colour": ROLE_COLOURS[p.role],
                        "arrive": p.arrive, "leave": p.leave, "badge": p.has_badge,
                        "car": p.car_bay} for p in self.people],
            "trips": self.trips,
            "labels": self.labels,
            "cars": self.cars,
            "tailgates": self.truth.tailgates,
        }


def _home(p: Person) -> str:
    return {"staff": "At desk", "manager": "In cabin", "receptionist": "At reception",
            "office_boy": "In pantry", "guard": "At guard post", "cleaner": "In store room"}.get(p.role, "Here")
