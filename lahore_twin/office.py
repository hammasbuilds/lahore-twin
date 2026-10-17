"""The office scenario: who works here, what they do all day, and the calendar.

Everything here is generated from one seed, before the simulation starts, and
never looks at a device. That is what makes the rule-set comparison fair: the
same people live the same day under every rule set.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .people import Person, Stay
from .plan import Plan

# A world mix of names. Never one regional pool (see worldwide-names).
FIRST = {
    "f": ["Amara", "Sofia", "Mei", "Ayesha", "Priya", "Elena", "Fatima", "Yuki", "Chloe",
          "Zainab", "Ingrid", "Lucia", "Nadia", "Hana", "Isabel", "Amina", "Leila", "Freya",
          "Sana", "Olga", "Mariam", "Ana", "Keiko", "Noor"],
    "m": ["Omar", "Kenji", "Mateo", "Arjun", "Lars", "Kwame", "Hassan", "Diego", "Liam",
          "Bilal", "Tomasz", "Ravi", "Emeka", "Jun", "Pierre", "Ali", "Samuel", "Andrei",
          "Yusuf", "Tariq", "Felipe", "Hamza", "Ivan", "Daniel"],
}
LAST = ["Okafor", "Tanaka", "Silva", "Khan", "Novak", "Haddad", "Kowalski", "Mensah",
        "Fernandez", "Ahmed", "Larsen", "Ivanova", "Nguyen", "Rossi", "Qureshi", "Mbeki",
        "Sato", "Costa", "Malik", "Andersson", "Petrov", "Chaudhry", "Moreau", "Osei",
        "Iqbal", "Kim", "Dubois", "Raza", "Lopez", "Begum"]


def hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 3600 + int(m) * 60


def clock(t: float) -> str:
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}"


@dataclass
class Booking:
    id: str
    room: str
    title: str
    start: int
    end: int
    attendees: list[str] = field(default_factory=list)
    no_show: bool = False


@dataclass
class Scenario:
    plan: Plan
    people: list[Person]
    bookings: list[Booking]
    seed: int
    prayer_times: dict[str, int]
    truth: dict = field(default_factory=dict)


ZUHR, ASR = hm("13:30"), hm("16:30")   # office congregation times, a configurable assumption


class _Busy:
    """Per-person busy intervals so nobody is booked into two places."""

    def __init__(self):
        self.iv: dict[str, list[tuple[int, int]]] = {}

    def free(self, pid: str, a: int, b: int, pad: int = 300) -> bool:
        return all(b + pad <= s or a >= e + pad for s, e in self.iv.get(pid, []))

    def add(self, pid: str, a: int, b: int) -> None:
        self.iv.setdefault(pid, []).append((a, b))


def build(plan: Plan, seed: int = 7, n_staff: int = 24, n_visitors: int = 4) -> Scenario:
    rng = random.Random(seed)
    used_names: set[str] = set()

    def name(g: str) -> str:
        while True:
            n = f"{rng.choice(FIRST[g])} {rng.choice(LAST)}"
            if n not in used_names:
                used_names.add(n)
                return n

    gate = plan.spots["gate"][0]
    people: list[Person] = []

    def person(pid, role, arrive, leave, desk=None, drives=False, g=None):
        g = g or rng.choice("fm")
        p = Person(
            id=pid, name=name(g), role=role, gender=g, speed=rng.uniform(1.1, 1.5),
            arrive=arrive, leave=leave, entry=gate, car_bay=-1 if drives else None, desk=desk,
            badge_out_habit=rng.choice([0.97, 0.95, 0.9, 0.8]),
            still_bias=rng.choice([0.6, 1.0, 1.0, 1.5, 2.5]),
        )
        people.append(p)
        return p

    def staff_times():
        if rng.random() < 0.12:                       # the late tail
            a = rng.gauss(hm("09:35"), 600)
        else:
            a = rng.gauss(hm("09:00"), 720)
        a = int(min(max(a, hm("08:15")), hm("10:30")))
        if rng.random() < 0.12:                       # overtime
            lv = rng.gauss(hm("19:10"), 1200)
        else:
            lv = rng.gauss(hm("17:45"), 1500)
        lv = int(min(max(lv, hm("16:30")), hm("20:15")))
        return a, lv

    desks = plan.spots["desk"]
    staff_list = []
    for i in range(n_staff):
        a, lv = staff_times()
        p = person(f"s{i + 1:02d}", "staff", a, lv, desk=desks[i % len(desks)], drives=rng.random() < 0.6)
        p.has_badge = rng.random() > 0.05
        staff_list.append(p)
    # about a quarter of staff arrive with a colleague (carpool, same bus, met at the gate):
    # the follower is a few seconds behind, which is where real tailgating comes from
    pairs = []
    pool = staff_list[:]
    rng.shuffle(pool)
    while len(pool) >= 2 and len(pairs) < n_staff // 8:
        lead, follow = pool.pop(), pool.pop()
        follow.arrive = lead.arrive + rng.randint(2, 6)
        follow.car_bay = None
        pairs.append((lead, follow))
    for i, key in enumerate(("mgr1_desk", "mgr2_desk")):
        a = int(rng.gauss(hm("08:50"), 480))
        lv = int(rng.gauss(hm("18:30"), 1200))
        person(f"m{i + 1}", "manager", a, lv, desk=plan.spots[key][0], drives=True)
    person("r1", "receptionist", hm("08:25"), hm("17:35"), desk=plan.spots["reception_desk"][0], g="f")
    person("b1", "office_boy", hm("07:55"), hm("18:10"), desk=plan.spots["pantry"][0], g="m")
    person("g1", "guard", hm("07:00"), hm("19:45"), desk=plan.spots["guard_post"][0], g="m")
    person("c1", "cleaner", hm("07:05"), hm("17:00"), desk=plan.spots["store_spot"][0])

    # parking: first come, first served; the rest park on the street and walk in
    drivers = sorted((p for p in people if p.car_bay == -1), key=lambda p: p.arrive)
    for i, p in enumerate(drivers):
        if i < len(plan.parking_spots):
            p.car_bay = i
            p.entry = plan.parking_spots[i]
        else:
            p.car_bay = None
    for lead, follow in pairs:
        follow.entry = lead.entry          # they walk in together from the leader's car or the gate

    busy = _Busy()
    bookings = _calendar(plan, rng, people, busy, n_visitors, person)
    prayer = {"Zuhr": ZUHR, "Asr": ASR}
    for p in people:
        p.day = _day_for(plan, rng, p, bookings, busy)
    # congregational prayers are fixed in time, so the building can treat them as bookings
    for name, t in prayer.items():
        who = [p.id for p in people if any(s.label == f"{name} prayer" for s in p.day)]
        bookings.append(Booking(f"pr-{name.lower()}", "prayer", f"{name} congregation", t - 240, t + 660, who))
    bookings.sort(key=lambda b: b.start)
    return Scenario(plan, people, bookings, seed, prayer)


def _calendar(plan, rng, people, busy, n_visitors, person_factory):
    staff = [p for p in people if p.role in ("staff", "manager")]
    bookings: list[Booking] = []
    titles = ["Sprint planning", "Client review", "Design crit", "1:1", "Budget sync",
              "Hiring panel", "Standup", "Vendor demo", "Retrospective", "Roadmap"]

    def book(room, start, dur, size, title, visitors=0):
        end = start + dur
        cand = [p for p in staff if p.arrive < start - 600 and p.leave > end + 300
                and busy.free(p.id, start, end)]
        if len(cand) < max(1, size - visitors):
            return None
        chosen = rng.sample(cand, max(1, size - visitors))
        b = Booking(f"bk{len(bookings) + 1}", room, title, start, end)
        b.no_show = rng.random() < 0.12
        for p in chosen:
            if not b.no_show:
                busy.add(p.id, start, end)
                b.attendees.append(p.id)
        for _ in range(visitors if not b.no_show else 0):
            g = rng.choice("fm")
            vid = f"v{sum(1 for x in people if x.role == 'visitor') + 1}"
            v = person_factory(vid, "visitor", start - rng.randint(900, 1500), end + 120, g=g)
            v.speed = rng.uniform(0.9, 1.2)
            v.badge_out_habit = 1.0     # visitor cards are collected at the gate
            busy.add(vid, start, end)
            b.attendees.append(vid)
        bookings.append(b)
        return b

    slots_l = [hm("10:00"), hm("11:30"), hm("14:30"), hm("16:00")]
    visitors_left = n_visitors
    for s in slots_l:
        v = 2 if visitors_left >= 2 and rng.random() < 0.6 else 0
        if book("meet_l", s + rng.choice([0, 900]), rng.choice([2700, 3600]), rng.randint(6, 10),
                rng.choice(titles), visitors=v):
            visitors_left -= v
    for s in [hm("09:30"), hm("10:45"), hm("12:00"), hm("14:00"), hm("15:15"), hm("16:45")]:
        v = 1 if visitors_left >= 1 and rng.random() < 0.35 else 0
        if book("meet_s", s + rng.choice([0, 600]), rng.choice([1800, 2700]), rng.randint(2, 4),
                rng.choice(titles), visitors=v):
            visitors_left -= v
    for booth in ("booth1", "booth2", "booth3"):
        t = hm("09:45") + rng.randint(0, 1800)
        while t < hm("17:00"):
            dur = rng.choice([900, 1200, 1800, 2400])
            book(booth, t, dur, 1, "Call")
            t += dur + rng.randint(1800, 5400)
    return sorted(bookings, key=lambda b: b.start)


def _seat(plan, booking: Booking, i: int):
    key = {"meet_l": "meet_l_seat", "meet_s": "meet_s_seat"}.get(booking.room, f"{booking.room}_seat")
    seats = plan.spots[key]
    return seats[i % len(seats)]


def _day_for(plan, rng, p: Person, bookings, busy) -> list[Stay]:
    """A person's day as a time-ordered list of stays, conflicts resolved by priority."""
    home = p.desk
    events: list[tuple[int, int, Stay]] = []   # (start, end, stay)

    def add(a, b, stay, force=False):
        if not force and any(not (b <= s or a >= e) for s, e, _ in events):
            return False
        events.append((a, b, stay))
        return True

    # meetings (highest priority)
    for b in bookings:
        if p.id in b.attendees:
            i = b.attendees.index(p.id)
            lead = rng.randint(-60, 240) if p.role != "visitor" else 180
            add(b.start - lead, b.end, Stay(b.start - lead, _seat(plan, b, i), f"{b.title} ({plan.rooms[b.room].name})"),
                force=True)

    if p.role == "visitor":
        start = p.arrive
        mtg = min(events, key=lambda e: e[0]) if events else None
        out = [Stay(start, plan.spots["kiosk"][0], "Visitor check-in", on_arrive="kiosk_checkin")]
        out.append(Stay(start + 90, rng.choice(plan.spots["lobby_seat"]), "Waiting in lobby"))
        if mtg:
            out.append(mtg[2])
        out.append(Stay(p.leave, p.entry, "Leaving", kind="leave"))
        return out

    if p.role == "guard":
        for t in ("10:00", "12:30", "15:00", "18:00"):
            stops = [(plan.spots["lobby_seat"][0], 20), ((16, 19), 10), ((11, 25), 20), ((23, 25), 10),
                     ((16, 31), 10), ((4, 35), 20), ((25, 31), 10), ((12.5, 15), 10)]
            add(hm(t), hm(t) + 420, Stay(hm(t), home, "Patrol", kind="round", stops=stops))

    if p.role == "office_boy":
        for t in ("10:30", "15:30"):
            stops = [(d, 15) for d in plan.spots["desk"]] + [(plan.spots["mgr1_desk"][0], 25),
                                                            (plan.spots["mgr2_desk"][0], 25)]
            add(hm(t), hm(t) + 1500, Stay(hm(t), home, "Tea round", kind="round", stops=stops))
        add(hm("12:50"), hm("14:05"), Stay(hm("12:50"), plan.spots["pantry"][0], "Serving lunch"))

    if p.role == "cleaner":
        order = ["lobby", "reception", "meet_l", "meet_s", "work", "mgr1", "mgr2", "booth1", "booth2",
                 "booth3", "cafe", "wc_m", "wc_f", "wc_a", "prayer", "corr1", "corr2"]
        stops = []
        for rid in order:
            r = plan.rooms[rid]
            stops.append((((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2), 150 if r.kind != "corridor" else 40))
        add(hm("07:10"), hm("08:45"), Stay(hm("07:10"), home, "Morning clean", kind="round", stops=stops))
        for t in ("11:00", "14:30", "16:15"):
            ws = [(((plan.rooms[w].x0 + plan.rooms[w].x1) / 2, 35), 180) for w in ("wc_m", "wc_f", "wc_a")]
            add(hm(t), hm(t) + 900, Stay(hm(t), home, "Washroom check", kind="round", stops=ws))

    # prayer: a share of people join each congregation
    for name, t in (("Zuhr", ZUHR), ("Asr", ASR)):
        if p.arrive < t - 300 and p.leave > t + 900 and rng.random() < 0.45:
            add(t - 240, t + 660, Stay(t - 240, rng.choice(plan.spots["prayer_spot"]), f"{name} prayer"))

    # lunch: try a preferred time, slide forward until it fits
    if p.role not in ("visitor",) and p.arrive < hm("12:30") and p.leave > hm("14:30"):
        want = rng.randint(hm("12:55"), hm("13:40"))
        if p.role == "office_boy":
            want = hm("14:10")
        for shift in range(0, 5400, 300):
            a = want + shift
            if add(a, a + 2700, Stay(a, plan.spots["queue"][-1], "Lunch", kind="lunch", until=a + 2700)):
                break

    # washroom and coffee, at random gaps
    t = p.arrive + rng.randint(1800, 5400)
    while t < p.leave - 1200:
        if rng.random() < 0.7:
            wc = {"m": "wc_m_spot", "f": "wc_f_spot"}[p.gender] if rng.random() > 0.08 else "wc_a_spot"
            add(t, t + rng.randint(180, 360), Stay(t, rng.choice(plan.spots[wc]), "Washroom"))
        else:
            add(t, t + rng.randint(180, 300), Stay(t, plan.spots["pantry"][0], "Coffee"))
        t += rng.randint(5400, 10800)

    events.sort(key=lambda e: e[0])
    day: list[Stay] = []
    if not p.has_badge:
        day.append(Stay(p.arrive, plan.spots["reception_counter"][0], "Forgot badge — manual check-in",
                        on_arrive="manual_checkin"))
        day.append(Stay(p.arrive + 75, home, "At desk"))
    else:
        # the guard works outside the badge line, so clocks in at the guard-post terminal
        day.append(Stay(p.arrive, home, _home_label(p), on_arrive="clock_in" if p.role == "guard" else ""))
    for a, b, stay in events:
        if a < p.arrive or b > p.leave:
            continue
        day.append(stay)
        day.append(Stay(b, home, _home_label(p)))
    day.append(Stay(p.leave, p.entry, "Leaving", kind="leave"))
    day.sort(key=lambda s: s.t)
    return day


def _home_label(p: Person) -> str:
    return {"staff": "At desk", "manager": "In cabin", "receptionist": "At reception",
            "office_boy": "In pantry", "guard": "At guard post", "cleaner": "In store room"}.get(p.role, "Here")
