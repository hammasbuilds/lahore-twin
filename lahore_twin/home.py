"""The home scenario: a Lahore family's day and the grid it lives on.

Everything here comes from one seed before the simulation starts, so every rule
set lives the identical day: the same people doing the same things, the same
published load-shedding, the same unannounced cuts, the same clouds and the same
voltage sags. Only the controller differs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .climate import Season, hm
from .office import FIRST, LAST, clock
from .people import Person, Stay
from .plan import Plan

DAY = 86400


@dataclass
class Outage:
    start: int
    end: int
    published: bool

    def covers(self, t: int) -> bool:
        return self.start <= t % DAY < self.end


@dataclass
class Request:
    """A deferrable job someone asks for: run `appliance` for `duration` by `deadline`."""
    id: str
    t: int
    appliance: str
    room: str
    duration: int
    deadline: int
    who: str
    label: str


@dataclass
class HomeScenario:
    plan: Plan
    season: Season
    seed: int
    category: str
    people: list[Person]
    outages: list[Outage]
    requests: list[Request]
    water: list[tuple[int, float, str]]          # (t, litres, why)
    meals: list[tuple[int, int]]                 # microwave use (t, seconds)
    cloud: list[tuple[int, int, float]]          # (start, end, factor) passing clouds
    day_factor: float                            # 1 clear, ~0.8 hazy, ~0.45 overcast
    forecast_factor: float                       # what a day-ahead forecast said
    sags: list[tuple[int, int, float]]           # (start, end, volts)

    def grid_up(self, t: int) -> bool:
        return not any(o.covers(t) for o in self.outages)

    def published(self) -> list[Outage]:
        return [o for o in self.outages if o.published]

    def cloud_factor(self, t: int) -> float:
        f = self.day_factor
        for a, b, k in self.cloud:
            if a <= t < b:
                f *= k
        return f

    def voltage(self, t: int) -> float:
        """Typical Lahore swing: ~228 V at night, sagging toward 200 V in the evening peak."""
        h = (t % DAY) / 3600
        v = 228.0
        if 18.5 <= h < 23.5:
            v = 205.0
        elif 11 <= h < 16:
            v = 218.0
        for a, b, volts in self.sags:
            if a <= t < b:
                v = min(v, volts)
        return v


# LESCO-style feeder categories: hours of scheduled load-shedding per day
CATEGORIES = {"I": 2, "III": 4, "IV": 5, "V": 6}


def _outages(rng: random.Random, category: str) -> list[Outage]:
    hours = CATEGORIES[category]
    # published blocks of 1 or 2 hours on the even-hour grid, one of them at night
    # (LESCO's plan "outlines heavier nocturnal outages")
    starts_night = [0, 2, 22]
    starts_day = [6, 8, 10, 12, 14, 16, 18, 20]
    blocks = []
    left = hours
    first = rng.choice(starts_night)
    d = min(2, left)
    blocks.append((first, d))
    left -= d
    pool = [s for s in starts_day]
    rng.shuffle(pool)
    while left > 0 and pool:
        s = pool.pop()
        if any(abs(s - b) < 3 for b, _ in blocks):
            continue
        d = min(left, rng.choice([1, 2]))
        blocks.append((s, d))
        left -= d
    out = [Outage(s * 3600, min(DAY, (s + d) * 3600), True) for s, d in sorted(blocks)]
    # unannounced cuts: about 1.2 a day, 20-90 minutes, never overlapping a published one
    n = 1 if rng.random() < 0.6 else 2
    for _ in range(n):
        for _attempt in range(20):
            a = rng.randint(hm("07:00"), hm("23:00"))
            b = a + rng.randint(20, 90) * 60
            if all(b + 1800 <= o.start or a >= o.end + 1800 for o in out):
                out.append(Outage(a, b, False))
                break
    return sorted(out, key=lambda o: o.start)


def build(plan: Plan, season: Season, seed: int = 7, category: str = "IV") -> HomeScenario:
    rng = random.Random(seed)
    family = rng.choice(LAST)
    used: set[str] = set()

    def name(g):
        while True:
            n = rng.choice(FIRST[g])
            if n not in used:
                used.add(n)
                return f"{n} {family}"

    street = plan.spots["street"][0]
    p = season.prayers
    people: list[Person] = []

    def person(pid, role, g, sleep_spot, arrive=0, leave=DAY):
        pe = Person(id=pid, name=name(g), role=role, gender=g, speed=rng.uniform(0.9, 1.3),
                    arrive=arrive, leave=leave, entry=sleep_spot, car_bay=None, desk=sleep_spot)
        people.append(pe)
        return pe

    s1 = plan.spots["bed1_sleep"]
    s2 = plan.spots["bed2_sleep"]
    father = person("f", "father", "m", s1[0])
    mother = person("m", "mother", "f", s1[1])
    dadi = person("d", "grandmother", "f", plan.spots["bed3_sleep"][0])
    k1 = person("k1", "school", rng.choice("fm"), s2[0])
    k2 = person("k2", "school", rng.choice("fm"), s2[1])
    uni = person("u", "student", rng.choice("fm"), s2[2])
    helper = person("h", "helper", "f", plan.spots["kitchen_work"][1], arrive=hm("09:00"), leave=hm("13:30"))
    helper.entry = street

    def j(base, spread=600):
        return base + rng.randint(-spread, spread)

    def day_of(pe, wake, out_at=None, back_at=None, nap=True, bed=hm("23:00"), prays=0.6):
        sleep = pe.desk
        d = [Stay(0, sleep, "Asleep")]
        if rng.random() < prays:
            d.append(Stay(p["Fajr"], plan.spots["prayer_mat"][0], "Fajr prayer", pool="prayer_mat"))
            d.append(Stay(p["Fajr"] + 900, sleep, "Asleep"))
        bath = "bath1_spot" if sleep in s1 else "bath2_spot"
        d.append(Stay(wake, plan.spots[bath][0], "Bath", pool=bath))
        d.append(Stay(wake + 900, plan.spots["dining_seat"][0], "Breakfast", pool="dining_seat"))
        if out_at:
            d.append(Stay(out_at, street, "Out"))
            d.append(Stay(back_at, plan.spots["sofa"][0], "Home, resting", pool="sofa"))
        if nap and season.t_max > 34:
            d.append(Stay(hm("14:45"), sleep, "Afternoon nap"))
            d.append(Stay(hm("16:15"), plan.spots["sofa"][0], "In the lounge", pool="sofa"))
        for nm in ("Asr", "Maghrib", "Isha"):
            if rng.random() < prays and p[nm] > (back_at or 0):
                d.append(Stay(p[nm], plan.spots["prayer_mat"][0], f"{nm} prayer", pool="prayer_mat"))
                d.append(Stay(p[nm] + 600, plan.spots["sofa"][0], "In the lounge", pool="sofa"))
        d.append(Stay(hm("20:30"), plan.spots["dining_seat"][0], "Dinner", pool="dining_seat"))
        d.append(Stay(hm("21:15"), plan.spots["sofa"][0], "TV", pool="sofa"))
        d.append(Stay(bed, sleep, "Asleep"))
        d.sort(key=lambda s: s.t)
        return d

    father.day = day_of(father, j(hm("06:45")), j(hm("08:20")), j(hm("17:45"), 1200), nap=False,
                        bed=j(hm("23:15")))
    uni.day = day_of(uni, j(hm("07:15")), j(hm("08:40")), j(hm("15:45"), 1200), bed=j(hm("23:30")))
    for k in (k1, k2):
        k.day = day_of(k, j(hm("06:30"), 300), hm("07:20"), j(hm("14:15"), 300), bed=j(hm("22:15")), prays=0.4)
    mother.day = day_of(mother, j(hm("06:15")), bed=j(hm("23:00")))
    mother.day += [Stay(hm("07:00"), plan.spots["stove"][0], "Making breakfast"),
                   Stay(hm("07:40"), plan.spots["sofa"][0], "In the lounge", pool="sofa"),
                   Stay(hm("12:30"), plan.spots["stove"][0], "Cooking lunch"),
                   Stay(hm("13:30"), plan.spots["dining_seat"][0], "Lunch", pool="dining_seat"),
                   Stay(hm("14:15"), plan.spots["sofa"][0], "In the lounge", pool="sofa"),
                   Stay(hm("19:30"), plan.spots["stove"][0], "Cooking dinner")]
    mother.day.sort(key=lambda s: s.t)
    dadi.day = day_of(dadi, j(hm("06:00")), bed=j(hm("22:00")), prays=0.95)
    dadi.day += [Stay(hm("09:30"), plan.spots["drawing_seat"][0], "Visitors in the drawing room",
                      pool="drawing_seat"),
                 Stay(hm("11:00"), plan.spots["sofa"][0], "In the lounge", pool="sofa")]
    dadi.day.sort(key=lambda s: s.t)
    helper.day = [Stay(hm("09:00"), plan.spots["kitchen_work"][0], "Washing dishes"),
                  Stay(hm("09:40"), plan.spots["washer"][0], "Laundry"),
                  Stay(hm("11:00"), plan.spots["clothesline"][0], "Hanging clothes"),
                  Stay(hm("11:30"), plan.spots["iron"][0], "Ironing"),
                  Stay(hm("12:15"), plan.spots["kitchen_work"][1], "Cleaning the kitchen"),
                  Stay(hm("13:30"), street, "Leaving", kind="leave")]

    # deferrable jobs: what the family asks for and how late it may finish
    requests = [
        Request("iron-am", j(hm("06:50"), 300), "iron", "spine", 900, hm("07:40"), "m", "Ironing school uniforms"),
        Request("laundry", hm("09:45"), "washer", "yard", 3600, hm("17:00"), "h", "Laundry"),
        Request("iron-day", hm("11:30"), "iron", "spine", 1500, hm("18:00"), "h", "Ironing the laundry"),
    ]
    # water: showers, wudu, cooking, dishes, laundry, flushes (litres)
    water = []
    for pe in people:
        for s in pe.day:
            if s.label == "Bath":
                water.append((s.t + 120, 45.0, f"{pe.name.split()[0]}'s shower"))
            elif s.label.endswith("prayer"):
                water.append((s.t, 4.0, "wudu"))
    water += [(hm("07:10"), 15, "breakfast"), (hm("09:10"), 40, "dishes"), (hm("10:00"), 90, "laundry"),
              (hm("12:45"), 25, "cooking"), (hm("14:30"), 35, "dishes"), (hm("19:45"), 30, "cooking"),
              (hm("21:30"), 40, "dishes")]
    for _ in range(30):
        water.append((rng.randint(hm("06:00"), hm("23:00")), 8.0, "flush"))
    water.sort()
    meals = [(hm("07:05"), 180), (hm("13:20"), 240), (hm("20:20"), 300)]

    r = rng.random()
    day_factor = 1.0 if r < 0.7 else (0.8 if r < 0.9 else 0.45)
    forecast = max(0.3, min(1.0, day_factor + rng.uniform(-0.1, 0.1)))
    cloud = []
    for _ in range(rng.randint(0, 4)):
        a = rng.randint(season.sunrise + 3600, season.sunset - 3600)
        cloud.append((a, a + rng.randint(600, 1800), rng.uniform(0.3, 0.6)))
    sags = []
    for _ in range(rng.randint(1, 3)):
        a = rng.randint(hm("18:30"), hm("23:00"))
        sags.append((a, a + rng.randint(300, 1500), rng.uniform(176, 189)))

    outages = _outages(random.Random(f"outages-{seed}-{category}"), category)
    return HomeScenario(plan, season, seed, category, people, outages, requests, water,
                        meals, cloud, day_factor, forecast, sags)


def learned_occupancy(plan: Plan, season: Season, seed: int, days: int = 4) -> dict[str, list[tuple[int, int]]]:
    """What a controller would learn from presence sensors over `days` earlier days.

    Each earlier day is a different generated day of the same household (different seed);
    a room counts as usually occupied in a 30-minute slot if someone was in it on at least
    half of those days. Not today's script — the controller never sees that.
    """
    slots = 48
    counts: dict[str, list[int]] = {}
    for k in range(days):
        sc = build(plan, season, seed=10_000 + seed * 10 + k)
        seen: dict[str, set[int]] = {}
        for p in sc.people:
            stays = sorted(p.day, key=lambda s: s.t)
            for s, nxt in zip(stays, stays[1:] + [None]):
                if s.label in ("Out", "Leaving") or s.kind == "leave":
                    continue
                room = plan.room_at(*s.spot)
                if room is None:
                    continue
                end = nxt.t if nxt else DAY
                for b in range(s.t // 1800, min(slots, (end - 1) // 1800 + 1)):
                    seen.setdefault(room, set()).add(b)
        for room, bins in seen.items():
            c = counts.setdefault(room, [0] * slots)
            for b in bins:
                c[b] += 1
    out: dict[str, list[tuple[int, int]]] = {}
    for room, c in counts.items():
        spans, start = [], None
        for b in range(slots + 1):
            on = b < slots and c[b] * 2 >= days
            if on and start is None:
                start = b
            elif not on and start is not None:
                spans.append((start * 1800, b * 1800))
                start = None
        if spans:
            out[room] = spans
    return out


def describe(sc: HomeScenario) -> str:
    lines = [f"Feeder category {sc.category}: {CATEGORIES[sc.category]} h published load-shedding"]
    for o in sc.outages:
        lines.append(f"  {clock(o.start)}-{clock(o.end)}  {'published' if o.published else 'UNANNOUNCED'}")
    return "\n".join(lines)
