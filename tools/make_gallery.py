"""Write docs/gallery.html: every screenshot in docs/screenshots/, captioned with the alt text the
README gives it, so the gallery and the README never describe a picture differently.

    python tools/make_gallery.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
OUT = ROOT / "docs" / "gallery.html"


def main() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    alt = {Path(p).name: a for a, p in re.findall(r"!\[([^\]]*)\]\((docs/screenshots/[^)]+)\)", readme)}
    pngs = sorted(SHOTS.glob("*.png"))
    missing = [p.name for p in pngs if p.name not in alt]
    if missing:                       # a picture the README never mentions has no caption to give
        raise SystemExit(f"not in README.md, so no caption: {missing}")
    figs = "\n".join(
        f'<figure><a href="screenshots/{p.name}"><img src="screenshots/{p.name}" alt="{html.escape(alt[p.name])}" loading="lazy"></a>'
        f"<figcaption>{html.escape(alt[p.name])}</figcaption></figure>" for p in pngs)
    OUT.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lahore Twin screenshots</title>
<style>
:root {{ --bg: #0b1220; --panel: #121a2b; --text: #e5e9f0; --muted: #94a3b8; }}
@media (prefers-color-scheme: light) {{ :root {{ --bg: #f4f6fa; --panel: #ffffff; --text: #111827; --muted: #4b5563; }} }}
body {{ margin: 0; padding: 24px 16px; background: var(--bg); color: var(--text); font: 15px/1.5 Segoe UI, system-ui, sans-serif; }}
h1 {{ font-size: 22px; margin: 0 0 4px; }} p {{ color: var(--muted); margin: 0 0 20px; }}
main {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 420px), 1fr)); gap: 18px; }}
figure {{ margin: 0; background: var(--panel); border-radius: 10px; overflow: hidden; }}
img {{ display: block; width: 100%; height: auto; }}
figcaption {{ padding: 10px 12px; font-size: 13.5px; color: var(--muted); }}
</style></head><body>
<h1>Lahore Twin</h1>
<p>{len(pngs)} screenshots of the running app, each taken with its result on screen (tools/demo_video.py). Click one for full size.</p>
<main>
{figs}
</main></body></html>
""", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(pngs)} screenshots)")


if __name__ == "__main__":
    main()
