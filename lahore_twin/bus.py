"""An in-process message bus with MQTT topic semantics.

Topics look like ``office/meet_l/light``. Subscriptions accept the MQTT
wildcards ``+`` (one level) and ``#`` (the rest). Swapping this for a real
broker means replacing ``publish`` with a paho-mqtt call; nothing that
subscribes has to change.

Every message gets an id, and a message published *because of* another one
carries that id as ``cause``. Following ``cause`` backwards answers "why is
this light on?" without guessing.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Message:
    id: int
    t: int
    topic: str
    payload: Any
    cause: int | None = None
    text: str = ""


def topic_matches(pattern: str, topic: str) -> bool:
    p, t = pattern.split("/"), topic.split("/")
    for i, part in enumerate(p):
        if part == "#":
            return True
        if i >= len(t):
            return False
        if part != "+" and part != t[i]:
            return False
    return len(p) == len(t)


@dataclass
class Bus:
    now: int = 0
    log: list[Message] = field(default_factory=list)
    _subs: list[tuple[str, Callable[[Message], None]]] = field(default_factory=list)
    _next: int = 1
    _recent: OrderedDict = field(default_factory=OrderedDict)  # quiet messages not yet logged
    # high-rate telemetry is delivered but not kept, or a day would hold millions
    quiet: tuple[str, ...] = ("motion", "co2", "temp")

    def subscribe(self, pattern: str, fn: Callable[[Message], None]) -> None:
        self._subs.append((pattern, fn))

    def publish(self, topic: str, payload: Any = None, cause: int | None = None, text: str = "") -> Message:
        msg = Message(self._next, self.now, topic, payload, cause, text)
        self._next += 1
        if cause is not None and cause in self._recent:
            # a quiet message just caused something: it has earned a place in the log
            self.log.append(self._recent.pop(cause))
        if topic.rsplit("/", 1)[-1] in self.quiet:
            self._recent[msg.id] = msg
            if len(self._recent) > 5000:
                self._recent.popitem(last=False)
        else:
            self.log.append(msg)
        for pattern, fn in list(self._subs):
            if topic_matches(pattern, topic):
                fn(msg)
        return msg

    def by_id(self) -> dict[int, Message]:
        return {m.id: m for m in self.log}

    def why(self, msg_id: int) -> list[Message]:
        """The chain of causes behind a logged message, newest first."""
        index, chain, cur = self.by_id(), [], msg_id
        while cur is not None and cur in index:
            chain.append(index[cur])
            cur = index[cur].cause
        return chain
