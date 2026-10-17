"""Run the office against a real MQTT broker.

    python -m lahore_twin.live --broker 192.168.1.10 --speed 60
    python -m lahore_twin.live --broker localhost --start 09:00 --hours 1

Every bus message appears on ``lahore-twin/office/...``. A real sensor that
publishes to, say, ``lahore-twin/office/meet_s/motion`` drives the same rules
as the simulated one; see INBOUND in mqtt.py for the accepted topics.
"""

from __future__ import annotations

import argparse
import time

from .mqtt import Bridge, Client
from .office import build, clock, hm
from .plan import Plan
from .sim import T1, Sim


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Run the simulated office against an MQTT broker")
    ap.add_argument("--broker", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--prefix", default="lahore-twin/")
    ap.add_argument("--mode", default="pir+co2", choices=("schedule", "pir", "pir+co2"))
    ap.add_argument("--speed", type=float, default=60.0, help="simulated seconds per real second")
    ap.add_argument("--start", default="07:00")
    ap.add_argument("--hours", type=float, default=14.0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)

    sim = Sim(build(Plan.load("office.json"), seed=args.seed), args.mode)
    t0 = hm(args.start)
    t1 = min(T1, t0 + int(args.hours * 3600))
    client = bridge = wall0 = None
    last_ping = [time.monotonic()]

    def on_tick(t: int) -> None:
        client.poll(0)
        due = wall0 + (t - t0 + 1) / args.speed
        delay = due - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        now = time.monotonic()
        if now - last_ping[0] > 20:          # keepalive is 60 s of wall time, whatever the speed
            last_ping[0] = now
            client.ping()
        if t % 600 == 0:
            print(f"{clock(t)}  sent {bridge.sent}  from devices {bridge.received}", flush=True)

    # the people still live their whole day from 07:00; publishing starts at --start
    if t0 > hm("07:00"):
        sim.run(hm("07:00"), t0)
    client = Client(args.broker, args.port, client_id=f"lahore-twin-{args.seed}")
    bridge = Bridge(sim.bus, client, prefix=args.prefix)
    wall0 = time.monotonic()
    try:
        sim.run(t0, t1, on_tick=on_tick)
    finally:
        client.close()


if __name__ == "__main__":
    main()
