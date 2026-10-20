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
MANUAL_AC_ABOVE = 26.5  # °C at which a settled person reaches for the AC remote
MANUAL_AC_AFTER = 300   # ... after this long
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
        # separate streams so a rule set can never change what happens elsewhere:
        # people and the gate are identical across rule sets; room sensors may differ
        self.rng_people = random.Random(seed * 1000 + 1)
        # three sensor streams, so one rule set's choices (a light it kept on, someone waving)
        # cannot reshuffle another sensor's noise: motion misses stay matched across rule sets
        self.rng_sense = random.Random(seed * 1000 + 2)          # motion-sensor misses
        self.rng_wave = random.Random(seed * 1000 + 4)           # how soon someone waves at a dark room
        self.rng_env = random.Random(seed * 1000 + 5)            # CO2 and temperature reading noise
        self.rng_gate = random.Random(seed * 1000 + 3)
        self.people: list[Person] = copy.deepcopy(scenario.people)
        self.by_id = {p.id: p for p in self.people}
        for p in self.people:
            p.pos = p.entry
        self.bus = Bus()
        self.auto = Automation(self.bus, self.plan, mode, scenario.bookings)
        self.att = Attendance(self.bus, self.by_id, self.plan.operations.get("manual_checkin_gate"))
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
                       "roll_truth": [], "roll_counter": [], "roll_register": [], "roll_estimate": [],
                       "kwh": [],
                       "occ": {r: [] for r in self.env}, "temp": {r: [] for r in self.env},
                       "co2": {r: [] for r in self.env}}
        self.energy = {"light_kwh": 0.0, "ac_kwh": 0.0}
        self.metrics_acc = {"dark_person_s": 0, "hot_person_s": 0, "empty_lit_s": 0,
                            "false_off": 0, "stuffy_person_s": 0, "manual_on": 0, "manual_ac": 0}
        self.queue: list[str] = []
        self.serving: tuple[str, int] | None = None
        self.seat_taken: dict[tuple, str] = {}
        self.claimed: dict[tuple, str] = {}
        self.pir_latch: dict[str, int] = {}
        self.last_in_pass: dict[str, int] = {}
        self.badge_doors = {frozenset((d.a, d.b)): d for d in self.plan.doors if d.gate == "badge"}
        self.last_beam = -10**9
        self.ac_w = {rid: 0.0 for rid in self.env}
        self.queue_reported = 0
        self._finished = False

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
        if s.kind != "stay":
            self._release(p)
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
        self._walk(p, self._claim(p, s), t, s.label)

    def _claim(self, p: Person, s: Stay):
        """A free spot from the stay's pool, so two people never stand on one point."""
        self._release(p)
        if not s.pool:
            return s.spot
        free = [tuple(q) for q in self.plan.spots[s.pool] if tuple(q) not in self.claimed]
        if not free:
            return s.spot          # all taken: wait at the first one (a queue for the stall)
        spot = self.rng_people.choice(free)
        self.claimed[spot] = p.id
        return spot

    def _release(self, p: Person) -> None:
        for spot, who in list(self.claimed.items()):
            if who == p.id:
                del self.claimed[spot]

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
            if p.role == "guard":
                self.bus.publish("office/guard_post/clock", {"person": p.id, "dir": "out"}, None,
                                 f"{p.name} clocked out at the guard post")
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
        if s.on_arrive == "clock_in":
            self.bus.publish("office/guard_post/clock", {"person": p.id, "dir": "in"}, None,
                             f"{p.name} clocked in at the guard post")
        elif s.on_arrive == "manual_checkin":
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
        """Badge readers and beam counters sit on every door marked gate=badge.

        A door's ``a`` side is public and ``b`` is secure, so a->b is "in".
        """
        door = self.badge_doors.get(frozenset((old, new)))
        if door is None:
            return
        gate = door.b
        where = door.name
        if old == door.a:
            self.truth.passes_in += 1
            last = self.last_in_pass.get(gate, -10**9)
            tailgate = False
            if p.has_badge and t - last <= 4 and self.rng_people.random() < 0.3:
                tailgate = True
                self.truth.tailgates.append((t, p.id))
            close = t - last <= 1
            self.last_in_pass[gate] = t
            if p.has_badge and not tailgate:
                self.bus.publish("office/gate/badge", {"person": p.id, "dir": "in", "gate": gate}, None,
                                 f"{p.name} badged in ({where})")
            # the beam: misses ~1%, and merges two people passing within a second half the time
            missed = self.rng_gate.random() < 0.01 or (close and self.rng_gate.random() < 0.5)
            if missed:
                self.truth.beam_misses += 1
            else:
                self.bus.publish("office/gate/beam", {"dir": "in", "gate": gate}, None,
                                 f"Door counter ({where}): 1 in")
            if self.rng_gate.random() < 0.004:      # someone lingers in the doorway
                self.bus.publish("office/gate/beam", {"dir": "in", "gate": gate}, None,
                                 f"Door counter ({where}): 1 in")
        else:
            if self.rng_people.random() < p.badge_out_habit and p.has_badge:
                self.bus.publish("office/gate/badge", {"person": p.id, "dir": "out", "gate": gate}, None,
                                 f"{p.name} badged out ({where})")
            if self.rng_gate.random() > 0.01:
                self.bus.publish("office/gate/beam", {"dir": "out", "gate": gate}, None,
                                 f"Door counter ({where}): 1 out")

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
            if p.path or getattr(p, "wave_at", -1) == t:
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

    def _people_too_warm(self, t: int) -> None:
        """Someone settled in a warm room with the AC off reaches for the remote.

        Every rule set gets the same remote, so the schedule's 18:30 AC switch-off
        does not leave overtime staff sweltering by construction.
        """
        for p in self.people:
            rid = p.room
            if not (p.on_site and rid in self.plan.ac_rooms) or p.path or self.ac.get(rid):
                p.warm_since = None
                continue
            if self.env[rid].temp <= MANUAL_AC_ABOVE:
                p.warm_since = None
                continue
            if getattr(p, "warm_since", None) is None:
                p.warm_since = t
            elif t - p.warm_since >= MANUAL_AC_AFTER:
                p.warm_since = None
                self.metrics_acc["manual_ac"] += 1
                self.bus.publish(f"office/{rid}/ac_switch", True, None,
                                 f"{p.name} turned the AC on by hand in {self.plan.rooms[rid].name} "
                                 f"({self.env[rid].temp:.1f} °C)")

    def _people_in_the_dark(self, t: int) -> None:
        """Someone settled in a dark room waves first, then uses the wall switch.

        Every rule set gets the same wall switches, so the fixed schedule is not a
        straw man where early arrivals sit in the dark until 08:30.
        """
        for p in self.people:
            if not (p.on_site and p.room in self.light) or p.path:
                p.dark_since = None
                continue
            if self.light[p.room]:
                p.dark_since = None
                continue
            if getattr(p, "dark_since", None) is None:
                p.dark_since = t
                p.wave_at = t + self.rng_wave.randint(5, 20)
            elif t - p.dark_since >= 30:
                p.dark_since = None
                self.metrics_acc["manual_on"] += 1
                self.bus.publish(f"office/{p.room}/switch", True, None,
                                 f"{p.name} switched the lights on by hand in {self.plan.rooms[p.room].name}")

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
                self.bus.publish(f"office/{rid}/co2", round(env.co2 + self.rng_env.gauss(0, 10), 1))
                self.bus.publish(f"office/{rid}/temp", round(env.temp + self.rng_env.gauss(0, 0.15), 2))
        s = self.series
        s["t"].append(t)
        s["light_kw"].append(round(sum(e.light_watts for r, e in self.env.items() if self.light[r]) / 1000, 3))
        s["ac_kw"].append(round(sum(self.ac_w.values()) / 1000, 3))
        s["out_temp"].append(round(outdoor_temp(t), 2))
        s["on_site"].append(sum(1 for p in self.people if p.on_site))
        s["kwh"].append(round(self.energy["light_kwh"] + self.energy["ac_kwh"], 3))
        for rid, env in self.env.items():
            s["occ"][rid].append(occ.get(rid, 0))
            s["temp"][rid].append(round(env.temp, 2))
            s["co2"][rid].append(round(env.co2))
        # roll-call scope: behind the badge doors (everything but the car park and lobby)
        s["roll_truth"].append(sum(n for r, n in occ.items() if r not in ("parking", "lobby")))
        s["roll_counter"].append(self.att.counted_inside)
        s["roll_register"].append(self.att.register_inside())
        s["roll_estimate"].append(self.att.estimate_inside())
        self.att.rollcall_tick(t)

    # ---- run ------------------------------------------------------------

    def run(self, t0: int = T0, t1: int = T1, on_tick=None) -> "Sim":
        """Simulate t0..t1. ``on_tick(t)`` runs after every second (live mode paces and polls MQTT there).

        Calling it again continues from where the last call stopped."""
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
                self._people_in_the_dark(t)
                self._people_too_warm(t)
                self.auto.tick(t)
                self.att.tick(t)
            if on_tick is not None:
                on_tick(t)
        if t1 >= T1:
            self.finish()
        return self

    def finish(self) -> None:
        """Close the day: reconcile the last gate passes and flag missing badge-outs.

        Stamped at the last second of the day so the viewer's timeline can show it;
        live mode, which runs the day in pieces, closes it only once.
        """
        if self._finished:
            return
        self._finished = True
        self.bus.now = T1 - 1
        self.att.tick(T1 + 10)
        self.att.finish(T1 - 1)

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
            "manual_switch_ons": m["manual_on"],
            "manual_ac_ons": m["manual_ac"],
            "people_on_site": len(truly_in),
            "register_count": len(register),
            "missing_from_register": sorted(truly_in - register),
            "tailgates_true": len(tg_true),
            "tailgates_caught": caught,
            "tailgate_false_alarms": false_alarms,
            "door_count_alerts": len(self.att.double_counts),
            **self._rollcall_errors(),
            "beam_misses": self.truth.beam_misses,
            "staff": len(staff),
            "alerts": alerts,
        }

    def _rollcall_errors(self) -> dict:
        """How far each roll-call view is from the truth, 08:30-18:30, in people."""
        s = self.series
        idx = [i for i, t in enumerate(s["t"]) if hm("08:30") <= t < hm("18:30")]
        def err(key):
            d = [abs(s[key][i] - s["roll_truth"][i]) for i in idx]
            return round(sum(d) / max(len(d), 1), 2), max(d, default=0)
        (cm, cx), (rm, rx), (em, ex) = err("roll_counter"), err("roll_register"), err("roll_estimate")
        return {"rollcall_counter_mean_err": cm, "rollcall_counter_max_err": cx,
                "rollcall_register_mean_err": rm, "rollcall_register_max_err": rx,
                "rollcall_estimate_mean_err": em, "rollcall_estimate_max_err": ex}

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
