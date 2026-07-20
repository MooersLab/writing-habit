"""Tests for the schedule-code decoder and the legend check."""

from pathlib import Path

import pytest

from writing_habit import name

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "examples" / "my-week.org"


def test_decode_full_example():
    week = dict(name.decode("4gAAeAsA-gWW"))
    assert week["Mon"] == [
        ("generative", "A"), ("generative", "A"), ("editing", "A"), ("support", "A")
    ]
    assert week["Mon"] == week["Thu"]          # 4 identical days
    assert week["Fri"] == [("generative", "W"), ("generative", "W")]


def test_decode_reduced_and_open():
    week = dict(name.decode("2gAAeA-o-2gW"))
    assert week["Wed"] == []                   # open day
    assert week["Thu"] == [("generative", "W")]


def test_summary_counts():
    total, act, proj = name.summary(name.decode("4gAAeAsA-gWW"))
    assert total == 18
    assert act["generative"] == 10 and act["editing"] == 4 and act["support"] == 4
    assert proj["A"] == 16 and proj["W"] == 2


def test_bad_codes():
    with pytest.raises(ValueError):
        name.decode("gAA-A")        # block before an activity in group two
    with pytest.raises(ValueError):
        name.decode("g1A")         # digit inside a day-pattern is illegal


def test_legend_check_exact_and_alias():
    legend = name.read_legend(str(TABLE))
    assert legend["A"][1] == "safe" and legend["W"][1] == "speculative"
    rows, problems = name.check_against_legend(name.decode("4gAAeAsA-gWW"), legend)
    status = {r[0]: r[4] for r in rows}
    assert status["A"] == "exact" and status["W"] == "exact"
    assert problems == []
    # EM is a two-letter legend code; the single-letter alias E resolves to it.
    rows2, problems2 = name.check_against_legend(name.decode("gAsE"), legend)
    status2 = {r[0]: (r[1], r[4]) for r in rows2}
    assert status2["E"] == ("EM", "alias")
    assert problems2 == []


def test_legend_check_unknown():
    legend = name.read_legend(str(TABLE))
    rows, problems = name.check_against_legend(name.decode("gZ"), legend)
    assert problems == ["Z"]
