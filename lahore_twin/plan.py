"""Floor plans: rooms, doors, named spots, and walking routes between them.

Rooms are axis-aligned rectangles. A wall separates every pair of rooms except
where a door spans their shared edge. Routing runs A* on a 0.5 m grid whose
moves may only cross a room boundary inside a door, then collapses each run of
cells in one room to its endpoints. Rooms are convex, so a straight line between
two points of the same room never leaves it, and the collapsed route is exact.
"""

from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

CELL = 0.5
PLANS = Path(__file__).resolve().parent.parent / "plans"


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    kind: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def contains(self, x: float, y: float) -> bool:
        return self.x0 < x < self.x1 and self.y0 < y < self.y1


@dataclass(frozen=True)
class Door:
    a: str
    b: str
    axis: str  # "x" if the shared edge is horizontal (door spans x), else "y"
    at: float  # coordinate of the shared edge on the other axis
    lo: float
    hi: float
    gate: str | None = None
    name: str = ""

    @property
    def mid(self) -> tuple[float, float]:
        m = (self.lo + self.hi) / 2
        return (m, self.at) if self.axis == "x" else (self.at, m)


def _shared_edge(r1: Room, r2: Room) -> tuple[str, float, float, float] | None:
    """The edge two rooms share, as (axis, at, lo, hi), or None."""
    for top, bottom in ((r1, r2), (r2, r1)):
        if math.isclose(top.y1, bottom.y0):
            lo, hi = max(top.x0, bottom.x0), min(top.x1, bottom.x1)
            if hi > lo:
                return ("x", top.y1, lo, hi)
    for left, right in ((r1, r2), (r2, r1)):
        if math.isclose(left.x1, right.x0):
            lo, hi = max(left.y0, right.y0), min(left.y1, right.y1)
            if hi > lo:
                return ("y", left.x1, lo, hi)
    return None


@dataclass
class Plan:
    name: str
    width: float
    height: float
    rooms: dict[str, Room]
    doors: list[Door]
    spots: dict[str, list[tuple[float, float]]]
    parking_spots: list[tuple[float, float]]
    lane_y: float
    ac_rooms: list[str]
    operations: dict = field(default_factory=dict)
    raw: dict = field(repr=False, default_factory=dict)

    # grid state, built lazily
    _cols: int = 0
    _rows: int = 0
    _cell_room: list = field(default_factory=list, repr=False)
    _door_cells: set = field(default_factory=set, repr=False)
    _cache: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: str | Path) -> "Plan":
        path = Path(path)
        if not path.is_absolute() and not path.exists():
            path = PLANS / path
        raw = json.loads(path.read_text(encoding="utf-8"))
        rooms = {
            r["id"]: Room(r["id"], r["name"], r["kind"], *map(float, r["rect"]))
            for r in raw["rooms"]
        }
        doors = []
        for d in raw["doors"]:
            ra, rb = rooms[d["a"]], rooms[d["b"]]
            edge = _shared_edge(ra, rb)
            if edge is None:
                raise ValueError(f"door {d['a']}-{d['b']}: rooms share no edge")
            axis, at, lo, hi = edge
            dlo, dhi = map(float, d["span"])
            if dlo < lo - 1e-9 or dhi > hi + 1e-9:
                raise ValueError(f"door {d['a']}-{d['b']} span {d['span']} outside edge {lo}-{hi}")
            doors.append(Door(d["a"], d["b"], axis, at, dlo, dhi, d.get("gate"),
                              d.get("name") or f"{ra.name} / {rb.name} door"))
        spots = {k: [tuple(map(float, p)) for p in v] for k, v in raw["spots"].items()}
        plan = cls(
            name=raw["name"],
            width=float(raw["size"][0]),
            height=float(raw["size"][1]),
            rooms=rooms,
            doors=doors,
            spots=spots,
            parking_spots=[tuple(map(float, p)) for p in raw["parking"]["spots"]],
            lane_y=float(raw["parking"]["lane_y"]),
            ac_rooms=list(raw.get("ac_rooms", [])),
            operations=raw.get("operations", {}),
            raw=raw,
        )
        plan._build_grid()
        for kind, pts in spots.items():
            for p in pts:
                if plan.room_at(*p) is None:
                    raise ValueError(f"spot {kind} {p} is not inside any room")
        ops = plan.operations
        for rid in list(ops.get("optimum_start", {})) + list(ops.get("cleaning_order", [])) + plan.ac_rooms:
            if rid not in rooms:
                raise ValueError(f"operations name room {rid!r}, which the plan does not have")
        for x, y, _ in ops.get("patrol", []):
            if plan.room_at(x, y) is None:
                raise ValueError(f"patrol stop {(x, y)} is not inside any room")
        gate = ops.get("manual_checkin_gate")
        if gate is not None and not any(d.gate == "badge" and d.b == gate for d in doors):
            raise ValueError(f"manual_checkin_gate {gate!r} is not the secure side of a badge door")
        return plan

    # ---- geometry -------------------------------------------------------

    def room_at(self, x: float, y: float) -> str | None:
        for r in self.rooms.values():
            if r.contains(x, y):
                return r.id
        return None

    def gate_door(self, gate: str) -> Door:
        for d in self.doors:
            if d.gate == gate:
                return d
        raise KeyError(gate)

    # ---- grid -----------------------------------------------------------

    def _build_grid(self) -> None:
        self._cols = int(round(self.width / CELL))
        self._rows = int(round(self.height / CELL))
        self._cell_room = [
            [self.room_at((c + 0.5) * CELL, (r + 0.5) * CELL) for c in range(self._cols)]
            for r in range(self._rows)
        ]

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return (min(self._cols - 1, max(0, int(x / CELL))), min(self._rows - 1, max(0, int(y / CELL))))

    def _centre(self, c: int, r: int) -> tuple[float, float]:
        return ((c + 0.5) * CELL, (r + 0.5) * CELL)

    def _can_cross(self, c: int, r: int, nc: int, nr: int) -> bool:
        """May a walker step from cell (c, r) to the 4-neighbour (nc, nr)?"""
        a, b = self._cell_room[r][c], self._cell_room[nr][nc]
        if a is None or b is None:
            return False
        if a == b:
            return True
        x0, y0 = self._centre(c, r)
        x1, y1 = self._centre(nc, nr)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        for d in self.doors:
            if {d.a, d.b} != {a, b}:
                continue
            along = mx if d.axis == "x" else my
            if d.lo <= along <= d.hi:
                return True
        return False

    def _neighbours(self, c: int, r: int):
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nc, nr = c + dc, r + dr
            if 0 <= nc < self._cols and 0 <= nr < self._rows and self._can_cross(c, r, nc, nr):
                yield nc, nr, 1.0
        here = self._cell_room[r][c]
        for dc, dr in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            nc, nr = c + dc, r + dr
            if not (0 <= nc < self._cols and 0 <= nr < self._rows):
                continue
            # diagonals only inside one room, so they never clip a wall corner
            if (self._cell_room[nr][nc] == here and self._cell_room[r][nc] == here
                    and self._cell_room[nr][c] == here):
                yield nc, nr, math.sqrt(2)

    def route(self, start: tuple[float, float], goal: tuple[float, float]) -> list[tuple[float, float]]:
        """Walking polyline from start to goal, through doors only."""
        s, g = self._cell(*start), self._cell(*goal)
        key = (s, g)
        if key not in self._cache:
            self._cache[key] = self._collapse(self._astar(s, g))
        cells = self._cache[key]
        pts = [start] + cells[1:-1] + [goal] if len(cells) > 2 else [start, goal]
        return _dedupe(pts)

    def _astar(self, s, g):
        def h(c):
            dx, dy = abs(c[0] - g[0]), abs(c[1] - g[1])
            return max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)

        openq = [(h(s), 0.0, s)]
        came = {s: None}
        cost = {s: 0.0}
        while openq:
            _, gc, cur = heapq.heappop(openq)
            if cur == g:
                break
            if gc > cost[cur]:
                continue
            for nc, nr, w in self._neighbours(*cur):
                n = (nc, nr)
                ng = gc + w
                if ng < cost.get(n, math.inf):
                    cost[n] = ng
                    came[n] = cur
                    heapq.heappush(openq, (ng + h(n), ng, n))
        if g not in came:
            raise ValueError(f"no route from cell {s} to {g}")
        path, cur = [], g
        while cur is not None:
            path.append(cur)
            cur = came[cur]
        return path[::-1]

    def _collapse(self, cells) -> list[tuple[float, float]]:
        """Keep only the first and last cell of each same-room run."""
        out = []
        for i, (c, r) in enumerate(cells):
            room = self._cell_room[r][c]
            prev = self._cell_room[cells[i - 1][1]][cells[i - 1][0]] if i else None
            nxt = self._cell_room[cells[i + 1][1]][cells[i + 1][0]] if i + 1 < len(cells) else None
            if i == 0 or i == len(cells) - 1 or room != prev or room != nxt:
                out.append(self._centre(c, r))
        return out

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "size": [self.width, self.height],
            "rooms": [
                {"id": r.id, "name": r.name, "kind": r.kind, "rect": [r.x0, r.y0, r.x1, r.y1]}
                for r in self.rooms.values()
            ],
            "doors": [
                {"a": d.a, "b": d.b, "axis": d.axis, "at": d.at, "lo": d.lo, "hi": d.hi, "gate": d.gate,
                 "name": d.name}
                for d in self.doors
            ],
            "spots": self.spots,
            "parking": {"lane_y": self.lane_y, "spots": self.parking_spots},
            "furniture": self.raw.get("furniture", []),
            "big_desks": self.raw.get("big_desks", []),
            "short_names": self.raw.get("short_names", {}),
            "labels": self.raw.get("labels", []),
        }


def _dedupe(pts):
    out = [pts[0]]
    for p in pts[1:]:
        if math.dist(p, out[-1]) > 1e-6:
            out.append(p)
    return out


def path_length(pts) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
