"""Weekly tables whose legend and lists are kept as tables in columns."""

import pytest

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_schedule import parse_text                                   # noqa: E402

from writing_habit import columns                                         # noqa: E402
from writing_habit.gui.weekly_table import WeeklyTable                    # noqa: E402
from writing_habit.project_lists import (COMPLETED, CURRENT, GRASSCATCHER,  # noqa: E402
                                         HORIZONS, Entry, read_lists)

GRID = """\
#+TITLE: Writing schedule
|        Time <l> | M  | Tu |
|-----------------+----+----|
|     04:00-06:00 | gB | gB |
|     06:15-08:15 | e0 |    |
|-----------------+----+----|
"""

TABLES = """
#+NAME: This week
| Code | Project Number | Project Name    | Deadline   | Risk tag | Default activity |
|------+----------------+-----------------+------------+----------+------------------|
| 0:   | 8721           | NoahlanaMonzon  | 2026-10-19 | :safe:   |                  |
| B:   | 1006           | AIrxOpt         | 2026-12-15 | :safe:   | editing          |

#+NAME: current-semester-projects
#+CAPTION: Fall 2026 projects
| Code | Project Number | Project Name | Deadline   | Risk tag | Default activity |
|------+----------------+--------------+------------+----------+------------------|
| A:   | 1094           | RNAstrucDet  |            | :safe:   |                  |
| -    | 1452           | PHFSboXt     | 2027-03-01 | :risky:  |                  |
| Y:   | 2026           | words        |            | :risky:  |                  |

#+NAME: completed-this-semester
#+CAPTION: Completed in Fall 2026
| Code | Project Number | Project Name  | Deadline   | Risk tag | Default activity |
|------+----------------+---------------+------------+----------+------------------|
| A:   | 3292           | ABRF-SC3-2026 | 2026-10-09 | :safe:   |                  |

#+NAME: grasscatcher
#+CAPTION: Grasscatcher
| Code | Project Number | Project Name   | Priority | Task                    |
|------+----------------+----------------+----------+-------------------------|
| 0:   | 8721           | NoahlanaMonzon | [#A1]    | Read the key reviews.   |
| -    |                |                |          | Tidy the bib file       |
"""

FILE = GRID + TABLES


@pytest.fixture()
def table():
    return WeeklyTable(FILE)


# -- one row at a time ---------------------------------------------------------------
@pytest.mark.parametrize("row,cell", [
    (["0:", "8721", "NoahlanaMonzon", "2026-10-19", ":safe:", ""],
     "0: 8721NoahlanaMonzon 2026-10-19 :safe:"),
    (["-", "1452", "PHFSboXt", "2027-03-01", "risky", ""], "- 1452PHFSboXt 2027-03-01 :risky:"),
    (["B", "1006", "AIrxOpt", "", ":safe:", "@editing"], "B: 1006AIrxOpt @editing :safe:"),
    (["E:", "", "email", "", "", "support"], "E: email @support"),
    (["", "", "", "", "", ""], None),
])
def test_a_project_row_reads_as_one_cell(row, cell):
    assert columns.project_cell(row) == cell


@pytest.mark.parametrize("cell", ["0: 8721NoahlanaMonzon 2026-10-19 :safe:",
                                  "- 1452PHFSboXt 2027-03-01 :risky:",
                                  "B: 1006AIrxOpt @editing :safe:",
                                  "Y: 2026words :risky:", "E: email"])
def test_a_project_row_round_trips(cell):
    assert columns.project_cell(columns.project_columns(cell)) == cell


def test_a_task_row_reads_and_writes():
    assert columns.task_cell(["1:", "0142", "RET", "[#A1]", "Read it."]) == "1: [#A1] Read it."
    assert columns.task_cell(["-", "", "", "B2", "tidy"]) == "- [#B2] tidy"
    assert columns.task_columns("1: [#A1] Read it.", {"1": ("0142", "RET")}) == [
        "1:", "0142", "RET", "[#A1]", "Read it."]


# -- the whole file ----------------------------------------------------------------------
def test_the_file_reads_into_the_model(table):
    assert table.columnar
    assert table.legend() == {"0": ("8721NoahlanaMonzon 2026-10-19", "safe"),
                              "B": ("1006AIrxOpt 2026-12-15", "safe")}
    assert table.legend_defaults() == {"B": "editing"}
    assert [e.project for e in table.lists.entries(CURRENT)] == [
        "1094RNAstrucDet", "1452PHFSboXt", "2026words"]
    assert table.lists.entries(CURRENT)[1].code is None
    assert [e.description for e in table.lists.entries(GRASSCATCHER)] == [
        "[#A1] Read the key reviews.", "Tidy the bib file"]
    assert table.layout_notes == [] and not table.dirty


def test_an_untouched_file_saves_byte_for_byte(table):
    assert table.to_text() == FILE


def test_the_grid_and_the_legend_reach_the_scheduler():
    parsed = parse_text(FILE)
    assert dict(parsed.legend) == {"0": "8721NoahlanaMonzon 2026-10-19 :safe:",
                                   "B": "1006AIrxOpt 2026-12-15 :safe:"}
    assert len(parsed.events) == 3
    assert {e.section for e in parsed.events if e.letter == "B"} == {"Generative"}


def test_an_edit_writes_columns_again(table):
    table.set_cell(table.block_rows[1], table.column_for(1), "gB")
    text = table.to_text()
    assert text.startswith(GRID.replace("| e0 |    |", "| e0 | gB |"))
    assert "| B:   | 1006           | AIrxOpt        | 2026-12-15 | :safe:   | editing          |" in text
    assert "#+NAME: grasscatcher\n#+CAPTION: Grasscatcher\n| Code | Project Number" in text
    reread = WeeklyTable(text)
    assert reread.legend() == table.legend()
    assert [e.text() for e in reread.lists.entries(CURRENT)] == [
        e.text() for e in table.lists.entries(CURRENT)]


def test_a_new_project_and_task_land_in_columns(table):
    table.lists.insert(HORIZONS[1], None, Entry("Z", "1008ToolsForQCrOfRNA 2027-07-05", "safe"))
    table.lists.insert(GRASSCATCHER, None, Entry("B", "[#C] Draft the abstract"))
    table.add_legend("X", "0374qflip 2026-11-21", "speculative")
    table.dirty = True
    text = table.to_text()
    assert "#+NAME: next-semester-projects" in text
    assert "| Z:   | 1008           | ToolsForQCrOfRNA | 2027-07-05 | :safe:   |" in text
    assert "| B:   | 1006           | AIrxOpt        | [#C]     | Draft the abstract" in text
    assert "| X:   | 0374           | qflip" in text.split("#+NAME: current")[0]
    assert "X:" not in text.split("#+NAME: This week")[0]


def test_titles_become_the_captions(table):
    table.list_titles = {CURRENT: "Spring 2027 projects"}
    table.set_cell(table.block_rows[0], table.column_for(0), "gA")
    assert "#+CAPTION: Spring 2027 projects" in table.to_text()


def test_a_saved_file_round_trips(tmp_path, table):
    table.set_cell(table.block_rows[0], table.column_for(0), "eB")
    path = table.save(str(tmp_path / "week.org"))
    again = WeeklyTable.from_file(path)
    assert again.to_text() == open(path).read()
    assert again.legend() == table.legend()


def test_the_command_line_readers_see_columns(tmp_path):
    from writing_habit.name import read_legend
    from writing_habit.track.mytime_sync import semester_numbers
    path = tmp_path / "week.org"
    path.write_text(FILE, encoding="utf-8")
    assert list(read_legend(str(path))) == ["0", "B"]
    lists = read_lists(str(path))
    assert [e.project for e in lists.entries(COMPLETED)] == ["3292ABRF-SC3-2026"]
    assert {"1094", "1452", "3292"} <= semester_numbers(str(path))


def test_plan_import_reads_the_column_legend(tmp_path):
    from writing_habit import db, plan_import
    path = tmp_path / "week.org"
    path.write_text(FILE, encoding="utf-8")
    con = db.connect(str(tmp_path / "habit.db"))
    db.init_db(con)
    plan_import.import_org(con, str(path), "2026-10-19")
    rows = dict(con.execute("SELECT code, description FROM project"))
    assert rows["0"].startswith("8721NoahlanaMonzon")
    assert rows["B"].startswith("1006AIrxOpt")
