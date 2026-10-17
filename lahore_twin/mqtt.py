"""A minimal MQTT 3.1.1 client (QoS 0) and a bridge between the bus and a broker.

Standard library only, so the simulator can talk to Mosquitto, EMQX or Home
Assistant's broker without installing anything. QoS 0 is what PIR and relay
nodes use for telemetry and commands on a LAN; no persistence, no retries.

The bridge works in both directions:

* every bus message is published to ``<prefix>state/<topic>`` as JSON
  (``{"t", "payload", "cause", "text"}``) — a dashboard sees the whole building;
* messages a real device publishes to ``<prefix>device/<topic>`` on the topics
  listed in ``inbound`` are injected into the bus, so a physical PIR on an ESP32
  drives the same rules as a simulated one.

The two prefixes never overlap. An MQTT 3.1.1 broker delivers a client's own
publishes back to it when it is subscribed to them; sharing one prefix made every
simulated reading come back as a "device" reading.
"""

from __future__ import annotations

import json
import select
import socket
import struct
from typing import Callable

from .bus import Bus, Message, topic_matches

CONNECT, CONNACK, PUBLISH, SUBSCRIBE, SUBACK, PINGREQ, PINGRESP, DISCONNECT = 1, 2, 3, 8, 9, 12, 13, 14


def _varlen(n: int) -> bytes:
    out = bytearray()
    while True:
        byte, n = n % 128, n // 128
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def packet(kind: int, body: bytes, flags: int = 0) -> bytes:
    return bytes([(kind << 4) | flags]) + _varlen(len(body)) + body


def read_packet(sock: socket.socket) -> tuple[int, int, bytes]:
    """Read one packet: (type, flags, body). Raises ConnectionError on EOF."""
    head = _recv_exact(sock, 1)[0]
    mult, length = 1, 0
    while True:
        b = _recv_exact(sock, 1)[0]
        length += (b & 0x7F) * mult
        if not b & 0x80:
            break
        mult *= 128
    return head >> 4, head & 0x0F, _recv_exact(sock, length) if length else b""


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("broker closed the connection")
        buf += chunk
    return bytes(buf)


def parse_publish(flags: int, body: bytes) -> tuple[str, bytes]:
    tlen = struct.unpack("!H", body[:2])[0]
    topic = body[2:2 + tlen].decode("utf-8")
    rest = body[2 + tlen:]
    if (flags >> 1) & 0x3:          # QoS > 0 carries a packet id
        rest = rest[2:]
    return topic, rest


class Client:
    def __init__(self, host: str = "127.0.0.1", port: int = 1883, client_id: str = "lahore-twin",
                 keepalive: int = 60, timeout: float = 5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        body = _str("MQTT") + bytes([4, 0x02]) + struct.pack("!H", keepalive) + _str(client_id)
        self.sock.sendall(packet(CONNECT, body))
        kind, _, ack = read_packet(self.sock)
        if kind != CONNACK or len(ack) < 2 or ack[1] != 0:
            raise ConnectionError(f"broker refused the connection (CONNACK {ack!r})")
        self._pid = 0
        self.on_message: Callable[[str, bytes], None] | None = None

    def publish(self, topic: str, payload: bytes | str, retain: bool = False) -> None:
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        self.sock.sendall(packet(PUBLISH, _str(topic) + payload, flags=1 if retain else 0))

    def subscribe(self, pattern: str) -> None:
        self._pid = self._pid % 65535 + 1
        body = struct.pack("!H", self._pid) + _str(pattern) + b"\x00"
        self.sock.sendall(packet(SUBSCRIBE, body, flags=0x2))

    def ping(self) -> None:
        self.sock.sendall(packet(PINGREQ, b""))

    def poll(self, timeout: float = 0.0) -> int:
        """Handle whatever the broker has sent. Returns the number of PUBLISHes delivered."""
        n = 0
        while True:
            ready, _, _ = select.select([self.sock], [], [], timeout)
            if not ready:
                return n
            kind, flags, body = read_packet(self.sock)
            if kind == PUBLISH:
                topic, payload = parse_publish(flags, body)
                if self.on_message:
                    self.on_message(topic, payload)
                n += 1
            timeout = 0.0

    def close(self) -> None:
        try:
            self.sock.sendall(packet(DISCONNECT, b""))
        finally:
            self.sock.close()


FROM_DEVICE = "from device: "

# Topics a real device may publish into the building. Commands and alerts are
# produced by the rules, never accepted from outside.
INBOUND = ("office/+/motion", "office/+/co2", "office/+/temp", "office/+/switch",
           "office/gate/badge", "office/gate/beam")


class Bridge:
    def __init__(self, bus: Bus, client: Client, prefix: str = "lahore-twin/", inbound=INBOUND):
        self.bus, self.client, self.prefix, self.inbound = bus, client, prefix, inbound
        self.sent = 0
        self.received = 0
        bus.subscribe("#", self._out)
        client.on_message = self._in
        self.out_prefix = prefix + "state/"
        self.in_prefix = prefix + "device/"
        for pattern in inbound:
            client.subscribe(self.in_prefix + pattern)

    def _out(self, m: Message) -> None:
        if m.text.startswith(FROM_DEVICE):
            return              # it came from the broker; echo only what the rules do about it
        body = {"t": m.t, "payload": m.payload, "cause": m.cause, "text": m.text}
        self.client.publish(self.out_prefix + m.topic, json.dumps(body, ensure_ascii=False, default=str))
        self.sent += 1

    def _in(self, topic: str, raw: bytes) -> None:
        if not topic.startswith(self.in_prefix):
            return
        topic = topic[len(self.in_prefix):]
        if not any(topic_matches(p, topic) for p in self.inbound):
            return
        try:
            data = json.loads(raw.decode("utf-8"))
            payload = data.get("payload", data) if isinstance(data, dict) else data
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = raw.decode("utf-8", "replace")
        self.received += 1
        self.bus.publish(topic, payload, None, f"{FROM_DEVICE}{topic}")
