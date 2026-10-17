"""Electrical side of the house: solar, battery, hybrid inverter, grid, appliances.

A hybrid inverter sits between four things: the PV array, the battery, the grid
and the house wiring. Each physics step it is told what the loads want, decides
where the power comes from, and reports what actually ran. It enforces what a
real one enforces: its own output rating (overload trips it for a minute), the
battery's charge/discharge limits and cutoff state of charge, and the fact that
during an outage only the circuits it feeds are alive.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# nameplate assumptions (no measured Pakistani appliance table exists; see PLAN.md)
APPLIANCES = {
    #  kind        watts  essential  note
    "fan":        (80, True, "ceiling fan"),
    "light":      (20, True, "LED lights for a room"),
    "fridge":     (150, True, "compressor, ~40% duty"),
    "router":     (15, True, "internet"),
    "tv":         (110, False, "LED TV"),
    "ac":         (1650, False, "1.5-ton inverter AC at full output (5.3 kW cooling / COP 3.2)"),
    "pump":       (750, False, "1 hp water motor, roof tank"),
    "washer":     (500, False, "twin-tub washing machine"),
    "iron":       (1000, False, "steam iron"),
    "microwave":  (1200, False, "microwave"),
}


@dataclass
class Battery:
    capacity_kwh: float = 10.0
    min_soc: float = 0.10          # LFP: 90% usable
    max_charge_kw: float = 5.0
    max_discharge_kw: float = 5.0
    efficiency: float = 0.95       # one-way, applied on charge
    soc: float = 0.60
    throughput_kwh: float = 0.0

    @property
    def usable_kwh(self) -> float:
        return max(0.0, (self.soc - self.min_soc) * self.capacity_kwh)

    def headroom_kwh(self) -> float:
        return max(0.0, (1.0 - self.soc) * self.capacity_kwh)

    def discharge(self, kw: float, dt: float) -> float:
        """Draw up to kw for dt seconds; returns the kW actually delivered."""
        kw = max(0.0, min(kw, self.max_discharge_kw, self.usable_kwh * 3600 / dt))
        self.soc -= kw * dt / 3600 / self.capacity_kwh
        self.throughput_kwh += kw * dt / 3600
        return kw

    def charge(self, kw: float, dt: float) -> float:
        """Push up to kw for dt seconds; returns the kW actually taken from the source."""
        kw = max(0.0, min(kw, self.max_charge_kw, self.headroom_kwh() * 3600 / dt / self.efficiency))
        self.soc += kw * self.efficiency * dt / 3600 / self.capacity_kwh
        self.throughput_kwh += kw * self.efficiency * dt / 3600
        return kw


@dataclass
class InverterSettings:
    """What a Growatt/Sunsynk-style hybrid lets you set; GridSense changes them live."""
    mode: str = "SBU"              # SBU: solar, battery, utility | UTI: utility first
    back_to_grid_soc: float = 0.30 # SBU: below this, loads move to the grid if present
    grid_charge_kw: float = 0.0    # charge the battery from the grid at this rate
    cutoff_soc: float = 0.10       # during an outage the output stops here


@dataclass
class StepResult:
    served: set = field(default_factory=set)      # appliance ids that actually ran
    pv_kw: float = 0.0
    pv_used_kw: float = 0.0
    batt_kw: float = 0.0          # + discharge, - charge
    grid_kw: float = 0.0          # + import, - export
    load_kw: float = 0.0
    tripped: bool = False
    dark: bool = False            # inverter output off during an outage


@dataclass
class Inverter:
    rating_kw: float = 6.0
    battery: Battery = field(default_factory=Battery)
    settings: InverterSettings = field(default_factory=InverterSettings)
    trip_until: int = -1
    trips: int = 0
    shutdown: bool = False        # hit cutoff during an outage; wakes when PV or grid returns

    def step(self, t: int, dt: float, demand: dict[str, float], on_inverter: set[str],
             grid_up: bool, pv_kw: float, export_ok: bool = True) -> StepResult:
        """demand: appliance id -> kW wanted. on_inverter: ids wired to the inverter output."""
        r = StepResult(pv_kw=pv_kw)
        inv_loads = {a: kw for a, kw in demand.items() if a in on_inverter}
        grid_only = {a: kw for a, kw in demand.items() if a not in on_inverter}
        if grid_up:
            r.served |= set(grid_only)
            r.grid_kw += sum(grid_only.values())

        if t < self.trip_until:
            r.tripped = True
            if not grid_up:
                r.dark = True
                self._charge_from(pv_kw, dt, r)
                return r
        inv_kw = sum(inv_loads.values())
        if inv_kw > self.rating_kw:
            # overload: the inverter shuts its output for a minute, as real units do
            self.trips += 1
            self.trip_until = t + 60
            r.tripped = True
            if not grid_up:
                r.dark = True
            else:
                # on grid most hybrids pass the grid straight through (bypass)
                r.served |= set(inv_loads)
                r.grid_kw += inv_kw
            self._charge_from(pv_kw, dt, r)
            r.load_kw = sum(demand[a] for a in r.served)
            return r

        b = self.battery
        if not grid_up:
            if self.shutdown and (pv_kw > 0.3 or b.soc > self.settings.cutoff_soc + 0.05):
                self.shutdown = False
            if not self.shutdown:
                need = inv_kw
                pv_used = min(pv_kw, need)
                need -= pv_used
                available = max(0.0, (b.soc - self.settings.cutoff_soc) * b.capacity_kwh * 3600 / dt)
                if need > 0 and need > min(b.max_discharge_kw, available):
                    self.shutdown = True      # not enough battery left: output stops
                    r.dark = True
                else:
                    r.batt_kw += b.discharge(need, dt)
                    r.served |= set(inv_loads)
                    r.pv_used_kw = pv_used
                    surplus = pv_kw - pv_used
                    if surplus > 0:
                        r.batt_kw -= b.charge(surplus, dt)
                        r.pv_used_kw += min(surplus, b.max_charge_kw)
            else:
                r.dark = True
                self._charge_from(pv_kw, dt, r)
            r.load_kw = sum(demand[a] for a in r.served)
            return r

        # grid present
        self.shutdown = False
        s = self.settings
        r.served |= set(inv_loads)
        need = inv_kw
        pv_used = min(pv_kw, need)
        need -= pv_used
        if s.mode == "SBU" and b.soc > s.back_to_grid_soc and need > 0:
            r.batt_kw += b.discharge(need, dt)
            need -= r.batt_kw
        r.grid_kw += need
        surplus = pv_kw - pv_used
        if surplus > 0:
            took = b.charge(surplus, dt)
            r.batt_kw -= took
            surplus -= took
            pv_used += took
        if s.grid_charge_kw > 0 and b.soc < 1.0:
            took = b.charge(s.grid_charge_kw, dt)
            r.batt_kw -= took
            r.grid_kw += took
        if surplus > 0 and export_ok:
            r.grid_kw -= surplus           # exported: counted as export, not as used at home
        r.pv_used_kw = pv_used
        r.load_kw = sum(demand[a] for a in r.served)
        return r

    def _charge_from(self, pv_kw: float, dt: float, r: StepResult) -> None:
        took = self.battery.charge(pv_kw, dt)
        r.batt_kw -= took
        r.pv_used_kw = took


@dataclass
class RoofTank:
    capacity_l: float = 1000.0
    level_l: float = 600.0
    pump_lpm: float = 40.0
    empty_s: int = 0

    @property
    def fraction(self) -> float:
        return self.level_l / self.capacity_l

    def step(self, dt: float, use_l: float, pumping: bool) -> float:
        """Advance; returns litres actually supplied (short when the tank runs dry)."""
        if pumping:
            self.level_l = min(self.capacity_l, self.level_l + self.pump_lpm * dt / 60)
        supplied = min(use_l, self.level_l)
        self.level_l -= supplied
        if self.level_l <= 0.5:
            self.empty_s += dt
        return supplied
