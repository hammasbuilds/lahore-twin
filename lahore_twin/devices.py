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
import zlib
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

    def __post_init__(self):
        # no two rooms are built alike: +-25% on envelope and thermal mass, fixed per
        # room id (crc32, not hash(), which changes between processes). Identical
        # rooms started together cycle their compressors in lockstep, which no real
        # building does.
        h = zlib.crc32(self.id.encode())
        self.envelope = 0.75 + 0.5 * ((h & 0xFFFF) / 0xFFFF)
        self.mass = 0.75 + 0.5 * ((h >> 16) / 0xFFFF)

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
        ua = 6.0 * self.area * self.envelope
        cap = 20e3 * self.area * self.mass
        gains = people * HEAT_PERSON + (self.light_watts if light_on else 0.0)
        # inverter AC (what Lahore offices mostly fit): capacity modulates across the
        # band instead of cycling on and off: 0% at setpoint - band, 100% at + band
        if self.has_ac and ac_enabled:
            frac = min(1.0, max(0.0, (self.temp - (SETPOINT - BAND)) / (2 * BAND)))
        else:
            frac = 0.0
        self.compressor = frac > 0
        cooling = self.ac_capacity * frac
        ach = 3.0 if self.vent_boost else 1.0
        # outdoor air brings outdoor heat: rho*cp/3600 = 0.335 W per (m3/h)·K. In a Lahore
        # afternoon more ventilation means more cooling, so a vent boost is never free.
        vent = 0.335 * self.volume * ach * (outdoor_temp(t) - self.temp)
        self.temp += dt * (ua * (outdoor_temp(t) - self.temp) + vent + gains - cooling) / cap
        self.co2 += dt * (people * GEN / self.volume - ach / 3600.0 * (self.co2 - C_OUT))
        return cooling / COP
