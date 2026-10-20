"""Reading weekly tables written in other layouts.

Three layouts reach the editor besides the standard one:

- the legend kept in its own table named ``This week`` after the time blocks;
- the semester lists named by their tab titles, such as ``Fall 2026
  projects``, sometimes with a list named twice;
- the older layout that kept the semester lists inside the legend, one block
  after another with a rule between them.
"""

import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_schedule import parse_text                                  # noqa: E402

from writing_habit.gui.weekly_table import WeeklyTable                   # noqa: E402
from writing_habit.project_lists import (CURRENT, HORIZONS, ProjectLists,  # noqa: E402
                                         normalize_title)

from test_periods import CALENDAR                                         # noqa: E402

GRID = """\
#+TITLE: Writing schedule
|        Time <l> | M  | Tu |
|-----------------+----+----|
|     04:00-06:00 | gB | gB |
|     06:15-08:15 | e0 |    |
|-----------------+----+----|
"""

TITLED = GRID + """
#+NAME:This week
|-----------------+----+----|
|  0:  8721NoahlanaMonzon 2026-10-19 :safe: |    |    |
|  B: 1006AIrxOpt 2026-12-15 :safe: |    |    |
|-----------------+----+----|

#+NAME: Fall 2026 projects
|-----------------+----+----|
|  A: 1094RNAstrucDetResearchProgram :safe: |    |    |
|  B: 1006AIrxOpt 2026-12-15 :safe: |    |    |

#+NAME: Spring 2027 projects
|-----------------+----+----|
|  A: 1094RNAstrucDetResearchProgram :safe: |    |    |

#+NAME:  Spring 2027 projects
|-----------------+----+----|
|  A: 1094RNAstrucDetResearchProgram :safe: |    |    |
|  -  1452PHFSboXt 2027-03-01  :safe: |    |    |
|-----------------+----+----|

#+NAME:  Summer 2027 projects
|  Z: 1008ToolsForQCrOfRNA 2027-07-05 :safe: |    |    |

#+NAME: grasscatcher
| 1: [#A1] Read the key review articles on covalent docking. |
"""

OLD = """\
|        Time <l> | M  | Tu |
|-----------------+----+----|
|     04:00-06:00 | gB | gH |
|-----------------+----+----|
| B: 1006AIrxOpt 2026-12-15 :safe: |  |  |
| H: 0104BaGquadShelxD 2026-11-15 :safe: |  |  |
|-----------------+----+----|
| A: 1094RNAstrucDetResearchProgram :safe: |  |  |
| B: 1006AIrxOpt 2026-12-15 :safe: |  |  |
| H: 0104BaGquadShelxD 2026-11-15 :safe: |  |  |
|-----------------+----+----|
| A: 1094RNAstrucDetResearchProgram :safe: |  |  |
| - 1452PHFSboXt 2027-03-01 :safe: |  |  |
"""


# -- names ----------------------------------------------------------------------
@pytest.mark.parametrize("text", ["Fall 2026 projects", "  fall  2026 Projects ",
                                  "Fall 2026 projects (26)", "Fall 2026 projects (3 of 26)",
                                  "Fall 2026 projects:"])
def test_titles_compare_without_case_space_or_count(text):
    assert normalize_title(text) == "fall 2026 projects"


def test_a_name_with_spaces_is_found():
    lists = ProjectLists(["#+NAME: grasscatcher", "| - one |",
                          "", "#+NAME:  current-semester-projects", "| A: two |"])
    assert [e.project for e in lists.entries(CURRENT)] == ["two"]


# -- the This week table ----------------------------------------------------------
def test_a_this_week_table_becomes_the_legend():
    table = WeeklyTable(TITLED)
    assert list(table.legend()) == ["0", "B"]
    assert table.dirty
    assert "This week" in table.layout_notes[0]
    text = table.to_text()
    assert "#+NAME:This week" not in text
    parsed = parse_text(text)
    assert dict(parsed.legend)["0"].startswith("8721NoahlanaMonzon")
    assert len(parsed.events) == 3


def test_a_code_the_legend_has_keeps_its_first_definition():
    text = (GRID + "| B: first definition :safe: |  |  |\n\n"
            "#+NAME: This week\n| B: second :safe: |  |  |\n")
    table = WeeklyTable(text)
    assert table.legend()["B"][0] == "first definition"
    assert "already had" in table.layout_notes[0]


def test_a_standard_file_is_read_unchanged():
    standard = GRID + "| B: 1006AIrxOpt :safe: |  |  |\n\n#+NAME: current-semester-projects\n| A: x |\n"
    table = WeeklyTable(standard)
    assert table.layout_notes == []
    assert not table.dirty
    assert table.lists.tidy_names() == []
    assert table.to_text() == standard


# -- titled and doubled lists ------------------------------------------------------
TITLES = {"fall 2026 projects": HORIZONS[0], "spring 2027 projects": HORIZONS[1],
          "summer 2027 projects": HORIZONS[2]}


def test_tab_titles_become_list_names_and_doubles_merge():
    table = WeeklyTable(TITLED)
    notes = table.lists.tidy_names(TITLES)
    assert any("“Fall 2026 projects” as current-semester-projects" in n for n in notes)
    assert any("Merged a second next-semester-projects" in n for n in notes)
    lists = table.lists
    assert [e.project for e in lists.entries(HORIZONS[0])] == [
        "1094RNAstrucDetResearchProgram", "1006AIrxOpt"]
    assert [e.project for e in lists.entries(HORIZONS[1])] == [
        "1094RNAstrucDetResearchProgram", "1452PHFSboXt"]
    assert [e.project for e in lists.entries(HORIZONS[2])] == ["1008ToolsForQCrOfRNA"]
    text = table.to_text()
    assert text.count("#+NAME: next-semester-projects") == 1
    assert "Spring 2027" not in text
    assert lists.tidy_names(TITLES) == []                # a second pass finds nothing


def test_plain_titles_need_no_calendar():
    lists = ProjectLists(["#+NAME: 3*Next semester projects", "| A: x |",
                          "#+NAME: Grasscatcher", "| - task |"])
    lists.tidy_names()
    assert lists.lines[0] == "#+NAME: next-next-next-semester-projects"
    assert lists.lines[2] == "#+NAME: grasscatcher"


def test_an_unknown_table_name_is_left_alone():
    lists = ProjectLists(["#+NAME: my-other-table", "| a | b |"])
    assert lists.tidy_names() == []
    assert lists.lines[0] == "#+NAME: my-other-table"


# -- the older layout ----------------------------------------------------------------
def test_legend_blocks_are_found():
    table = WeeklyTable(OLD)
    assert [len(b) for b in table.legend_blocks()] == [2, 3, 2]


def test_extra_blocks_move_to_the_lists():
    table = WeeklyTable(OLD)
    moved = table.split_legend_blocks()
    assert moved == [(HORIZONS[0], 3), (HORIZONS[1], 2)]
    assert list(table.legend()) == ["B", "H"]
    assert [e.project for e in table.lists.entries(HORIZONS[1])] == [
        "1094RNAstrucDetResearchProgram", "1452PHFSboXt"]
    text = table.to_text()
    parsed = parse_text(text)
    assert [code for code, _d in parsed.legend] == ["B", "H"]
    assert "- 1452PHFSboXt" not in text.split("#+NAME")[0]


def test_one_block_has_nothing_to_move():
    assert WeeklyTable(GRID + "| B: x |  |  |\n").split_legend_blocks() == []


# -- New from template keeps the period line -----------------------------------------
def test_adopted_lists_keep_their_period():
    old = WeeklyTable(GRID + "| B: x |  |  |\n\n#+PROJECT_PERIOD: Fall 2026\n\n"
                      "#+NAME: current-semester-projects\n| A: y |\n")
    new = WeeklyTable(GRID + "| B: x |  |  |\n")
    assert new.adopt_lists(old)
    assert new.lists.period() == "Fall 2026"
    assert [e.project for e in new.lists.entries(CURRENT)] == ["y"]


# -- the editor -------------------------------------------------------------------------
@pytest.fixture()
def editor_for(qtbot, monkeypatch, tmp_path):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    (tmp_path / "periods.org").write_text(CALENDAR, encoding="utf-8")
    store = {"hour_view": "false"}
    monkeypatch.setattr("writing_habit.gui.settings.get", lambda k: store.get(k, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda k, v: store.__setitem__(k, v))

    def make(text, name="Oct19.org"):
        from writing_habit.gui.schedule_editor import ScheduleEditor
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        widget = ScheduleEditor()
        qtbot.addWidget(widget)
        widget.today = lambda: dt.date(2026, 10, 20)
        widget.open(str(path))
        return widget, path
    return make


def _tabs(editor):
    tabs = editor.project_tabs
    return [tabs.tabText(i) for i in range(tabs.count()) if tabs.isTabVisible(i)]


def test_the_editor_reads_the_titled_file(editor_for):
    editor, path = editor_for(TITLED)
    assert _tabs(editor)[:2] == ["This week (2)", "Fall 2026 projects (2)"]
    assert "Spring 2027 projects (2)" in _tabs(editor)
    assert "Summer 2027 projects (1)" in _tabs(editor)
    assert editor.layout_banner.isVisibleTo(editor)
    assert "Save to keep" in editor.layout_banner.text()
    assert editor.table.dirty
    assert path.read_text() == TITLED                    # nothing written yet
    saved = editor.save()
    again, _path = editor_for(open(saved).read(), name="again.org")
    assert not again.layout_banner.isVisibleTo(again)
    assert not again.table.dirty


def test_the_editor_points_at_old_legend_blocks(editor_for, monkeypatch):
    editor, _path = editor_for(OLD)
    assert "3 blocks" in editor.layout_banner.text()
    assert not editor.table.dirty                        # only a suggestion
    monkeypatch.setattr(editor, "_confirm", lambda title, text: True)
    assert editor.split_legend_blocks() == [(HORIZONS[0], 3), (HORIZONS[1], 2)]
    assert _tabs(editor)[0] == "This week (2)"
    assert "Fall 2026 projects (3)" in _tabs(editor)
    assert editor.table.dirty


def test_the_command_line_reads_a_this_week_table(tmp_path):
    from writing_habit.name import read_legend
    path = tmp_path / "week.org"
    path.write_text(TITLED, encoding="utf-8")
    assert list(read_legend(str(path))) == ["0", "B"]
