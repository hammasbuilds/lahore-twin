"""The local server's input checks and run cache."""

import pytest

import serve


def test_inputs_are_checked_against_their_ranges():
    assert serve.clean("traffic", {"per_hour": "4000", "period": "morning"}) == {"seed": 7, "per_hour": 4000, "period": "morning"}
    with pytest.raises(ValueError, match="per_hour must be between"):
        serve.clean("traffic", {"per_hour": 50000})
    with pytest.raises(ValueError, match="period must be one of"):
        serve.clean("traffic", {"period": "midnight"})
    with pytest.raises(ValueError, match="must be a number"):
        serve.clean("office", {"staff": "lots"})
    with pytest.raises(ValueError, match="unknown module"):
        serve.clean("moon", {})


def test_a_code_change_never_serves_an_old_cached_run(monkeypatch):
    """Runs were cached by their inputs alone, so after the home gained its gate counter and
    visitors, "Run with your values" kept serving days without either."""
    import lahore_twin.export as export
    p = serve.clean("home", {})
    before = serve.run_key("home", p)
    assert serve.run_key("home", p) == before                    # same code, same inputs: cached
    assert serve.run_key("home", {**p, "seed": 8}) != before
    monkeypatch.setattr(export, "source_digest", lambda module: "changed")
    monkeypatch.setattr(serve, "LOADED", {})                     # a restarted server runs the new code
    assert serve.run_key("home", p) != before


def test_a_running_server_never_files_old_code_under_the_new_name(monkeypatch):
    """A server started before an edit kept running the old city code (Python keeps an imported
    module) while keying its runs by the digest on disk: a 2,000-trip run came back with the
    default night's traffic, filed as if the fixed code had made it."""
    import lahore_twin.export as export
    monkeypatch.setattr(serve, "LOADED", {})
    p = serve.clean("city", {})
    key = serve.run_key("city", p)
    assert not serve.stale("city")
    monkeypatch.setattr(export, "source_digest", lambda module: "edited on disk")
    assert serve.run_key("city", p) == key                        # still the code it runs
    assert serve.stale("city")                                    # and the server refuses to run it


def test_any_signalised_junction_can_be_planned():
    names = serve.INPUTS["junctions"]["junction"][2]
    assert names[0] == "worst" and len(names) > 50
    assert serve.clean("junctions", {"junction": "Ghalib Road / MM Alam Road"})["junction"] == "Ghalib Road / MM Alam Road"
    with pytest.raises(ValueError, match="one of the .* listed in the form"):
        serve.clean("junctions", {"junction": "Mall Road / Nowhere"})
