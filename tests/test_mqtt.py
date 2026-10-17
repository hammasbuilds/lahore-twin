"""The MQTT bridge against a fake broker that speaks the wire protocol."""

import json
import socket
import struct
import threading
import time

from lahore_twin.bus import Bus, topic_matches
from lahore_twin.mqtt import (CONNACK, CONNECT, PINGREQ, PINGRESP, PUBLISH, SUBACK, SUBSCRIBE, Bridge,
                              Client, packet, parse_publish, read_packet)
from lahore_twin.office import hm
from lahore_twin.plan import Plan
from lahore_twin.rules import Automation


class FakeBroker:
    """Accepts one client, records what it publishes, and can push messages to it."""

    def __init__(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.published: list[tuple[str, bytes]] = []
        self.subscriptions: list[str] = []
        self.client_id = None
        self.conn = None
        self.ready = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        self.conn, _ = self.srv.accept()
        while True:
            try:
                kind, flags, body = read_packet(self.conn)
            except (ConnectionError, OSError):
                return
            if kind == CONNECT:
                n = struct.unpack("!H", body[10:12])[0]
                self.client_id = body[12:12 + n].decode()
                self.conn.sendall(packet(CONNACK, b"\x00\x00"))
            elif kind == SUBSCRIBE:
                pid = body[:2]
                n = struct.unpack("!H", body[2:4])[0]
                self.subscriptions.append(body[4:4 + n].decode())
                self.conn.sendall(packet(SUBACK, pid + b"\x00"))
                self.ready.set()
            elif kind == PUBLISH:
                topic, payload = parse_publish(flags, body)
                self.published.append((topic, payload))
                if any(topic_matches(s, topic) for s in self.subscriptions):
                    self.push(topic, payload)      # a real 3.1.1 broker echoes to the sender
            elif kind == PINGREQ:
                self.conn.sendall(packet(PINGRESP, b""))

    def push(self, topic: str, payload: bytes):
        t = topic.encode()
        self.conn.sendall(packet(PUBLISH, struct.pack("!H", len(t)) + t + payload))


def _wait(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_a_real_sensor_drives_the_rules_and_the_command_reaches_the_broker():
    broker = FakeBroker()
    plan = Plan.load("office.json")
    bus = Bus()
    auto = Automation(bus, plan, "pir", [])
    client = Client("127.0.0.1", broker.port, client_id="test-node")
    bridge = Bridge(bus, client)
    assert broker.client_id == "test-node"
    assert _wait(lambda: "lahore-twin/device/office/+/motion" in broker.subscriptions)

    bus.now = hm("10:00")
    broker.push("lahore-twin/device/office/meet_s/motion", b"1")   # an ESP32 PIR fires
    assert _wait(lambda: client.poll(0.05) >= 0 and auto.rooms["meet_s"].light)
    assert bridge.received == 1

    # the rule's reaction went out; the injected motion itself was not echoed back
    assert _wait(lambda: any(t == "lahore-twin/state/office/meet_s/light" for t, _ in broker.published))
    topics = [t for t, _ in broker.published]
    assert "lahore-twin/state/office/meet_s/motion" not in topics
    light = next(json.loads(p) for t, p in broker.published if t == "lahore-twin/state/office/meet_s/light")
    assert light["payload"] is True and "motion in Meeting room S" in light["text"]
    client.close()


def test_commands_from_outside_are_refused():
    broker = FakeBroker()
    bus = Bus()
    seen = []
    bus.subscribe("#", seen.append)
    client = Client("127.0.0.1", broker.port)
    Bridge(bus, client)
    assert _wait(lambda: broker.ready.is_set())
    broker.push("lahore-twin/device/office/work/light", b'{"payload": true}')   # not an inbound topic
    broker.push("lahore-twin/state/office/work/motion", b'{"payload": 1}')     # our own echo
    broker.push("lahore-twin/device/office/work/motion", b'{"payload": 1}')
    _wait(lambda: client.poll(0.05) >= 0 and len(seen) >= 1)
    assert [m.topic for m in seen] == ["office/work/motion"]
    client.close()


def test_long_remaining_length_round_trips():
    a, b = socket.socketpair()
    payload = b"x" * 20000                      # needs a 3-byte remaining length
    a.sendall(packet(PUBLISH, struct.pack("!H", 1) + b"t" + payload))
    kind, flags, body = read_packet(b)
    assert kind == PUBLISH and parse_publish(flags, body) == ("t", payload)
    a.close()
    b.close()


def test_live_mode_streams_the_building_to_a_broker(capsys):
    from lahore_twin import live
    broker = FakeBroker()
    live.main(["--port", str(broker.port), "--speed", "1000000", "--start", "09:00", "--hours", "0.25"])
    assert _wait(lambda: len(broker.published) > 50)
    topics = {t for t, _ in broker.published}
    assert any(t.endswith("/light") for t in topics) and any(t.startswith("lahore-twin/state/office/gate/") for t in topics)
    # nothing from before --start was sent
    first = json.loads(broker.published[0][1])
    assert first["t"] >= hm("09:00")


def test_an_echoing_broker_does_not_feed_the_building_its_own_readings():
    """The reviewer's case: mosquitto echoes our publishes; nothing may come back in."""
    from lahore_twin.office import build
    from lahore_twin.sim import Sim
    broker = FakeBroker()
    sim = Sim(build(Plan.load("office.json"), seed=7), "pir")
    client = Client("127.0.0.1", broker.port)
    bridge = Bridge(sim.bus, client)
    assert _wait(lambda: broker.ready.is_set())
    sim.run(hm("07:00"), hm("09:30"), on_tick=lambda t: client.poll(0))
    _wait(lambda: client.poll(0.05) >= 0 and False, timeout=0.5)
    assert bridge.sent > 100 and bridge.received == 0
    assert sim.att.estimate_inside() == sim.series["roll_truth"][-1] or abs(
        sim.att.estimate_inside() - sim.series["roll_truth"][-1]) <= 1
    client.close()


def test_live_mode_closes_the_day_once(capsys):
    from lahore_twin import live
    broker = FakeBroker()
    live.main(["--port", str(broker.port), "--speed", "1000000", "--start", "20:30", "--hours", "1"])
    assert _wait(lambda: any("no_badge_out" in t for t, _ in broker.published))
    stamps = [json.loads(p)["t"] for t, p in broker.published if t.endswith("/no_badge_out")]
    assert stamps and all(s == hm("21:00") - 1 for s in stamps)
    assert len(stamps) == len(set(json.loads(p)["payload"] for t, p in broker.published
                                  if t.endswith("/no_badge_out")))
