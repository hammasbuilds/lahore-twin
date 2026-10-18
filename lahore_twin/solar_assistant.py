"""Translate between SolarAssistant's MQTT topics and the home bus.

SolarAssistant (a small box many Pakistani solar homes already run) reads the
hybrid inverter over its serial or USB port and publishes plain MQTT topics.
This adapter lets GridSense run against a real inverter without custom wiring:

* inbound  — SolarAssistant readings are rescaled and republished as the home
             topics GridSense already listens to (battery SOC, PV power, load,
             grid voltage and grid up/down);
* outbound — GridSense's inverter settings (`home/inverter/settings`) become
             SolarAssistant `.../set` messages: output source priority and the
             grid charge current.

The topic names live in plans/solar_assistant_map.json so they can be matched to
an installation without touching code. Tested against a fake broker; not yet run
against a real SolarAssistant box.
"""

from __future__ import annotations

import json
from pathlib import Path

from .bus import Bus, Message

MAP = Path(__file__).resolve().parent.parent / "plans" / "solar_assistant_map.json"


class SolarAssistantAdapter:
    def __init__(self, bus: Bus, client, mapping: dict | None = None):
        self.bus, self.client = bus, client
        self.map = mapping or json.loads(MAP.read_text(encoding="utf-8"))
        self.prefix = self.map["prefix"]
        self.routes = self.map["inbound"]
        self.received = 0
        self.sent = 0
        self._grid_up = None
        previous = getattr(client, "on_message", None)

        def on_message(topic: str, payload: bytes) -> None:
            self._in(topic, payload)
            if previous:
                previous(topic, payload)

        client.on_message = on_message
        for r in {r["from"] for r in self.routes}:
            client.subscribe(self.prefix + r)
        bus.subscribe("home/inverter/settings", self._out)

    def _in(self, topic: str, raw: bytes) -> None:
        if not topic.startswith(self.prefix):
            return
        key = topic[len(self.prefix):]
        try:
            value = float(raw.decode("utf-8").strip())
        except (UnicodeDecodeError, ValueError):
            return                       # SolarAssistant also publishes text states; not ours
        for r in self.routes:
            if r["from"] != key:
                continue
            if "threshold" in r:
                up = value > r["threshold"]
                if up != self._grid_up:          # publish grid state on change only, like the simulator
                    self._grid_up = up
                    self.bus.publish(r["to"], up, None, "Grid is back" if up else "Power cut — grid is down")
            else:
                self.bus.publish(r["to"], round(value * r.get("scale", 1.0), 4))
            self.received += 1

    def _out(self, m: Message) -> None:
        if not isinstance(m.payload, dict):
            return
        out = self.map["outbound"]
        mode = out["modes"].get(m.payload.get("mode"))
        if mode:
            self.client.publish(self.prefix + out["settings_topic"], mode)
            self.sent += 1
        kw = m.payload.get("grid_charge_kw")
        if kw is not None and out.get("charge_topic"):
            self.client.publish(self.prefix + out["charge_topic"], str(round(kw * out["charge_amps_per_kw"])))
            self.sent += 1
