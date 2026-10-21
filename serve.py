"""Serve the Lahore Twin app on 127.0.0.1 and run simulations with your values.

    python serve.py                 # http://127.0.0.1:8860
    python serve.py --port 8861

GET  /                     the app (viewer/), every module in one interface
POST /api/run/<module>     JSON inputs -> {"replay": "runs/<file>.js"}; the module page then
                           opens on that run (?replay=runs/<file>.js)

Standard library only. Binds to 127.0.0.1, never opens a browser. Inputs are checked
against fixed ranges; a run with the same inputs is served from viewer/runs/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VIEWER = ROOT / "viewer"
RUNS = VIEWER / "runs"
LOCK = threading.Lock()                  # one simulation at a time: they are CPU-bound

def _signal_names() -> list[str]:
    from lahore_twin.junctions import signal_names
    return signal_names()


# module -> {input: (kind, default, low, high | choices)}
INPUTS = {
    "office": {"seed": ("int", 7, 1, 999), "staff": ("int", 36, 10, 36), "visitors": ("int", 4, 0, 8)},
    "home": {"seed": ("int", 7, 1, 999), "season": ("choice", "june", ("june", "october")),
             "category": ("choice", "IV", ("I", "III", "IV", "V")),
             "pv_kwp": ("float", 6.0, 0.0, 12.0), "battery_kwh": ("float", 10.0, 1.0, 20.0)},
    "hospital": {"seed": ("int", 7, 1, 999), "arrivals_pct": ("int", 100, 50, 200),
                 "ward_nurses": ("int", 3, 1, 6), "alarm_delay": ("int", 15, 0, 30)},
    "traffic": {"seed": ("int", 7, 1, 999), "per_hour": ("int", 8000, 2000, 12000),
                "period": ("choice", "evening", ("evening", "morning"))},
    "city": {"seed": ("int", 7, 1, 999), "per_hour": ("int", 8000, 2000, 12000)},
    "junctions": {"seed": ("int", 7, 1, 999), "per_hour": ("int", 8000, 2000, 12000),
                  # any of the city's signalised junctions, read from the road network
                  "junction": ("choice", "worst", ("worst", *_signal_names()))},
}


def clean(module: str, raw: dict) -> dict:
    """Validated inputs, or ValueError naming the first bad one."""
    if module not in INPUTS:
        raise ValueError(f"unknown module {module!r}")
    out = {}
    for name, spec in INPUTS[module].items():
        kind, default = spec[0], spec[1]
        v = raw.get(name, default)
        if kind == "choice":
            if v not in spec[2]:
                if len(spec[2]) > 8:      # a long list (every junction) is named by what it is, not read out
                    raise ValueError(f"{name} must be {spec[2][0]!r} or one of the {len(spec[2]) - 1} listed in the form")
                raise ValueError(f"{name} must be one of {', '.join(spec[2])}")
        else:
            try:
                v = int(v) if kind == "int" else float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be a number") from None
            if not spec[2] <= v <= spec[3]:
                raise ValueError(f"{name} must be between {spec[2]} and {spec[3]}")
        out[name] = v
    return out


LOADED: dict[str, str] = {}             # module -> digest of the code this process runs


def loaded_digest(module: str) -> str:
    """The digest of the simulation code as this server process imported it. Python keeps a module
    once imported, so after an edit on disk a running server still runs the old code: keying a run
    by the digest on disk would file old-code results under the new code's name."""
    if module not in LOADED:
        from lahore_twin.export import source_digest
        LOADED[module] = source_digest(module)
    return LOADED[module]


def stale(module: str) -> bool:
    """True when the code on disk is no longer the code this process runs."""
    from lahore_twin.export import source_digest
    return loaded_digest(module) != source_digest(module)


def run_key(module: str, p: dict) -> str:
    """The cache name of a run. The code's digest is part of it: a run cached before a change
    to the simulation would otherwise be served as if the current code had produced it."""
    return hashlib.sha256(json.dumps([module, p, loaded_digest(module)], sort_keys=True).encode()).hexdigest()[:12]


def simulate(module: str, p: dict) -> str:
    """Run the module with inputs p; return the replay's path relative to viewer/."""
    rel = f"runs/{module}-{run_key(module, p)}.js"
    path = VIEWER / rel
    if path.exists():
        return rel
    RUNS.mkdir(exist_ok=True)
    if module == "office":
        from lahore_twin.export import run_all
        replay, _ = run_all(seed=p["seed"], n_staff=p["staff"], n_visitors=p["visitors"])
        body = "window.REPLAY = " + json.dumps(replay, separators=(",", ":"), ensure_ascii=False) + ";\n"
    elif module == "home":
        from lahore_twin.export_home import run_all
        replay, _ = run_all(seed=p["seed"], season=p["season"], category=p["category"],
                            pv_kwp=p["pv_kwp"], battery_kwh=p["battery_kwh"])
        scen = json.dumps({p["season"]: replay}, separators=(",", ":"), ensure_ascii=False)
        body = f"window.HOME_SCENARIOS = {scen};\nwindow.HOME = window.HOME_SCENARIOS[{json.dumps(p['season'])}];\n"
    elif module == "city":
        from lahore_twin.export_city import run_all
        replay = run_all(seed=p["seed"], per_hour=p["per_hour"])
        body = "window.CITY = " + json.dumps(replay, separators=(",", ":"), ensure_ascii=False) + ";\n"
    elif module == "junctions":
        from lahore_twin.export_junctions import run_all
        replay, _ = run_all(seed=p["seed"], per_hour=p["per_hour"], junction=p["junction"])
        body = "window.JUNCTIONS = " + json.dumps(replay, separators=(",", ":"), ensure_ascii=False) + ";\n"
    elif module == "traffic":
        from lahore_twin.export_traffic import run_all
        replay, _ = run_all(seed=p["seed"], per_hour=p["per_hour"], period=p["period"])
        body = "window.TRAFFIC = " + json.dumps(replay, separators=(",", ":"), ensure_ascii=False) + ";\n"
    else:
        from lahore_twin.export_hospital import run_all
        replay, _ = run_all(seed=p["seed"], arrivals_pct=p["arrivals_pct"], ward_nurses=p["ward_nurses"],
                            alarm_delay=p["alarm_delay"])
        body = "window.HOSPITAL = " + json.dumps(replay, separators=(",", ":"), ensure_ascii=False) + ";\n"
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(body.encode("utf-8"))
    tmp.replace(path)
    return rel


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(VIEWER), **kw)

    def log_message(self, fmt, *args):         # quiet: one line per API call only
        if self.path.startswith("/api/"):
            super().log_message(fmt, *args)

    def _json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        parts = self.path.strip("/").split("/")
        if len(parts) != 3 or parts[:2] != ["api", "run"]:
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = json.loads(self.rfile.read(min(n, 10_000)) or b"{}")
            if not isinstance(raw, dict):
                raise ValueError("send a JSON object")
            p = clean(parts[2], raw)
        except (ValueError, json.JSONDecodeError) as e:
            return self._json(400, {"error": str(e)})
        with LOCK:
            if stale(parts[2]):
                return self._json(409, {"error": "the simulation code changed since this server started: restart serve.py"})
            try:
                rel = simulate(parts[2], p)
            except Exception as e:                # report the failure, do not hang the page
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        return self._json(200, {"replay": rel, "inputs": p})


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8860)
    a = ap.parse_args(argv)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"Lahore Twin on http://127.0.0.1:{a.port}  (Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
