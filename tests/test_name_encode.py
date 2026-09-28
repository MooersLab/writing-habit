"""Tests for the schedule-code encoder and its canonical spelling.

The encoder is the inverse of the decoder for a canonical code, so most of the
work here is a round-trip property. A run covers consecutive blocks that share
both the activity and the project, and a change of project repeats the activity
letter, so support work on B, then C, then D reads ``sBBBsCCCsD``. Two template
file names still use the older merged spelling for a change of project within a
generative run, so the corpus test asserts the semantic round trip and the exact
spelling is asserted for canonical codes only.
"""

from pathlib import Path

import pytest

from writing_habit import name

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = sorted(p.stem for p in (ROOT / "templates").glob("*.org"))

CANONICAL = [
    "5gA",
    "2gAsBBBsCCCsD-2gAsBBBsCCCsE-gWsBBBsCCC-sDDDsEEE",
    "4gAsBBBsCCC-sBBBsCCC",
    "5gAA",
    "4gAAeAsA-gWW",
    "2gAAeA-o-2gW",
    "gA-o-gA-o-gA",
    "gAeAsA-gAeAsB-gBeBsB-gBeBsW-gWW",
    "o",
]


@pytest.mark.parametrize("code", CANONICAL)
def test_encode_inverts_decode(code):
    assert name.encode(name.decode(code)) == code


@pytest.mark.parametrize("stem", TEMPLATES)
def test_template_names_survive_a_round_trip(stem):
    """Every shipped template name decodes to the week its re-encoding decodes to."""
    week = name.decode(stem)
    assert name.decode(name.encode(week)) == week


def test_encode_accepts_bare_block_lists():
    week = [[("generative", "A")], [], [("generative", "A")]]
    assert name.encode(week) == "gA-o-gA"


def test_encode_accepts_activity_letters():
    assert name.encode([[("g", "A"), ("e", "A")]]) == "gAeA"


def test_count_collapses_only_consecutive_days():
    """Identical days that are not adjacent are written out again."""
    day = [("generative", "A")]
    assert name.encode([day, day, day]) == "3gA"
    assert name.encode([day, [], day]) == "gA-o-gA"


def test_count_of_one_is_omitted():
    assert name.encode([[("generative", "W"), ("generative", "W")]]) == "gWW"


def test_trailing_open_days_are_dropped():
    day = [("generative", "A")]
    assert name.encode([day, [], []]) == "gA"
    assert name.encode([[], []]) == "o"


def test_interior_open_day_is_kept():
    day = [("generative", "A")]
    assert name.encode([day, [], day]) == "gA-o-gA"


def test_a_change_of_project_repeats_the_activity_letter():
    """Support on B, then C, then D reads sBBBsCCCsD, not sBBBCCCD."""
    blocks = (
        [("support", "B")] * 3 + [("support", "C")] * 3 + [("support", "D")]
    )
    assert name.encode([blocks]) == "sBBBsCCCsD"
    assert name.encode([[("support", "B"), ("support", "C")]]) == "sBsC"


def test_a_run_merges_only_repeats_of_one_project():
    assert name.encode([[("generative", "A"), ("generative", "A"),
                         ("generative", "B")]]) == "gAAgB"


def test_encode_day_patterns():
    assert name.encode_day([]) == "o"
    assert name.encode_day([("generative", "A"), ("generative", "A")]) == "gAA"
    assert name.encode_day(
        [("generative", "A"), ("editing", "A"), ("support", "A")]
    ) == "gAeAsA"


def test_encode_rejects_bad_input():
    with pytest.raises(ValueError):
        name.encode([])                                   # no days
    with pytest.raises(ValueError):
        name.encode([[("dreaming", "A")]])                # unknown activity
    with pytest.raises(ValueError):
        name.encode([[("generative", "a")]])              # project must be uppercase
    with pytest.raises(ValueError):
        name.encode([[("generative", "AB")]])             # one letter is one block
    with pytest.raises(ValueError):
        name.encode([[("generative", "A")]] * 8)          # longer than a week
