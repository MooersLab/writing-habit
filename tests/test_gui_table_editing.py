"""Editing the weekly table: one edit, one changed line, and a saved file.

The document tests here need no Qt. The widget tests do, and they are skipped
when the graphical extra is absent. The property that matters throughout is the
one the writer relies on: a save differs from the file on disk only where they
changed something.
"""

import os
from pathlib import Path

import pytest

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_schedule import parse_text                        # noqa: E402

from writing_habit.gui.weekly_table import WeeklyTable         # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "my-week.org"


@pytest.fixture()
def table():
    return WeeklyTable.from_file(str(EXAMPLE))


def _changed_lines(before: str, after: str):
    return [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]


def test_writing_a_cell_its_own_value_changes_nothing(table):
    before = table.to_text()
    assert table.set_cell(table.block_rows[0], 1, "A") is False
    assert table.to_text() == before
    assert table.dirty is False


def test_one_cell_edit_rewrites_one_line(table):
    before = table.to_text()
    row = table.block_rows[0]
    assert table.set_cell(row, 6, "B") is True          # the Saturday cell
    after = table.to_text()
    changed = _changed_lines(before, after)
    assert len(changed) == 1
    assert changed[0][1].rstrip().endswith("| B  |")
    assert table.dirty is True


def test_an_edit_keeps_the_column_width_when_it_fits(table):
    row = table.block_rows[0]
    before = table.rows[row].raw
    table.set_cell(row, 1, "B")
    assert len(table.rows[row].raw) == len(before)


def test_a_longer_value_widens_only_its_own_slot(table):
    row = table.block_rows[0]
    before = table.rows[row].raw
    table.set_cell(row, 1, "ABCD")
    after = table.rows[row].raw
    assert len(after) == len(before) + 3
    assert after.count("|") == before.count("|")


def test_the_parser_sees_the_edited_week(table):
    row = table.block_rows[0]
    table.set_cell(row, 6, "B")
    reparsed = parse_text(table.to_text())
    assert reparsed.events == WeeklyTable(table.to_text()).events()
    saturday = [e for e in reparsed.events if e.offset == 5 and e.start == "04:00"]
    assert [e.letter for e in saturday] == ["B"]


def test_clearing_a_cell_removes_the_block(table):
    row = table.block_rows[0]
    before = len(table.blocks())
    table.set_cell(row, 1, "")
    assert len(table.blocks()) == before - 1


def test_an_edit_moves_the_canonical_name(table):
    first, _problem = table.code_or_problem()
    table.set_cell(table.block_rows[0], 6, "B")
    second, _problem = table.code_or_problem()
    assert first != second


TWO_ROWS = (
    "| Time <l>    | M | Tu |\n"
    "|-------------+---+----|\n"
    "| Generative: |   |    |\n"
    "| 04:00-05:30 | A |    |\n"
    "| Rewriting:  |   |    |\n"
    "| 05:00-06:30 |   |    |\n"
    "|-------------+---+----|\n"
    "| A: one :safe: |  |  |\n"
    "| B: two :risky: |  |  |\n"
)


def test_a_cell_edit_can_create_and_remove_a_clash():
    """The two rows overlap by half an hour, so filling both on one day clashes."""
    table = WeeklyTable(TWO_ROWS)
    assert table.overlaps() == []
    second = table.block_rows[1]
    table.set_cell(second, 1, "B")               # Monday, 05:00-06:30
    assert len(table.overlaps()) == 1
    table.set_cell(second, 2, "B")               # Tuesday is alone, so no clash
    assert len(table.overlaps()) == 1
    table.set_cell(second, 1, "")
    assert table.overlaps() == []


def test_a_legend_edit_rewrites_one_line(table):
    before = table.to_text()
    row = table.legend_rows()[3]
    assert table.set_legend(row, "T", "teaching", "safe") is True
    changed = _changed_lines(before, table.to_text())
    assert len(changed) == 1
    assert ":safe:" in changed[0][1]
    assert table.legend()["T"] == ("teaching", "safe")


def test_a_legend_edit_writes_risky_for_the_speculative_class(table):
    row = table.legend_rows()[3]
    table.set_legend(row, "T", "teaching", "speculative")
    assert ":risky:" in table.rows[row].raw
    assert table.legend()["T"][1] == "speculative"


def test_a_legend_edit_can_drop_the_tag(table):
    row = table.legend_rows()[0]
    table.set_legend(row, "A", "DNPH1 docking", None)
    assert ":safe:" not in table.rows[row].raw
    assert table.legend()["A"] == ("DNPH1 docking", None)


def test_only_a_block_row_takes_a_cell_edit(table):
    section = next(i for i, row in enumerate(table.rows) if row.kind == "section")
    with pytest.raises(ValueError):
        table.set_cell(section, 1, "A")
    with pytest.raises(ValueError):
        table.set_legend(table.block_rows[0], "A", "x", None)


def test_saving_writes_the_document_and_clears_the_dirty_flag(tmp_path, table):
    table.set_cell(table.block_rows[0], 6, "B")
    target = tmp_path / "week.org"
    written = table.save(str(target))
    assert written == str(target)
    assert table.dirty is False
    assert target.read_text(encoding="utf-8") == table.to_text()
    # and the file that comes back is the file that went out
    assert WeeklyTable.from_file(str(target)).to_text() == table.to_text()


def test_saving_an_untouched_table_reproduces_it_byte_for_byte(tmp_path, table):
    target = tmp_path / "copy.org"
    table.save(str(target))
    assert target.read_text(encoding="utf-8") == EXAMPLE.read_text(encoding="utf-8")


# -- the canonical file name ----------------------------------------------
#
# The tracker groups weeks by the schedule code stored at plan import, and that
# code comes from the file name, so a name that has drifted from its grid files
# the week under the wrong shape.

def _copy(tmp_path, name="week.org"):
    target = tmp_path / name
    target.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    return WeeklyTable.from_file(str(target))


def test_a_drifted_name_is_reported_and_corrected(tmp_path):
    table = _copy(tmp_path)
    assert table.name_matches_code() is False
    code, _problem = table.code_or_problem()

    path = Path(table.rename_to_canonical())
    assert path.name == f"{code}.org"
    assert path.exists() and not (tmp_path / "week.org").exists()
    assert table.name_matches_code() is True
    assert path.read_text(encoding="utf-8") == EXAMPLE.read_text(encoding="utf-8")


def test_renaming_a_table_already_named_right_is_a_no_op(tmp_path):
    table = _copy(tmp_path)
    first = table.rename_to_canonical()
    assert table.rename_to_canonical() == first


def test_renaming_waits_for_the_edits_to_be_saved(tmp_path):
    table = _copy(tmp_path)
    table.set_cell(table.block_rows[0], 6, "B")
    with pytest.raises(ValueError, match="save the table"):
        table.rename_to_canonical()
    table.save()
    assert Path(table.rename_to_canonical()).name != "week.org"


def test_renaming_refuses_to_overwrite_another_file(tmp_path):
    table = _copy(tmp_path)
    code, _problem = table.code_or_problem()
    (tmp_path / f"{code}.org").write_text("someone else's week\n", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        table.rename_to_canonical()
    assert Path(table.path).name == "week.org"


def test_a_week_with_no_canonical_name_cannot_be_renamed(tmp_path):
    target = tmp_path / "multi.org"
    target.write_text(
        "| Time <l>    | M  |\n"
        "|-------------+----|\n"
        "| Supporting: |    |\n"
        "| 13:15-14:45 | EM |\n"
        "|-------------+----|\n"
        "| EM: email   |    |\n", encoding="utf-8")
    table = WeeklyTable.from_file(str(target))
    with pytest.raises(ValueError, match="single-letter alias"):
        table.rename_to_canonical()


def test_a_table_that_came_from_no_file_cannot_be_renamed():
    table = WeeklyTable(TWO_ROWS)
    with pytest.raises(ValueError, match="never been saved"):
        table.rename_to_canonical()
