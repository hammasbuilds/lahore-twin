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
    assert serve.run_key("home", p) != before
