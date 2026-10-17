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
PRECOOL = 900
NO_SHOW_GRACE = 600
CO2_HIGH, CO2_OK = 1000, 800


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

    def _occupancy_tick(self, t: int) -> None:
        for rid, st in self.rooms.items():
            kind = self.plan.rooms[rid].kind
            hold = HOLD.get(kind, HOLD_DEFAULT)
            if st.occupied and t - st.last_motion >= hold:
                if self.mode == "pir+co2" and self._co2_says_occupied(st):
                    if t - st.kept_note >= 1800:
                        st.kept_note = t
                        self.bus.publish(f"office/{rid}/kept", None, st.motion_msg,
                                         f"No motion in {self._name(rid)} for {hold // 60} min, "
                                         f"but CO₂ is steady at {st.co2[-1][1]:.0f} ppm — keeping it on")
                    continue
                st.occupied = False
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
            if (self.mode != "schedule" and "precool" not in fired and t >= b.start - PRECOOL
                    and t < b.end and b.room in self.plan.ac_rooms and b.id not in self.released):
                fired.add("precool")
                m = self.bus.publish(f"office/{b.room}/booking", b.id, None,
                                     f"{b.title} booked {clock(b.start)}–{clock(b.end)} — pre-cooling")
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
        bus.subscribe("office/gate/badge", self._on_badge)
        bus.subscribe("office/gate/beam", self._on_beam)
        bus.subscribe("office/reception/manual", self._on_manual)
        bus.subscribe("office/lobby/kiosk", self._on_kiosk)

    def _first_in(self, pid: str, t: int, how: str, cause: int) -> None:
        if pid in self.checkin:
            return
        self.checkin[pid] = t
        p = self.people[pid]
        if p.role in ("staff", "manager") and t > hm("09:15"):
            self.bus.publish("office/alert/late", pid, cause, f"{p.name} checked in late at {clock(t)} ({how})")

    def _on_badge(self, m: Message) -> None:
        pid, direction = m.payload["person"], m.payload["dir"]
        if direction == "in":
            self.creds.append([m.t, pid, False])
            self._first_in(pid, m.t, "badge", m.id)
        else:
            self.checkout[pid] = m.t

    def _on_manual(self, m: Message) -> None:
        pid = m.payload
        self.creds.append([m.t, pid, False, "manual"])
        self._first_in(pid, m.t, "manual at reception", m.id)

    def _on_kiosk(self, m: Message) -> None:
        pass     # visitor kiosk check-in; the gate tap still happens with a visitor card

    def _on_beam(self, m: Message) -> None:
        if m.payload == "in":
            self.beams.append([m.t, m.id, False])

    def tick(self, t: int) -> None:
        for beam in self.beams:
            bt, bid, resolved = beam
            if resolved or t < bt + self.WINDOW:
                continue
            beam[2] = True
            # nearest credential wins, exact badge reads before manual check-ins,
            # so an old manual check-in never claims someone else's badge pass
            cands = []
            for c in self.creds:
                if c[2]:
                    continue
                manual = len(c) > 3
                window = self.MANUAL_VALID if manual else self.WINDOW
                if bt - window <= c[0] <= bt + self.WINDOW:
                    cands.append((manual, abs(c[0] - bt), c))
            match = min(cands, key=lambda x: (x[0], x[1]))[2] if cands else None
            if match:
                match[2] = True
            else:
                self.tailgate_alerts.append(bt)
                self.bus.publish("office/alert/tailgate", bt, bid,
                                 f"Someone entered at {clock(bt)} without a badge read — possible tailgating")

    def finish(self, t: int) -> None:
        for pid, tin in self.checkin.items():
            if pid not in self.checkout:
                p = self.people[pid]
                self.bus.publish("office/alert/no_badge_out", pid, None,
                                 f"{p.name} checked in at {clock(tin)} but never badged out")
