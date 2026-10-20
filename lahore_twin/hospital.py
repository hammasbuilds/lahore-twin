"""One day at the hospital: who works, who arrives, and what happens to them
that no rule set controls.

Everything here is drawn before the simulation starts, from separate random
streams, so both rule sets meet exactly the same patients, the same alarms and
the same fridge door left open. Numbers marked *assumption* are modelling
choices, not measurements; the research notes in PLAN.md say where the others
come from.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .office import FIRST, LAST, clock

DAY = 86400
H = 3600

COLOURS = ("red", "orange", "yellow", "green", "blue")
COLOUR_MIX = (0.03, 0.12, 0.35, 0.40, 0.10)                       # assumption, typical 5-level mix
AMBULANCE_SHARE = {"red": 0.7, "orange": 0.4, "yellow": 0.1, "green": 0.0, "blue": 0.0}
NEEDS_BLOOD = {"red": 1.0, "orange": 0.9, "yellow": 0.6, "green": 0.2, "blue": 0.0}
NEEDS_XRAY = {"red": 0.5, "orange": 0.5, "yellow": 0.4, "green": 0.3, "blue": 0.05}
NEEDS_DRIP = {"red": 1.0, "orange": 0.7, "yellow": 0.3, "green": 0.0, "blue": 0.0}
ADMIT = {"red": 0.7, "orange": 0.5, "yellow": 0.2, "green": 0.03, "blue": 0.0}
PATIENCE_H = {"yellow": 4.0, "green": 2.5, "blue": 2.0}            # mean wait before leaving unseen
# walk-in arrivals per hour of the day (sums to ~170): quiet before dawn, peaks late morning and evening
ARRIVALS = (4, 3, 2, 2, 2, 2, 3, 5, 7, 9, 11, 11, 10, 9, 8, 8, 8, 9, 10, 11, 11, 9, 7, 5)

SHIFTS = {"morning": (8 * H, 14 * H), "evening": (14 * H, 20 * H), "night": (20 * H, 32 * H)}
ED_STAFF = {"doctor": (3, 3, 2), "nurse": (4, 4, 3), "clerk": (2, 2, 1), "porter": (2, 2, 1),
            "cleaner": (1, 1, 1), "radiographer": (1, 1, 1), "guard": (1, 1, 1)}
WARD_STAFF = {"nurse": (3, 3, 2), "doctor": (1, 1, 1), "cleaner": (1, 1, 1)}

ROLE_COLOURS = {"doctor": "#60a5fa", "nurse": "#2dd4bf", "clerk": "#a3a3a3", "porter": "#fbbf24",
                "cleaner": "#a78bfa", "radiographer": "#38bdf8", "guard": "#94a3b8", "patient": "#f472b6"}


@dataclass
class Staff:
    id: str
    name: str
    role: str
    unit: str            # ed | ward
    shift: str
    start: int           # may exceed DAY for the night crew that comes on at 20:00
    end: int
    speed: float


@dataclass
class EDPatient:
    id: str
    name: str
    arrive: int
    colour: str
    ambulance: bool
    patience: int        # seconds of waiting before leaving unseen (red/orange never leave)
    reg_s: int
    triage_s: int
    consult_s: int
    review_s: int
    blood: bool
    xray: bool
    drip: bool
    admit: bool
    ward: str            # medical (this ward) | other (a bed elsewhere in the main block)
    other_bed_wait: int  # for "other": how long until another ward has a bed
    lab_tat: int         # sample taken -> result
    speed: float


@dataclass
class WardPatient:
    id: str
    name: str
    bed: str             # bed id, e.g. bay_a-3, hdu-1
    discharge: int | None
    drip: bool


@dataclass
class Alarm:
    t: int
    bed: str
    kind: str            # artefact | brief | sustained | critical
    dur: int             # seconds the condition lasts on its own
    care_s: int


@dataclass
class Call:
    t: int
    bed: str
    care_s: int


@dataclass
class Asset:
    id: str
    kind: str            # pump | wheelchair | trolley
    building: str
    spot: tuple[float, float]
    room: str


@dataclass
class HospitalScenario:
    seed: int
    staff: list[Staff]
    ed_patients: list[EDPatient]
    ward_patients: list[WardPatient]
    beds: dict[str, tuple[str, tuple[float, float]]]     # bed id -> (room, spot)
    alarms: list[Alarm]
    calls: list[Call]
    fridge_open: list[tuple[str, int]]                   # (fridge id, time the door is left ajar)
    assets: list[Asset]
    audit: tuple[int, int] = (10 * H, 11 * H)            # hand-hygiene audit on the ward (Today only)
    true_hand_hygiene: float = 0.35                      # MedSense measured 35.1% in an ICU
    audited_hand_hygiene: float = 0.70                   # assumption: staff wash more when watched
    alarm_delay: int = 15                                # Connected: seconds a non-critical alarm waits
    names: dict = field(default_factory=dict)


def ward_beds(ward_plan) -> dict[str, tuple[str, tuple[float, float]]]:
    beds = {}
    for key, pts in ward_plan.spots.items():
        if key.startswith("bed_"):
            room = key[4:]
            for i, p in enumerate(pts, 1):
                beds[f"{room}-{i}"] = (room, p)
    return beds


def _gamma(rng: random.Random, mean: float, k: float = 4.0) -> int:
    return max(1, int(rng.gammavariate(k, mean / k)))


def _trunc_exp(rng: random.Random, mean: float, lo: float, hi: float) -> int:
    while True:
        v = rng.expovariate(1 / mean)
        if lo <= v <= hi:
            return int(v)


def build(ed_plan, ward_plan, seed: int = 7, arrivals_pct: float = 100, ward_nurses: int | None = None,
          alarm_delay: int = 15) -> HospitalScenario:
    """arrivals_pct scales the ED's hourly arrivals; ward_nurses sets nurses per day shift on the
    ward (the night shift has one fewer); alarm_delay is the Connected annunciation delay."""
    r_staff, r_pat = random.Random(seed * 101 + 1), random.Random(seed * 101 + 2)
    r_ward, r_alarm = random.Random(seed * 101 + 3), random.Random(seed * 101 + 4)
    r_misc = random.Random(seed * 101 + 5)
    used: set[str] = set()

    def name(rng) -> str:
        while True:
            n = f"{rng.choice(FIRST[rng.choice('fm')])} {rng.choice(LAST)}"
            if n not in used:
                used.add(n)
                return n

    staff: list[Staff] = []
    ward_table = dict(WARD_STAFF)
    if ward_nurses is not None:
        n = max(1, int(ward_nurses))
        ward_table["nurse"] = (n, n, max(1, n - 1))
    for unit, table in (("ed", ED_STAFF), ("ward", ward_table)):
        for role, counts in table.items():
            for (shift, (s, e)), n in zip(SHIFTS.items(), counts):
                for k in range(n):
                    sid = f"{unit}-{role}-{shift[0]}{k + 1}"
                    staff.append(Staff(sid, name(r_staff), role, unit, shift, s, e, round(r_staff.uniform(1.15, 1.45), 2)))
    # the night crew already on at 00:00 came on at 20:00 yesterday and leaves at 08:00
    for s in list(staff):
        if s.shift == "night":
            staff.append(Staff(s.id + "y", name(r_staff), s.role, s.unit, "night", -4 * H, 8 * H, s.speed))

    pats: list[EDPatient] = []
    for hour, rate in enumerate(ARRIVALS):
        rate = rate * max(0.1, arrivals_pct / 100)
        t = hour * H + r_pat.expovariate(rate / H)
        while t < (hour + 1) * H:
            colour = r_pat.choices(COLOURS, COLOUR_MIX)[0]
            amb = r_pat.random() < AMBULANCE_SHARE[colour]
            pats.append(EDPatient(
                id=f"p{len(pats) + 1:03d}", name=name(r_pat), arrive=int(t), colour=colour, ambulance=amb,
                # gamma, not exponential: few people walk out within minutes of arriving
                patience=_gamma(r_pat, PATIENCE_H[colour] * H, 3) if colour in PATIENCE_H else 10 ** 9,
                reg_s=_gamma(r_pat, 180), triage_s=_gamma(r_pat, 300),
                consult_s=_trunc_exp(r_pat, 540, 300, 900), review_s=_trunc_exp(r_pat, 900, 300, 1500),
                blood=r_pat.random() < NEEDS_BLOOD[colour], xray=r_pat.random() < NEEDS_XRAY[colour],
                drip=r_pat.random() < NEEDS_DRIP[colour], admit=r_pat.random() < ADMIT[colour],
                # a tertiary ED admits to many wards; about 40% are medical (assumption)
                ward="medical" if r_pat.random() < 0.4 else "other", other_bed_wait=_gamma(r_pat, 90 * 60, 2),
                lab_tat=_gamma(r_pat, 3600, 6), speed=round(r_pat.uniform(0.7, 1.2), 2)))
            t += r_pat.expovariate(rate / H)

    beds = ward_beds(ward_plan)
    bed_ids = list(beds)
    occupied = r_ward.sample(bed_ids, 34)                 # the ward starts nearly full
    wps = []
    for i, b in enumerate(sorted(occupied, key=bed_ids.index)):
        wps.append(WardPatient(f"w{i + 1:02d}", name(r_ward), b, None, r_ward.random() < 0.35))
    # after the morning round, about seven go home between 11:00 and 16:00 (never the HDU's)
    for wp in r_ward.sample([w for w in wps if not w.bed.startswith("hdu")], 7):
        wp.discharge = int(r_ward.uniform(11 * H, 16 * H))

    calls = []
    for wp in wps:
        t = r_ward.expovariate(0.15 / H)
        while t < DAY:
            calls.append(Call(int(t), wp.bed, int(r_ward.uniform(180, 360))))
            day = 7 * H <= t < 22 * H
            t += r_ward.expovariate((0.3 if day else 0.15) / H)        # assumption: calls per patient-hour
    calls.sort(key=lambda c: c.t)

    alarms = []
    for b in [b for b in bed_ids if b.startswith("hdu")]:
        t = r_alarm.expovariate(1.0 / H)
        while t < DAY:                                                 # ~1 alarm per monitored bed-hour
            u = r_alarm.random()
            if u < 0.64:                                               # 63.8% false (Korean ICU, 2016)
                kind, dur = "artefact", int(r_alarm.uniform(3, 12) if r_alarm.random() < 0.8 else r_alarm.uniform(15, 40))
                care = 30
            elif u < 0.64 + 0.36 * 0.3:
                kind, dur, care = "brief", int(r_alarm.uniform(5, 14)), 60
            else:
                kind, dur, care = "sustained", 10 ** 6, int(r_alarm.uniform(180, 480))
            alarms.append(Alarm(int(t), b, kind, dur, care))
            t += r_alarm.expovariate(1.0 / H)
    for _ in range(2):                                                 # assumption: two critical events a day
        alarms.append(Alarm(int(r_alarm.uniform(0, DAY - H)), r_alarm.choice([b for b in bed_ids if b.startswith("hdu")]),
                            "critical", 10 ** 6, int(r_alarm.uniform(600, 900))))
    alarms.sort(key=lambda a: a.t)

    fridge = sorted([("ward", int(r_misc.uniform(6 * H, 23 * H))) for _ in range(2)]
                    + [("ed", int(r_misc.uniform(6 * H, 23 * H)))], key=lambda f: f[1])

    assets = []
    def put(kind, building, plan, spots):
        for p in spots:
            assets.append(Asset(f"{kind}-{len([a for a in assets if a.kind == kind]) + 1}", kind, building,
                                tuple(p), plan.room_at(*p)))
    sh = ed_plan.spots
    put("pump", "ed", ed_plan, [(25.6, 6.2), (26.6, 6.2), (27.4, 6.2), (28.2, 12.2), (28.2, 24.2), (25.5, 41)])
    put("wheelchair", "ed", ed_plan, [(23, 46.5), (24, 46.5), (21, 48.5), (12, 9.6), (24.5, 30)])
    put("trolley", "ed", ed_plan, [(28, 46.5), (29.5, 46.5), (23.5, 42.5)])
    # four spare pumps wait in the basement central store under the ED
    bx, by = next(f["origin"] for f in ed_plan.floors if f["id"] == "B1")
    put("pump", "ed", ed_plan, [(bx + 2.5, by + 3), (bx + 3.5, by + 3), (bx + 4.5, by + 3), (bx + 5.5, by + 3)])
    wx, wy = next(f["origin"] for f in ward_plan.floors if f["id"] == "2")
    put("pump", "ward", ward_plan, [(wx + x, wy + y) for x, y in
                                     [(29, 33.5), (30, 33.5), (31, 33.5), (2.4, 3.5), (16.8, 13.5), (14.5, 21.5), (17.5, 25), (7.2, 31.5)]])
    put("wheelchair", "ward", ward_plan, [(wx + 36.5, wy + 13.5), (wx + 32.5, wy + 30)])
    del sh
    return HospitalScenario(seed, staff, pats, wps, beds, alarms, calls, fridge, assets, alarm_delay=int(alarm_delay))


def describe(sc: HospitalScenario) -> str:
    by = {c: sum(1 for p in sc.ed_patients if p.colour == c) for c in COLOURS}
    return (f"{len(sc.ed_patients)} ED arrivals ({', '.join(f'{n} {c}' for c, n in by.items())}); "
            f"{sum(p.ambulance for p in sc.ed_patients)} by ambulance; ward {len(sc.ward_patients)}/{len(sc.beds)} beds, "
            f"{sum(1 for w in sc.ward_patients if w.discharge)} discharges; {len(sc.calls)} call buttons; "
            f"{len(sc.alarms)} HDU monitor alarms ({sum(a.kind == 'artefact' for a in sc.alarms)} false); "
            f"fridge doors left open at {', '.join(f'{f} {clock(t)}' for f, t in sc.fridge_open)}")
