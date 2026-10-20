"""People who walk the plan: a schedule of stays, turned into trips.

A person's day is a list of ``Stay`` items — be at this spot from this time,
doing this. The simulator walks them there along a routed polyline. A few
activities (the lunch queue, the office boy's tea round) are expanded while
the day runs, because where you stand in a queue depends on who came first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .plan import is_portal, seg_len

ROLE_COLOURS = {
    "staff": "#8b7cf6",
    "manager": "#e879f9",
    "receptionist": "#34d399",
    "office_boy": "#fbbf24",
    "courier": "#fb923c",
    "guard": "#60a5fa",
    "cleaner": "#2dd4bf",
    "visitor": "#f87171",
}


@dataclass
class Stay:
    t: int                 # seconds since midnight when the person should set off
    spot: tuple[float, float]
    label: str
    kind: str = "stay"     # stay | lunch | tea_round | leave
    stops: list = field(default_factory=list)   # tea_round: [(spot, dwell_s), ...]
    priority: int = 0
    on_arrive: str = ""    # manual_checkin | kiosk_checkin — an action fired on reaching the spot
    until: int = 0         # lunch: latest time to give up and go back
    pool: str = ""         # shared spots (prayer rows, stalls, seats): take a free one on arrival


@dataclass
class Person:
    id: str
    name: str
    role: str
    gender: str
    speed: float
    arrive: int
    leave: int
    entry: tuple[float, float]          # where they appear: their parking bay or the gate
    car_bay: int | None
    desk: tuple[float, float] | None
    has_badge: bool = True              # False = forgot it today, checks in at reception
    badge_out_habit: float = 0.9        # chance of tapping out on the way out
    still_bias: float = 1.0             # >1 = sits stiller than most (PIR misses them more)
    day: list[Stay] = field(default_factory=list)

    # runtime state
    on_site: bool = False
    gone: bool = False
    pos: tuple[float, float] = (0.0, 0.0)
    room: str | None = None
    path: list = field(default_factory=list)
    seg: int = 0
    seg_done: float = 0.0
    label: str = "away"
    idx: int = -1                       # index of the active Stay
    mode: str = "idle"                  # idle | walking | queue | eat | round
    hold_until: int = 0
    round_left: list = field(default_factory=list)

    @property
    def moving(self) -> bool:
        return self.mode == "walking" or bool(self.path)

    def set_path(self, pts) -> None:
        self.path = list(pts)
        self.seg = 0
        self.seg_done = 0.0

    def advance(self, dt: float) -> bool:
        """Walk along the current path. Returns True on the step the path ends."""
        if not self.path:
            return False
        budget = self.speed * dt
        while budget > 0 and self.seg < len(self.path) - 1:
            a, b = self.path[self.seg], self.path[self.seg + 1]
            length = seg_len(a, b)
            left = length - self.seg_done
            if budget < left:
                self.seg_done += budget
                if is_portal(a, b):
                    self.pos = a                 # on the stairs or in the lift: shown where they got on
                else:
                    f = self.seg_done / length
                    self.pos = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                return False
            budget -= left
            self.seg += 1
            self.seg_done = 0.0
            self.pos = b
        self.path = []
        return True
