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
    """Where every kilowatt went in one step. Solar is split exactly once:
    pv_kw = pv_load_kw + pv_batt_kw + pv_out_kw + curtailed_kw."""
    served: set = field(default_factory=set)      # appliance ids that actually ran
    pv_kw: float = 0.0
    pv_load_kw: float = 0.0       # solar straight into the inverter's loads
    pv_batt_kw: float = 0.0       # solar into the battery
    pv_out_kw: float = 0.0        # solar pushed out to the house's grid side (grid-only loads, then export)
    curtailed_kw: float = 0.0     # solar thrown away: battery full and nowhere to send it
    batt_kw: float = 0.0          # + discharge, - charge
    grid_in_kw: float = 0.0       # what the inverter drew from the grid (bypassed loads + charging)
    load_kw: float = 0.0          # inverter loads actually served
    tripped: bool = False
    dark: bool = False            # inverter output off during an outage
    dark_reason: str = ""         # "cutoff" (battery empty) or "overload" (asked for more than it can give)


@dataclass
class Inverter:
    rating_kw: float = 6.0
    battery: Battery = field(default_factory=Battery)
    settings: InverterSettings = field(default_factory=InverterSettings)
    trip_until: int = -1
    trips: int = 0
    shutdown: bool = False        # hit cutoff during an outage; wakes when PV or grid returns

    def capacity_kw(self, grid_up: bool, pv_kw: float) -> float:
        """What the output can carry: the rating on grid (bypass), and in an outage also
        no more than the battery's discharge limit plus the sun."""
        if grid_up:
            return self.rating_kw
        b = self.battery
        batt = b.max_discharge_kw if b.soc > self.settings.cutoff_soc else 0.0
        return min(self.rating_kw, batt + pv_kw)

    def step(self, t: int, dt: float, demand: dict[str, float], on_inverter: set[str],
             grid_up: bool, pv_kw: float, export_ok: bool = True) -> StepResult:
        """demand: appliance id -> kW wanted. on_inverter: ids wired to the inverter output.
        Grid-only loads are the house's business (see the meter in home_sim); this returns
        what the inverter itself did."""
        r = StepResult(pv_kw=pv_kw)
        b = self.battery
        inv_kw = sum(kw for a, kw in demand.items() if a in on_inverter)
        if grid_up:
            r.served |= {a for a in demand if a not in on_inverter}
        allowance = b.max_charge_kw                  # one charge limit, shared by sun and grid

        def bank(kw: float) -> float:
            nonlocal allowance
            took = b.charge(min(kw, allowance), dt)
            allowance -= took
            return took

        overload = inv_kw > self.capacity_kw(grid_up, pv_kw) + 1e-9
        if overload and t >= self.trip_until:
            self.trips += 1
            self.trip_until = t + 60                 # real units shut their output for a minute
        if t < self.trip_until:
            r.tripped = True
            if grid_up:                              # most hybrids pass the grid straight through
                r.served |= {a for a in demand if a in on_inverter}
                r.grid_in_kw += inv_kw
                r.load_kw = inv_kw
            else:
                r.dark, r.dark_reason = True, "overload"
            r.pv_batt_kw = bank(pv_kw)
            rest = pv_kw - r.pv_batt_kw
            r.batt_kw = -r.pv_batt_kw
            if grid_up and export_ok:
                r.pv_out_kw = rest
            else:
                r.curtailed_kw = rest
            return r

        if not grid_up:
            if self.shutdown and (pv_kw > 0.3 or b.soc > self.settings.cutoff_soc + 0.05):
                self.shutdown = False
            if not self.shutdown:
                r.pv_load_kw = min(pv_kw, inv_kw)
                need = inv_kw - r.pv_load_kw
                available_kwh = max(0.0, (b.soc - self.settings.cutoff_soc) * b.capacity_kwh)
                if need > 0 and need * dt / 3600 > available_kwh:
                    self.shutdown = True             # the battery has reached cut-off
                else:
                    r.batt_kw += b.discharge(need, dt)
                    r.served |= {a for a in demand if a in on_inverter}
                    r.load_kw = inv_kw
            if self.shutdown:
                r.dark, r.dark_reason = True, "cutoff"
                r.pv_load_kw = 0.0
            surplus = pv_kw - r.pv_load_kw
            r.pv_batt_kw = bank(surplus)
            r.batt_kw -= r.pv_batt_kw
            r.curtailed_kw = surplus - r.pv_batt_kw  # no grid to send it to
            return r

        # grid present
        self.shutdown = False
        s = self.settings
        r.served |= {a for a in demand if a in on_inverter}
        r.load_kw = inv_kw
        r.pv_load_kw = min(pv_kw, inv_kw)
        need = inv_kw - r.pv_load_kw
        if s.mode == "SBU" and b.soc > s.back_to_grid_soc and need > 0:
            r.batt_kw += b.discharge(need, dt)
            need -= r.batt_kw
        r.grid_in_kw += need
        surplus = pv_kw - r.pv_load_kw
        r.pv_batt_kw = bank(surplus)
        r.batt_kw -= r.pv_batt_kw
        surplus -= r.pv_batt_kw
        if s.grid_charge_kw > 0 and b.soc < 1.0:
            gc = bank(s.grid_charge_kw)
            r.batt_kw -= gc
            r.grid_in_kw += gc
        if export_ok:
            r.pv_out_kw = surplus
        else:
            r.curtailed_kw = surplus
        return r


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
