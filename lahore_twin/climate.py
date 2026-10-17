"""Seasons for Lahore: outdoor temperature, daylight, solar yield, prayer times.

Values are typical, stated so they can be checked, not a weather record:

* temperature: daily min/max of Lahore's climate normals for the month;
* solar yield: kWh per kWp per day, NASA POWER via Profile Solar (summer 6.3,
  autumn 4.8, winter 3.6, spring 6.5);
* sunrise/sunset and prayer times: mid-month for Lahore (Hanafi Asr), rounded
  to five minutes;
* peak tariff window: K-Electric's published schedule (Apr–Oct 18:30–22:30,
  Nov–Mar 18:00–22:00).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 3600 + int(m) * 60


@dataclass(frozen=True)
class Season:
    name: str
    t_min: float
    t_max: float
    sunrise: int
    sunset: int
    pv_kwh_per_kwp: float
    peak: tuple[int, int]
    prayers: dict = field(default_factory=dict)

    def outdoor_temp(self, t: float) -> float:
        """Coolest just before sunrise, hottest at 15:00, smooth between."""
        h = (t % 86400) / 3600.0
        lo_h, hi_h = self.sunrise / 3600.0, 15.0
        if lo_h <= h <= hi_h:
            f = (h - lo_h) / (hi_h - lo_h)
            w = 0.5 - 0.5 * math.cos(math.pi * f)
        else:
            span = 24.0 - hi_h + lo_h
            f = ((h - hi_h) % 24.0) / span
            w = 0.5 + 0.5 * math.cos(math.pi * f)
        return self.t_min + (self.t_max - self.t_min) * w

    def clear_sky_shape(self, t: float) -> float:
        """Relative PV output 0..1 over the day (sine of the sun's arc, sharpened)."""
        tt = t % 86400
        if not (self.sunrise < tt < self.sunset):
            return 0.0
        x = math.pi * (tt - self.sunrise) / (self.sunset - self.sunrise)
        return math.sin(x) ** 1.3

    def shape_integral_hours(self) -> float:
        """Integral of the shape over a day, in hours, so yield can be normalised."""
        step = 60
        return sum(self.clear_sky_shape(t) for t in range(0, 86400, step)) * step / 3600.0

    def is_peak(self, t: float) -> bool:
        tt = t % 86400
        return self.peak[0] <= tt < self.peak[1]


JUNE = Season(
    name="June", t_min=29.0, t_max=41.0, sunrise=hm("05:00"), sunset=hm("19:10"),
    pv_kwh_per_kwp=6.3, peak=(hm("18:30"), hm("22:30")),
    prayers={"Fajr": hm("03:45"), "Zuhr": hm("13:30"), "Asr": hm("17:15"),
             "Maghrib": hm("19:15"), "Isha": hm("20:50")},
)

OCTOBER = Season(
    name="October", t_min=19.0, t_max=33.0, sunrise=hm("06:15"), sunset=hm("17:45"),
    pv_kwh_per_kwp=4.8, peak=(hm("18:30"), hm("22:30")),
    prayers={"Fajr": hm("04:55"), "Zuhr": hm("13:30"), "Asr": hm("16:15"),
             "Maghrib": hm("17:50"), "Isha": hm("19:10")},
)

SEASONS = {"june": JUNE, "october": OCTOBER}
