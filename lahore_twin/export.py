"""Run the office day under every rule set and write the viewer's replay file.

The replay is a JavaScript file (``window.REPLAY = {...}``) rather than JSON so
the viewer opens straight from disk: browsers refuse ``fetch`` on file:// URLs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .office import build
from .plan import Plan
from .rules import MODES
from .sim import T0, T1, Sim

ROOT = Path(__file__).resolve().parent.parent


def source_digest() -> str:
    """Hash of everything that decides the replay: the engine and the floor plans.

    Line endings are normalised so a CRLF checkout does not look stale.
    """
    h = hashlib.sha256()
    files = sorted((ROOT / "lahore_twin").glob("*.py")) + sorted((ROOT / "plans").glob("*.json"))
    for f in files:
        h.update(f.relative_to(ROOT).as_posix().encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def run_all(seed: int = 7, plan_file: str = "office.json") -> tuple[dict, dict[str, Sim]]:
    plan = Plan.load(plan_file)
    sc = build(plan, seed=seed)
    sims = {mode: Sim(sc, mode).run() for mode in MODES}
    first = sims[MODES[0]]
    replay = {
        "meta": {"seed": seed, "t0": T0, "t1": T1, "title": plan.name,
                 "prayer": sc.prayer_times, "digest": source_digest()},
        "plan": plan.to_json() | {"ac_rooms": plan.ac_rooms},
        "bookings": [{"id": b.id, "room": b.room, "title": b.title, "start": b.start, "end": b.end,
                      "attendees": b.attendees, "no_show": b.no_show} for b in sc.bookings],
        **first.replay_people(),
        "modes": {mode: s.replay_mode() for mode, s in sims.items()},
    }
    return replay, sims


def write(replay: dict, out: Path | None = None) -> Path:
    out = out or ROOT / "viewer" / "replay.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    # bytes, not write_text: Windows text mode would turn the newline into CRLF
    out.write_bytes(("window.REPLAY = " + json.dumps(replay, separators=(",", ":"), ensure_ascii=False)
                     + ";\n").encode("utf-8"))
    return out


if __name__ == "__main__":
    r, _ = run_all()
    p = write(r)
    print(f"wrote {p} ({p.stat().st_size / 1e6:.2f} MB)")
