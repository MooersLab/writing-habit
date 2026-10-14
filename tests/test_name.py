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
        name.decode("g1x")         # a lowercase letter that is no activity


def test_legend_check_exact_and_alias():
    legend = name.read_legend(str(TABLE))
    assert legend["A"][1] == "safe" and legend["W"][1] == "speculative"
    rows, problems = name.check_against_legend(name.decode("4gAAeAsA-gWW"), legend)
    status = {r[0]: r[4] for r in rows}
    assert status["A"] == "exact" and status["W"] == "exact"
    assert problems == []
    # A single letter resolves to a longer legend code that starts with it.
    # The example table now uses single letters throughout, so the alias case
    # is shown with a legend of its own.
    aliased = {"A": ("DNPH1 docking", "safe"), "EM": ("email", None)}
    rows2, problems2 = name.check_against_legend(name.decode("gAsE"), aliased)
    status2 = {r[0]: (r[1], r[4]) for r in rows2}
    assert status2["E"] == ("EM", "alias")
    assert problems2 == []


def test_legend_check_unknown():
    legend = name.read_legend(str(TABLE))
    rows, problems = name.check_against_legend(name.decode("gZ"), legend)
    assert problems == ["Z"]


def test_digit_project_codes_round_trip():
    decoded = name.decode("4g12e3-o-gA0")
    assert decoded[0][1] == [("generative", "1"), ("generative", "2"), ("editing", "3")]
    assert decoded[5][1] == [("generative", "A"), ("generative", "0")]
    assert name.decode(name.encode(decoded)) == decoded
    assert name.parse_legend_cell("3: 0374qflip :risky:") == ("3", "0374qflip", "speculative")
    assert name.parse_legend_cell("5:00-06:30") is None     # a time, not code 5
