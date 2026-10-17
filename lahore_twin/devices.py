"""Room physics and the devices that sense and act on it.

Each room is one well-mixed air volume:

* temperature — first-order RC: ``C dT/dt = UA (T_out - T) + gains - cooling``
* CO2 — mass balance: ``dC/dt = n * G / V - ACH/3600 * (C - C_out)``

The constants are typical values for a lightweight office, not a calibration
of any real building; they decide how fast rooms warm, cool and go stuffy,
which is what the rules react to.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

C_OUT = 420.0            # outdoor CO2, ppm
GEN = 5.2                # CO2 per seated adult: 0.0052 L/s -> 5.2 ppm*m3/s
CEIL = 3.0               # ceiling height, m
SETPOINT = 24.0
BAND = 0.5
COP = 3.0
HEAT_PERSON = 100.0      # sensible W per person
LPD = {"corridor": 5.0, "washroom": 6.0, "storage": 4.0, "electrical": 6.0}
LPD_DEFAULT = 9.0        # lighting W/m2


def outdoor_temp(t: float) -> float:
    """Lahore, mid-October: about 20 C before dawn, 33 C mid-afternoon."""
    h = t / 3600.0
    return 26.5 + 6.5 * math.sin(2 * math.pi * (h - 9.0) / 24.0)


@dataclass
class RoomEnv:
    id: str
    kind: str
    area: float
    has_ac: bool
    temp: float = 26.0
    co2: float = C_OUT + 30
    compressor: bool = False
    vent_boost: bool = False

    @property
    def volume(self) -> float:
        return self.area * CEIL

    @property
    def light_watts(self) -> float:
        return LPD.get(self.kind, LPD_DEFAULT) * self.area

    @property
    def ac_capacity(self) -> float:      # thermal W
        return 120.0 * self.area

    def step(self, dt: float, t: float, people: int, light_on: bool, ac_enabled: bool) -> float:
        """Advance dt seconds. Returns electrical watts drawn by the AC."""
        ua = 6.0 * self.area
        cap = 20e3 * self.area
        gains = people * HEAT_PERSON + (self.light_watts if light_on else 0.0)
        if self.has_ac and ac_enabled:
            if self.temp > SETPOINT + BAND:
                self.compressor = True
            elif self.temp < SETPOINT - BAND:
                self.compressor = False
        else:
            self.compressor = False
        cooling = self.ac_capacity if self.compressor else 0.0
        self.temp += dt * (ua * (outdoor_temp(t) - self.temp) + gains - cooling) / cap
        ach = 3.0 if self.vent_boost else 1.0
        self.co2 += dt * (people * GEN / self.volume - ach / 3600.0 * (self.co2 - C_OUT))
        return cooling / COP if self.compressor else 0.0
