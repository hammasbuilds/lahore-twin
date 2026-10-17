"""Automation rules and the attendance reconciler.

Rules only see what a real building management system would see: messages on
the bus. They never read a person's true position. Every command they publish
names the message that caused it.

Three rule sets run on the same day:

* ``schedule`` — lights and AC on 08:30-18:30 everywhere (what most offices do)
* ``pir``      — rooms follow motion; empty after a hold time with no motion
* ``pir+co2``  — as ``pir``, but a room is only declared empty once its CO2
                 is falling or back near outdoor level
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .bus import Bus, Message
from .devices import C_OUT
from .office import Booking, clock, hm

MODES = ("schedule", "pir", "pir+co2")
HOLD = {"corridor": 120, "washroom": 300, "outdoor": 0}
HOLD_DEFAULT = 600
SCHEDULE_ON, SCHEDULE_OFF = hm("08:30"), hm("18:30")
AC_WINDOW = (hm("07:30"), hm("20:00"))
PRECOOL = 600               # minimum pre-cool lead; hotter rooms get longer (see _booking_tick)
NO_SHOW_GRACE = 600
CO2_HIGH, CO2_OK = 800, 650      # demand-controlled ventilation: boost before 1000 ppm, not at it
LATE_FROM = hm("09:16")
RETRIGGER = 60              # motion this soon after switching off means the room was not empty
CO2_EXTEND = 300            # a CO2 "still occupied" verdict holds for this long
ROLLCALL_GAP, ROLLCALL_FOR = 2, 900
HOLD_MULT_MAX = 4
# optimum start: rooms used every day, and when their first occupant usually walks in
# (in a real building this comes from weeks of badge history)
OPTIMUM_START = {"work": hm("08:30"), "reception": hm("08:25"), "mgr1": hm("08:45"), "mgr2": hm("08:45")}
PULLDOWN_S_PER_C = 330      # measured from the room model: seconds of full cooling per degree


@dataclass
class RoomState:
    occupied: bool = False
    last_motion: int = -10**9
    motion_msg: int | None = None
    light: bool = False
    ac: bool = False
    precool: int | None = None        # booking msg id holding the AC on
    vent: bool = False
    co2: deque = field(default_factory=lambda: deque(maxlen=12))   # (t, ppm) at 60 s
    kept_note: int = -10**9
    vacated_at: int = -10**9          # when the rules last declared the room empty
    hold_mult: int = 1                # adaptive hold: doubles each time someone was switched off
    relaxed: bool = True              # has the last switch-off been judged correct yet
    co2_hold_until: int = -10**9      # CO2 said "still occupied": no switch-off before this


class Automation:
    def __init__(self, bus: Bus, plan, mode: str, bookings: list[Booking]):
        assert mode in MODES, mode
        self.bus, self.plan, self.mode = bus, plan, mode
        self.bookings = bookings
        self.rooms = {rid: RoomState() for rid, r in plan.rooms.items() if r.kind != "outdoor"}
        self.released: set[str] = set()
        self.booking_seen: dict[str, bool] = {b.id: False for b in bookings}
        self.fired: dict[str, set] = {}
        self.cafe_busy = False
        bus.subscribe("office/+/motion", self._on_motion)
        bus.subscribe("office/+/co2", self._on_co2)
        bus.subscribe("office/cafe/queue", self._on_queue)
        bus.subscribe("office/+/temp", self._on_temp)
        bus.subscribe("office/+/switch", self._on_switch)
        self.temps: dict[str, float] = {}
        self.temp_msg: dict[str, int] = {}
        self.started: set[str] = set()

    def _on_switch(self, m: Message) -> None:
        """A wall switch always works, whatever the rule set."""
        rid = m.topic.split("/")[1]
        st = self.rooms.get(rid)
        if st is None:
            return
        if self.mode != "schedule":
            st.occupied = True
            st.last_motion, st.motion_msg = m.t, m.id
            if m.t - st.vacated_at <= 120 and st.hold_mult < HOLD_MULT_MAX:
                st.hold_mult *= 2
        self._set(rid, "light", True, m.id, "wall switch")

    def _on_temp(self, m: Message) -> None:
        rid = m.topic.split("/")[1]
        self.temps[rid] = m.payload
        self.temp_msg[rid] = m.id

    # ---- inputs ---------------------------------------------------------

    def _on_motion(self, m: Message) -> None:
        rid = m.topic.split("/")[1]
        st = self.rooms.get(rid)
        if st is None:
            return
        st.last_motion, st.motion_msg = m.t, m.id
        for b in self.bookings:
            if b.room == rid and b.start - 300 <= m.t <= b.end:
                self.booking_seen[b.id] = True
        if self.mode == "schedule":
            return
        if not st.occupied and m.t - st.vacated_at <= RETRIGGER and st.hold_mult < HOLD_MULT_MAX:
            # motion right after switching off: someone was there all along. Learn from it.
            st.hold_mult *= 2
            self.bus.publish(f"office/{rid}/hold", st.hold_mult, m.id,
                             f"Motion {m.t - st.vacated_at} s after switching {self._name(rid)} off — "
                             f"someone was still there; hold time now "
                             f"{HOLD.get(self.plan.rooms[rid].kind, HOLD_DEFAULT) * st.hold_mult // 60} min")
        if not st.occupied:
            st.occupied = True
            self._set(rid, "light", True, m.id, f"motion in {self._name(rid)}")
            if self._ac_allowed(rid, m.t):
                self._set(rid, "ac", True, m.id, f"motion in {self._name(rid)}")

    def _on_co2(self, m: Message) -> None:
        rid = m.topic.split("/")[1]
        st = self.rooms.get(rid)
        if st is None:
            return
        st.co2.append((m.t, m.payload))
        if m.payload > CO2_HIGH and not st.vent:
            st.vent = True
            self.bus.publish(f"office/{rid}/vent", True, m.id,
                             f"CO₂ {m.payload:.0f} ppm in {self._name(rid)} — ventilation boost")
        elif m.payload < CO2_OK and st.vent:
            st.vent = False
            self.bus.publish(f"office/{rid}/vent", False, m.id, f"CO₂ back to {m.payload:.0f} ppm")

    def _on_queue(self, m: Message) -> None:
        if m.payload >= 6 and not self.cafe_busy:
            self.cafe_busy = True
            self.bus.publish("office/alert/cafe_busy", m.payload, m.id,
                             f"Cafeteria queue is {m.payload} long — suggest coming back in 10 min")
        elif m.payload <= 2 and self.cafe_busy:
            self.cafe_busy = False
            self.bus.publish("office/alert/cafe_clear", m.payload, m.id, "Cafeteria queue cleared")

    # ---- timers ---------------------------------------------------------

    def tick(self, t: int) -> None:
        if self.mode == "schedule":
            self._schedule_tick(t)
        else:
            self._occupancy_tick(t)
        self._booking_tick(t)

    def _schedule_tick(self, t: int) -> None:
        if t > SCHEDULE_OFF and t % 3600 == 0:
            # after-hours sweep: lights switched on by hand go off on the hour
            lit = [rid for rid, st in self.rooms.items() if st.light]
            if lit:
                m = self.bus.publish("office/schedule/sweep", None, None, f"After-hours sweep at {clock(t)}")
                for rid in lit:
                    self._set(rid, "light", False, m.id, "after-hours sweep")
        if t == SCHEDULE_ON:
            m = self.bus.publish("office/schedule/on", None, None, "Building schedule: 08:30 start")
            for rid in self.rooms:
                self._set(rid, "light", True, m.id, "schedule 08:30–18:30")
                if self.plan.rooms[rid].id in self.plan.ac_rooms:
                    self._set(rid, "ac", True, m.id, "schedule 08:30–18:30")
        elif t == SCHEDULE_OFF:
            m = self.bus.publish("office/schedule/off", None, None, "Building schedule: 18:30 end")
            for rid in self.rooms:
                self._set(rid, "light", False, m.id, "schedule 08:30–18:30")
                self._set(rid, "ac", False, m.id, "schedule 08:30–18:30")

    def _optimum_start(self, t: int) -> None:
        """Start the AC early enough to reach the setpoint when people usually arrive."""
        for rid, due in OPTIMUM_START.items():
            if rid in self.started or t >= due or t < AC_WINDOW[0]:
                continue
            temp = self.temps.get(rid)
            if temp is None:
                continue
            lead = max(0.0, temp - 24.0) * PULLDOWN_S_PER_C
            if t >= due - lead:
                self.started.add(rid)
                m = self.bus.publish(f"office/{rid}/optimum_start", round(temp, 1), self.temp_msg.get(rid),
                                     f"Optimum start: {self._name(rid)} is {temp:.1f} °C, needs about "
                                     f"{lead / 60:.0f} min to reach 24 °C before {clock(due)}")
                self.rooms[rid].precool = m.id
                self._set(rid, "ac", True, m.id, f"optimum start for {clock(due)}")

    def _occupancy_tick(self, t: int) -> None:
        self._optimum_start(t)
        for rid, st in self.rooms.items():
            # a switch-off that nobody contradicted within a minute was right: relax the hold
            if (not st.occupied and st.hold_mult > 1 and st.vacated_at > 0
                    and t - st.vacated_at >= RETRIGGER and not st.relaxed):
                st.relaxed = True
                st.hold_mult //= 2
        for rid in list(self.started):
            st = self.rooms[rid]
            if st.precool is not None and t >= OPTIMUM_START[rid] + 1800:
                st.precool = None          # the start window is over; occupancy rules take it from here
        for rid, st in self.rooms.items():
            kind = self.plan.rooms[rid].kind
            hold = HOLD.get(kind, HOLD_DEFAULT) * st.hold_mult
            if st.occupied and t - st.last_motion >= hold:
                if t < st.co2_hold_until:
                    continue
                if self.mode == "pir+co2" and self._co2_says_occupied(st):
                    # one verdict buys a fixed extension, so sensor noise cannot flip
                    # the decision from one tick to the next
                    st.co2_hold_until = t + CO2_EXTEND
                    if st.kept_note < st.last_motion:
                        st.kept_note = t
                        self.bus.publish(f"office/{rid}/kept", None, st.motion_msg,
                                         f"No motion in {self._name(rid)} for {(t - st.last_motion) // 60} min, "
                                         f"but CO₂ is steady at {st.co2[-1][1]:.0f} ppm — keeping it on")
                    continue
                st.occupied = False
                st.vacated_at = t
                st.relaxed = False
                m = self.bus.publish(f"office/{rid}/vacant", None, st.motion_msg,
                                     f"No motion in {self._name(rid)} since {clock(st.last_motion)}")
                self._set(rid, "light", False, m.id, f"{self._name(rid)} empty")
                if st.precool is None:
                    self._set(rid, "ac", False, m.id, f"{self._name(rid)} empty")
            if st.occupied and not st.ac and self._ac_allowed(rid, t):
                self._set(rid, "ac", True, st.motion_msg, "room occupied, AC window open")
            if st.ac and not (AC_WINDOW[0] <= t < AC_WINDOW[1]) and st.precool is None:
                self._set(rid, "ac", False, None, "outside AC hours 07:30–20:00")

    def _co2_says_occupied(self, st: RoomState) -> bool:
        """Occupied evidence: CO2 well above outdoor and not decaying.

        An empty room's CO2 decays exponentially towards outdoor level; a room
        with someone sitting still holds steady or rises. Means of three
        readings, five minutes apart, keep sensor noise from deciding.
        """
        if len(st.co2) < 8:
            return False
        recent = sum(p for _, p in list(st.co2)[-3:]) / 3
        earlier = sum(p for _, p in list(st.co2)[-8:-5]) / 3
        return recent > C_OUT + 120 and recent - earlier > -12

    def _booking_tick(self, t: int) -> None:
        # rules run every few seconds, so timers fire on crossing a time, never on equality
        for b in self.bookings:
            st = self.rooms[b.room]
            fired = self.fired.setdefault(b.id, set())
            # pre-cool lead from the room's own temperature: a heat-soaked room needs longer
            temp = self.temps.get(b.room, 26.0)
            lead = max(PRECOOL, (temp - 24.0) * PULLDOWN_S_PER_C + 300)
            if (self.mode != "schedule" and "precool" not in fired and t >= b.start - lead
                    and t < b.end and b.room in self.plan.ac_rooms and b.id not in self.released):
                fired.add("precool")
                m = self.bus.publish(f"office/{b.room}/booking", b.id, self.temp_msg.get(b.room),
                                     f"{b.title} booked {clock(b.start)}–{clock(b.end)}; room is {temp:.1f} °C "
                                     f"— pre-cooling {lead / 60:.0f} min ahead")
                st.precool = m.id
                self._set(b.room, "ac", True, m.id, f"pre-cool for {b.title} at {clock(b.start)}")
            if "noshow" not in fired and t >= b.start + NO_SHOW_GRACE:
                fired.add("noshow")
                if not self.booking_seen[b.id]:
                    self.released.add(b.id)
                    m = self.bus.publish("office/alert/no_show", b.id, st.precool,
                                         f"{b.title} in {self._name(b.room)} ({clock(b.start)}): nobody came "
                                         f"in {NO_SHOW_GRACE // 60} min — booking released")
                    if self.mode != "schedule" and st.precool is not None:
                        st.precool = None
                        if not st.occupied:
                            self._set(b.room, "ac", False, m.id, "booking released, room empty")
            if "end" not in fired and t >= b.end:
                fired.add("end")
                if st.precool is not None:
                    st.precool = None
                    if not st.occupied and self.mode != "schedule":
                        self._set(b.room, "ac", False, None, f"{b.title} ended, room empty")

    # ---- outputs --------------------------------------------------------

    def _ac_allowed(self, rid: str, t: int) -> bool:
        return rid in self.plan.ac_rooms and AC_WINDOW[0] <= t < AC_WINDOW[1]

    def _set(self, rid: str, dev: str, on: bool, cause: int | None, why: str) -> None:
        st = self.rooms[rid]
        if dev == "ac" and rid not in self.plan.ac_rooms:
            return
        if getattr(st, dev) == on:
            return
        setattr(st, dev, on)
        label = {"light": "Lights", "ac": "AC"}[dev]
        self.bus.publish(f"office/{rid}/{dev}", on, cause,
                         f"{label} {'on' if on else 'off'} in {self._name(rid)} — {why}")

    def _name(self, rid: str) -> str:
        return self.plan.rooms[rid].name


class Attendance:
    """Builds the attendance register from gate messages alone, and audits it.

    A tailgate is a beam pass that no credential explains: no badge read and
    no manual reception check-in within a few seconds of it.
    """

    WINDOW = 4          # seconds either side of a beam pass
    MANUAL_VALID = 240  # a manual check-in authorises one pass for this long

    def __init__(self, bus: Bus, people_by_id: dict):
        self.bus = bus
        self.people = people_by_id
        self.checkin: dict[str, int] = {}
        self.checkout: dict[str, int] = {}
        self.creds: list[list] = []      # [t, person, used]
        self.beams: list[list] = []      # [t, msg_id, resolved]
        self.tailgate_alerts: list[int] = []
        self.double_counts: list[int] = []
        # roll-call: two independent views of how many people are behind the badge doors
        self.inside: dict[str, bool] = {}     # register: last badge direction per person
        self.counted_inside = 0               # door counters: ins minus outs
        self.mismatch_since: int | None = None
        self.unidentified = 0                 # tailgate entries whose person is not yet known
        self.unexplained_out = 0              # counted exits with no badge-out
        self.out_beams: list[list] = []
        self.out_creds: list[list] = []
        bus.subscribe("office/gate/badge", self._on_badge)
        bus.subscribe("office/gate/beam", self._on_beam)
        bus.subscribe("office/reception/manual", self._on_manual)
        bus.subscribe("office/guard_post/clock", self._on_clock)
        bus.subscribe("office/lobby/kiosk", self._on_kiosk)

    def _first_in(self, pid: str, t: int, how: str, cause: int) -> None:
        if pid in self.checkin:
            return
        self.checkin[pid] = t
        p = self.people[pid]
        # late = 09:16 or after, so the alert never shows a time that reads as on time
        if p.role in ("staff", "manager") and t >= LATE_FROM:
            self.bus.publish("office/alert/late", pid, cause,
                             f"{p.name} checked in late at {clock(t)} ({how}), "
                             f"{(t - hm('09:00')) // 60} min after 09:00")

    def _on_badge(self, m: Message) -> None:
        pid, direction, gate = m.payload["person"], m.payload["dir"], m.payload["gate"]
        if direction == "in":
            self.creds.append([m.t, pid, False, gate])
            if self.inside.get(pid):
                # tapping in while "inside": they left untapped earlier. Their exit may not be
                # reconciled yet (that waits a few seconds), so the count may dip below zero
                # here and is settled when it is.
                self.unexplained_out -= 1
            self.inside[pid] = True
            self._first_in(pid, m.t, "badge", m.id)
        else:
            self.out_creds.append([m.t, pid, False, gate])
            if not self.inside.get(pid) and self.unidentified > 0:
                self.unidentified -= 1        # tapping out while not "inside": the unbadged entry
            self.inside[pid] = False
            self.checkout[pid] = m.t

    def _on_clock(self, m: Message) -> None:
        pid = m.payload["person"]
        if m.payload["dir"] == "in":
            self._first_in(pid, m.t, "guard-post terminal", m.id)
        else:
            self.checkout[pid] = m.t

    def _on_manual(self, m: Message) -> None:
        pid = m.payload
        self.creds.append([m.t, pid, False, "manual"])     # manual: valid at the main gate
        self.inside[pid] = True
        self._first_in(pid, m.t, "manual at reception", m.id)

    def _on_kiosk(self, m: Message) -> None:
        pass     # visitor kiosk check-in; the gate tap still happens with a visitor card

    def _on_beam(self, m: Message) -> None:
        if m.payload["dir"] == "in":
            self.counted_inside += 1
            self.beams.append([m.t, m.id, False, m.payload["gate"]])
        else:
            self.counted_inside = max(0, self.counted_inside - 1)
            self.out_beams.append([m.t, m.id, False, m.payload["gate"]])

    def register_inside(self) -> int:
        return sum(self.inside.values())

    def estimate_inside(self) -> int:
        """Best evacuation count: the register, plus entries nobody badged for, minus
        exits nobody badged for (people who forget to tap out on the way home)."""
        return max(0, self.register_inside() + self.unidentified - self.unexplained_out)

    def rollcall_tick(self, t: int) -> None:
        """Door counters drift (every missed count accumulates), so when they have
        disagreed with the badge estimate by 2+ for 15 minutes they are re-zeroed."""
        est = self.estimate_inside()
        gap = self.counted_inside - est
        if abs(gap) >= ROLLCALL_GAP:
            if self.mismatch_since is None:
                self.mismatch_since = t
            if t - self.mismatch_since >= ROLLCALL_FOR:
                self.bus.publish("office/gate/rezero", est, None,
                                 f"Door counters drifted to {self.counted_inside} against a badge estimate of "
                                 f"{est} since {clock(self.mismatch_since)} — re-zeroed")
                self.counted_inside = est
                self.mismatch_since = None
        else:
            self.mismatch_since = None

    def _reconcile_exits(self, t: int) -> None:
        for beam in self.out_beams:
            if beam[2] or t < beam[0] + self.WINDOW:
                continue
            beam[2] = True
            cands = [c for c in self.out_creds if not c[2] and c[3] == beam[3] and abs(c[0] - beam[0]) <= self.WINDOW]
            if cands:
                min(cands, key=lambda c: abs(c[0] - beam[0]))[2] = True
            else:
                self.unexplained_out += 1

    def tick(self, t: int) -> None:
        self._reconcile_exits(t)
        for beam in self.beams:
            bt, bid, resolved, gate = beam
            if resolved or t < bt + self.WINDOW:
                continue
            beam[2] = True
            # nearest credential wins, exact badge reads before manual check-ins,
            # so an old manual check-in never claims someone else's badge pass
            cands = []
            for c in self.creds:
                if c[2]:
                    continue
                manual = c[3] == "manual"
                if not manual and c[3] != gate:
                    continue          # a badge read at another door explains nothing here
                if manual and gate != "corr1":
                    continue
                window = self.MANUAL_VALID if manual else self.WINDOW
                if bt - window <= c[0] <= bt + self.WINDOW:
                    cands.append((manual, abs(c[0] - bt), c))
            match = min(cands, key=lambda x: (x[0], x[1]))[2] if cands else None
            if match is None and any(b2[0] == bt and b2[1] != bid and b2[3] == gate for b2 in self.beams):
                # a second count in the very same second as an explained one: a person
                # lingering in the beam looks exactly like this, so it is not called a tailgate
                self.double_counts.append(bt)
                self.bus.publish("office/alert/door_count", bt, bid,
                                 f"Door counter counted 2 at {clock(bt)} for 1 badge — check the camera")
                continue
            if match:
                match[2] = True
            else:
                self.tailgate_alerts.append(bt)
                self.unidentified += 1
                self.bus.publish("office/alert/tailgate", bt, bid,
                                 f"Someone entered at {clock(bt)} without a badge read — possible tailgating")

    def finish(self, t: int) -> None:
        for pid, tin in self.checkin.items():
            if pid not in self.checkout:
                p = self.people[pid]
                self.bus.publish("office/alert/no_badge_out", pid, None,
                                 f"{p.name} checked in at {clock(tin)} but never badged out")
