"""The weekly-table document: parity with the parser, and a byte-exact round trip.

These tests need no Qt. Two properties carry the editor. The document must see
the same blocks and the same legend the scheduler sees, because a grid that
disagrees with the tools would show the writer a week the tools never run. An
untouched document must write back byte for byte, because a save that reformats
a file the writer did not change is a loss they cannot undo.
"""

from pathlib import Path

import pytest

pytest.importorskip("writing_schedule",
                    reason="the weekly table is parsed by writing-schedule")

from writing_schedule import parse_text                      # noqa: E402

from writing_habit import name                               # noqa: E402
from writing_habit.gui.weekly_table import WeeklyTable       # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TABLES = sorted(ROOT.glob("templates/*.org")) + sorted(ROOT.glob("examples/*.org"))

#: The two names that predate the canonical run rule, so the grid renames them.
UNCANONICAL = {
    "gAABeAsA-gAABeBsB-gBBAeAsB-gBBAeBsW-gWsA-sAAA",
    "gAABeAsA-gAABeBsB-gBBAeAsB-gBBAeBsW-gWsA",
}


@pytest.mark.parametrize("path", TABLES, ids=lambda p: p.stem[:40])
def test_the_document_sees_what_the_parser_sees(path):
    table = WeeklyTable.from_file(str(path))
    assert table.events() == parse_text(path.read_text(encoding="utf-8")).events


@pytest.mark.parametrize("path", TABLES, ids=lambda p: p.stem[:40])
def test_an_untouched_document_writes_back_byte_for_byte(path):
    table = WeeklyTable.from_file(str(path))
    assert table.to_text() == path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", TABLES, ids=lambda p: p.stem[:40])
def test_the_legend_matches_the_reader_used_by_the_tracker(path):
    table = WeeklyTable.from_file(str(path))
    assert table.legend() == name.read_legend(str(path))


@pytest.mark.parametrize(
    "path", [p for p in TABLES if p.parent.name == "templates"],
    ids=lambda p: p.stem[:40])
def test_the_grid_names_itself_as_the_file_is_named(path):
    """The code derived from the grid is the code in the file name."""
    table = WeeklyTable.from_file(str(path))
    code, problem = table.code_or_problem()
    assert problem is None
    if path.stem in UNCANONICAL:
        assert name.decode(code) == name.decode(path.stem)   # same week, newer spelling
    else:
        assert code == path.stem


MULTI_LETTER = (
    "| Time <l>    | M  |\n"
    "|-------------+----|\n"
    "| Supporting: |    |\n"
    "| 13:15-14:45 | EM |\n"
    "|-------------+----|\n"
    "| EM: email   |    |\n"
)


def test_a_multi_letter_project_has_no_file_name_and_says_why():
    """A file name gives one letter to one block, so EM cannot be named."""
    table = WeeklyTable(MULTI_LETTER)
    code, problem = table.code_or_problem()
    assert code is None
    assert "EM" in problem and "single-letter alias" in problem


def test_totals_by_day_project_and_activity():
    table = WeeklyTable.from_file(str(ROOT / "examples" / "my-week.org"))
    totals = table.totals()
    assert totals["day"]["M"] == 360 and totals["day"]["Sa"] == 180
    assert totals["project"]["A"] == 720
    assert totals["category"] == {"generative": 990, "editing": 540, "support": 450}
    assert sum(totals["day"].values()) == sum(totals["category"].values())


def test_the_example_week_can_now_be_named():
    """my-week.org uses single-letter codes, so it has a canonical file name."""
    table = WeeklyTable.from_file(str(ROOT / "examples" / "my-week.org"))
    code, problem = table.code_or_problem()
    assert problem is None
    assert name.decode(code)                       # it parses back to a week


def test_the_legend_check_resolves_every_letter_of_the_example():
    table = WeeklyTable.from_file(str(ROOT / "examples" / "my-week.org"))
    rows, problems = table.legend_check()
    assert problems == []
    assert {row[0] for row in rows} == {"A", "B", "W", "T", "E"}


CLASH = (
    "| Time <l>    | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| Generative: |    |    |\n"
    "| 04:00-05:30 | A  |    |\n"
    "| Rewriting:  |    |    |\n"
    "| 05:00-06:30 | B  | A  |\n"
    "|-------------+----+----|\n"
    "| A: one :safe: |  |  |\n"
    "| B: two        |  |  |\n"
)


def test_a_clash_is_found_and_located_in_the_grid():
    table = WeeklyTable(CLASH)
    conflicts = table.overlaps()
    assert len(conflicts) == 1
    cells = table.conflicting_cells()
    assert len(cells) == 2
    rows = {row for row, _column in cells}
    assert len(rows) == 2                      # the two clashing block rows
    assert all(column == 1 for _row, column in cells)   # both on Monday


def test_touching_blocks_do_not_clash():
    table = WeeklyTable(CLASH.replace("05:00-06:30", "05:30-07:00"))
    assert table.overlaps() == []
    assert table.conflicting_cells() == set()


def test_a_section_with_no_category_is_reported():
    table = WeeklyTable(CLASH.replace("Rewriting:", "Pondering:"))
    assert table.unknown_sections() == ["Pondering"]
    # the plan importer counts an unknown section as generative, and so do we
    assert table.totals()["category"]["generative"] == 90 + 90 + 90


def test_the_document_keeps_the_text_around_the_table():
    text = "#+TITLE: A week\n\n" + CLASH + "\nA closing note.\n"
    table = WeeklyTable(text)
    assert table.to_text() == text
    assert table.day_labels == ["M", "Tu"]


# -- the real week ---------------------------------------------------------
#
# examples/aug24.org is a real weekly table. It offers a long menu of candidate
# time blocks and fills only a few, which is the case the readers must get right
# because an empty cell is not a plan.

REAL = ROOT / "examples" / "aug24.org"


def test_only_the_lettered_cells_count_as_planned_blocks():
    table = WeeklyTable.from_file(str(REAL))
    assert len(table.block_rows) == 126        # the menu of candidate blocks
    assert len(table.blocks()) == 5            # the blocks actually chosen
    totals = table.totals()
    assert totals["day"]["Th"] == 570
    assert sum(totals["day"].values()) == 570  # every other day is empty


def test_a_one_day_week_is_named_with_leading_open_days():
    table = WeeklyTable.from_file(str(REAL))
    code, problem = table.code_or_problem()
    assert problem is None
    assert code == "3o-gHgAeCsIsB"             # Monday to Wednesday open
    assert name.decode(code)[3][1][0] == ("generative", "H")


LEGEND_FAULTS = (
    "| Time <l>    | M |\n"
    "|-------------+---|\n"
    "| Generative: |   |\n"
    "| 04:00-05:30 | H |\n"
    "|-------------+---|\n"
    "| H: first project :safe:  |  |\n"
    "| H: second project :safe: |  |\n"
    "| G: an aim :spec:         |  |\n"
)


def test_a_code_defined_twice_in_the_legend_is_reported():
    """The readers keep the first definition and drop the rest without a word."""
    table = WeeklyTable(LEGEND_FAULTS)
    duplicates = table.duplicate_legend_codes()
    assert list(duplicates) == ["H"]
    assert duplicates["H"] == ["first project", "second project"]
    assert table.legend()["H"][0] == "first project"


def test_an_unrecognized_risk_tag_is_reported_rather_than_read():
    """:spec: is not a tag, so the project keeps no class and the tag stays put."""
    table = WeeklyTable(LEGEND_FAULTS)
    assert table.stray_risk_tags() == [("G", "spec")]
    assert table.legend()["G"][1] is None


def test_risky_names_the_class_the_database_calls_speculative():
    table = WeeklyTable(LEGEND_FAULTS.replace(":spec:", ":risky:"))
    assert table.legend()["G"][1] == "speculative"
    assert table.stray_risk_tags() == []


def test_the_old_speculative_tag_no_longer_names_a_class():
    """:risky: replaced it, so an old table is flagged rather than misread."""
    table = WeeklyTable(LEGEND_FAULTS.replace(":spec:", ":speculative:"))
    assert table.legend()["G"][1] is None
    assert table.stray_risk_tags() == [("G", "speculative")]


def test_the_real_week_carries_no_legend_faults():
    table = WeeklyTable.from_file(str(REAL))
    assert table.duplicate_legend_codes() == {}
    assert table.stray_risk_tags() == []
    assert table.legend()["G"][1] == "speculative"      # tagged :risky:
    assert table.legend()["O"][0] == "2174ComputationalCrystallography"


def test_one_table_gives_one_description_for_a_duplicated_code():
    """The document and the tracker's own reader must agree on which one wins."""
    table = WeeklyTable.from_file(str(REAL))
    assert table.legend() == name.read_legend(str(REAL))
    assert table.legend()["H"][0] == "1006AIrxOpt"     # the first definition
