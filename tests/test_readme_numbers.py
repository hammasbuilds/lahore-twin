"""The README's module table and Results are rendered from the replays (tools/results.py): a replay
regenerated without its README, or a number edited by hand, fails here."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import results  # noqa: E402


def test_readme_numbers_match_the_replays():
    have = results.README.read_text(encoding="utf-8")
    assert have == results.wanted(have), "run python tools/results.py write"


def test_a_number_changed_by_hand_is_caught():
    have = results.README.read_text(encoding="utf-8")
    a, b = results.MARKS["results"]
    body = have[have.index(a):have.index(b)]
    first = next(tok for tok in body.split() if tok.replace(".", "").replace(",", "").isdigit() and len(tok) >= 3)
    tampered = have.replace(first, first[:-1] + ("1" if first[-1] != "1" else "2"), 1)
    assert tampered != results.wanted(tampered)


def test_every_figure_in_the_about_panels_is_in_the_checked_readme():
    """The About panels are typed prose; each figure in a traffic, junction or city analysis must
    appear in the README section the replays check, so the panels cannot keep an old number."""
    import re
    about = (ROOT / "viewer" / "about.js").read_text(encoding="utf-8")
    readme = results.README.read_text(encoding="utf-8")
    a, b = results.MARKS["results"]
    a2, b2 = results.MARKS["modules"]
    checked = readme[readme.index(a):readme.index(b)] + readme[readme.index(a2):readme.index(b2)]
    missing = []
    for key in ("traffic", "junctions", "city"):
        block = about[about.index(f"  {key}: {{"):]
        analysis = re.search(r'analysis: "([^"]*)"', block).group(1)
        for fig in re.findall(r"\d[\d,]*\.\d+|\d{1,3}(?:,\d{3})+|\d+:\d\d", analysis):
            if fig not in checked:
                missing.append(f"{key}: {fig}")
    assert not missing, missing
