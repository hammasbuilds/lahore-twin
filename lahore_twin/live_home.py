"""Run the house against a real MQTT broker.

    python -m lahore_twin.live_home --broker 192.168.1.10 --speed 60
    python -m lahore_twin.live_home --broker localhost --speed 1 --solar-assistant

Every home bus message appears on ``lahore-twin/state/home/...``. Real presence
and temperature sensors publish to ``lahore-twin/device/home/<room>/presence``
and ``.../temp``. With ``--solar-assistant``, readings from a SolarAssistant box
(battery, solar, load, grid voltage) also feed GridSense, and its inverter
settings go back to SolarAssistant's ``/set`` topics (see
plans/solar_assistant_map.json).
"""

from __future__ import annotations

import argparse
import time

from .climate import SEASONS
from .home import DAY, build
from .home_sim import HomeSim
from .mqtt import Bridge, Client
from .office import clock
from .plan import Plan
from .solar_assistant import SolarAssistantAdapter

INBOUND_HOME = ("home/+/presence", "home/+/temp", "home/grid/state", "home/grid/voltage",
                "home/battery/soc", "home/pv/kw", "home/house/load", "home/tank/level")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Run the simulated house against an MQTT broker")
    ap.add_argument("--broker", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--prefix", default="lahore-twin/")
    ap.add_argument("--mode", default="gridsense", choices=("default", "ups", "gridsense_eco", "gridsense"))
    ap.add_argument("--season", default="june", choices=tuple(SEASONS))
    ap.add_argument("--speed", type=float, default=60.0, help="simulated seconds per real second")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--solar-assistant", action="store_true", help="also read and command a SolarAssistant box")
    a = ap.parse_args(argv)

    sim = HomeSim(build(Plan.load("home.json"), SEASONS[a.season], seed=a.seed), a.mode)
    client = Client(a.broker, a.port, client_id=f"lahore-twin-home-{a.seed}")
    bridge = Bridge(sim.bus, client, prefix=a.prefix, inbound=INBOUND_HOME)
    adapter = SolarAssistantAdapter(sim.bus, client) if a.solar_assistant else None
    wall0 = time.monotonic()
    last_ping = [wall0]
    t1 = min(DAY, int(a.hours * 3600))

    def on_tick(t: int) -> None:
        client.poll(0)
        delay = wall0 + (t + 1) / a.speed - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        now = time.monotonic()
        if now - last_ping[0] > 20:
            last_ping[0] = now
            client.ping()
        if t % 1800 == 0:
            extra = f"  from SolarAssistant {adapter.received}" if adapter else ""
            print(f"{clock(t)}  sent {bridge.sent}  from devices {bridge.received}{extra}", flush=True)

    try:
        sim.run(until=t1, on_tick=on_tick)
    finally:
        client.close()


if __name__ == "__main__":
    main()
