"""Record a walkthrough of the Lahore Twin app and take one screenshot per feature.

    python tools/demo_video.py [--base http://127.0.0.1:8860/] [--out-video PATH]

Drives system Chrome with Playwright (no browser download): opens every module from the
overview, reads an About panel, presses the buttons, types values into "Run with your values",
follows a vehicle on the traffic map, and ends on the theme switch. Writes the MP4 (kept out of
git) and docs/screenshots/*.png. Needs serve.py running. Dev-only: pip install playwright imageio-ffmpeg.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
RUN = {"module": "hospital", "values": {"seed": 7, "arrivals_pct": 150, "ward_nurses": 4, "alarm_delay": 0}}


def warm(base: str) -> None:
    """Simulate the run the video shows once beforehand: the server caches it by its inputs,
    so on camera the typed values come back in seconds with the real result."""
    req = urllib.request.Request(base + "api/run/" + RUN["module"], data=json.dumps(RUN["values"]).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=900) as r:
        print("warm run:", r.read().decode()[:120])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8860/")
    ap.add_argument("--out-video", default=str(Path.home() / "Desktop" / "lahore-twin-demo.mp4"))
    a = ap.parse_args()
    warm(a.base)
    SHOTS.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="twin-demo-"))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True, slow_mo=250)
        ctx = browser.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(tmp),
                                  record_video_size={"width": 1280, "height": 720})
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        page.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)

        def frame():
            return next(f for f in page.frames if f != page.main_frame)

        def wait_module(glob: str):
            for _ in range(120):
                fr = [f for f in page.frames if f != page.main_frame]
                if fr and fr[0].evaluate(f"!!window.{glob}"):
                    return fr[0]
                page.wait_for_timeout(150)
            raise RuntimeError(f"module {glob} never loaded")

        def shot(name: str) -> None:
            page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
            print("screenshot", name)

        def set_time(fr, glob: str, seconds: int) -> None:
            fr.evaluate(f"(t) => {{ window.{glob}.state.t = t; window.{glob}.frame(true); }}", seconds)

        # 1 overview
        page.goto(a.base)
        page.wait_for_function("window.__shell")
        page.wait_for_timeout(1500)
        shot("01-overview")
        page.mouse.wheel(0, 400); page.wait_for_timeout(700); page.mouse.wheel(0, -400)

        # 2 about
        page.click('.card[data-card="hospital"] [data-about]')
        page.wait_for_selector("#dlg[open]"); page.wait_for_timeout(1200)
        page.mouse.move(640, 400); page.mouse.wheel(0, 300); page.wait_for_timeout(600)
        shot("02-about-panel")
        page.click("#dlg [data-close]")

        # 3 office: three floors, rule sets, comparison
        page.click('#nav button[data-go="office"]')
        f = wait_module("__twin")
        set_time(f, "__twin", 10 * 3600 + 20 * 60)
        f.click('#floors button[data-floor="G"]'); page.wait_for_timeout(500)
        shot("03-office-ground-floor")
        f.click('#floors button[data-floor="B1"]'); page.wait_for_timeout(700)
        shot("04-office-basement-car-park")
        f.click('#floors button[data-floor="1"]'); page.wait_for_timeout(500)
        f.click('#modes button[data-mode="schedule"]'); page.wait_for_timeout(400)
        f.click('#modes button[data-mode="pir+co2"]')
        f.click(".tabs button[data-tab=attendance]"); page.wait_for_timeout(700)
        shot("05-office-attendance")
        f.click(".tabs button[data-tab=energy]"); page.wait_for_timeout(700)
        shot("05b-office-compare")

        # 4 home: roof, power flow, controllers
        page.click('#nav button[data-go="home"]')
        f = wait_module("__home")
        set_time(f, "__home", 11 * 3600 + 15 * 60)
        f.click('#floors button[data-floor="R"]'); page.wait_for_timeout(700)
        shot("06-home-roof-solar")
        set_time(f, "__home", 23 * 3600 + 30 * 60)
        f.click('#floors button[data-floor="1"]'); page.wait_for_timeout(500)
        f.click('#modes button[data-mode="default"]'); page.wait_for_timeout(600)
        f.click('#modes button[data-mode="gridsense"]')
        f.click(".tabs button[data-tab=compare]"); page.wait_for_timeout(700)
        shot("07-home-controllers-compare")

        # 5 hospital: ED board, ward floor, campus, comparison
        page.click('#nav button[data-go="hospital"]')
        f = wait_module("__hosp")
        set_time(f, "__hosp", 11 * 3600)
        f.click('#views button[data-view="ed"]'); page.wait_for_timeout(700)
        shot("08-hospital-emergency-board")
        f.click('#views button[data-view="ward"]'); f.click(".tabs button[data-tab=beds]"); page.wait_for_timeout(700)
        shot("09-hospital-ward-beds")
        f.click('#views button[data-view="site"]'); page.wait_for_timeout(800)
        shot("10-hospital-campus")
        f.click('#views button[data-view="ed"]')
        f.click(".tabs button[data-tab=compare]"); page.wait_for_timeout(700)
        shot("11-hospital-compare")

        # 6 traffic: streaming map, follow a vehicle, hotspot, comparison
        page.click('#nav button[data-go="traffic"]')
        f = wait_module("__traffic")
        page.wait_for_timeout(1200)
        shot("12-traffic-map")
        f.click("#follow-random"); page.wait_for_timeout(400)
        for _ in range(6):
            f.evaluate("() => { window.__traffic.state.t += 8; window.__traffic.frame(true); }")
            page.wait_for_timeout(250)
        page.wait_for_timeout(800)
        shot("13-traffic-follow-vehicle")
        f.click(".tabs button[data-tab=hot]")
        f.click("#pane-hot li[data-sig]"); page.wait_for_timeout(1200)
        shot("14-traffic-junction")
        f.click(".tabs button[data-tab=compare]"); page.wait_for_timeout(800)
        shot("15-traffic-compare")

        # 7 run with your own values
        page.click('#nav button[data-go="overview"]')
        page.click(f'.card[data-card="{RUN["module"]}"] [data-run]')
        page.wait_for_selector("#runform")
        for name, v in RUN["values"].items():
            sel = f'#runform [name="{name}"]'
            page.fill(sel, "")
            page.type(sel, str(v), delay=120)
        page.wait_for_timeout(500)
        shot("16-run-with-your-values")
        page.click("#run-go")
        page.wait_for_function("!document.querySelector('#dlg[open]')", timeout=900_000)
        f = wait_module("__hosp")
        f.click(".tabs button[data-tab=compare]"); page.wait_for_timeout(1000)
        pill = f.text_content("#your-run")
        print("run result:", pill)
        shot("17-your-run-result")

        # 8 theme
        page.click("#theme"); page.wait_for_timeout(1000)
        shot("18-light-theme")
        page.click('#nav button[data-go="overview"]'); page.wait_for_timeout(1200)
        page.click("#theme"); page.wait_for_timeout(800)
        video = page.video.path()
        ctx.close()
        browser.close()
    out = Path(a.out_video)
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-r", "25", str(out)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("video:", out, f"{out.stat().st_size / 1e6:.1f} MB")
    print("errors:", errors or "none")


if __name__ == "__main__":
    main()
