"""Semester project lists after the weekly table: reading, editing, and sync."""

import os
import sqlite3

import pytest

from writing_habit import db
from writing_habit.name import read_legend
from writing_habit.project_lists import CURRENT, LISTS, Entry, ProjectLists, read_lists

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

WEEK = """\
| Time <l>    | M  | Tu |
|-------------+----+----|
| 05:00-06:30 | gB | gX |
|-------------+----+----|
| B: 1006AIrxOpt 2026-12-15 :safe: |  |  |
| X: 0374qflip 2026-11-21 :risky:  |  |  |

#+NAME: current-semester-projects
| A: 1094RNAstrucDetResearchProgram :safe: |
| B: 1006AIrxOpt 2026-12-15 :safe:         |
| X: 0374qflip 2026-11-21 :risky:          |

#+NAME: next-semester-projects
| - 1452PHFSboXt 2027-03-01 :safe:          |
| Z: 1008ToolsForQCrOfRNA @editing :safe:   |
"""


@pytest.fixture()
def table_file(tmp_path):
    path = tmp_path / "Oct12.org"
    path.write_text(WEEK, encoding="utf-8")
    return path


def test_the_legend_is_the_first_table_only(table_file):
    assert sorted(read_legend(str(table_file))) == ["B", "X"]


def test_lists_are_read_with_their_codes_and_dashes(table_file):
    lists = read_lists(str(table_file))
    assert lists.present() == ["current-semester-projects", "next-semester-projects"]
    assert [e.code for e in lists.entries(CURRENT)] == ["A", "B", "X"]
    nxt = lists.entries("next-semester-projects")
    assert (nxt[0].code, nxt[0].project, nxt[0].deadline, nxt[0].risk) == (
        None, "1452PHFSboXt", "2027-03-01", "safe")
    assert (nxt[1].code, nxt[1].activity) == ("Z", "editing")
    assert lists.entries("next-next-semester-projects") == []


def test_editing_rewrites_only_the_row(table_file):
    lines = WEEK.splitlines()
    tail = lines[lines.index("") :]
    lists = ProjectLists(tail)
    entry = lists.entries(CURRENT)[0]
    entry.description = "1094RNAstrucDetResearchProgram 2027-05-01"
    assert lists.set_entry(CURRENT, 0, entry)
    changed = [a for a, b in zip(tail, lines[lines.index(""):]) if a != b]
    assert changed == ["| A: 1094RNAstrucDetResearchProgram 2027-05-01 :safe: |"]


def test_insert_move_remove_and_create(table_file):
    lines = []
    lists = ProjectLists(lines)
    assert lists.insert("next-next-semester-projects", None, Entry(None, "0001idea")) == 0
    assert lists.insert(CURRENT, None, Entry("Q", "3292ABRF", "safe")) == 0
    assert lists.insert(CURRENT, 0, Entry("R", "0128NoSpherA2qRNA")) == 0
    # The current list is created before the later one, in horizon order.
    assert lines.index("#+NAME: current-semester-projects") < lines.index(
        "#+NAME: next-next-semester-projects")
    assert lists.move(CURRENT, 0, up=False) == 1
    assert [e.code for e in lists.entries(CURRENT)] == ["Q", "R"]
    assert lists.remove(CURRENT, 0).code == "Q"
    assert [e.text() for e in lists.entries(CURRENT)] == ["R: 0128NoSpherA2qRNA"]


def test_the_scheduler_ignores_the_lists(table_file):
    parse_text = pytest.importorskip("writing_schedule").parse_text
    parsed = parse_text(table_file.read_text(encoding="utf-8"))
    assert [code for code, _d in parsed.legend] == ["B", "X"]
    assert len(parsed.events) == 2


def _mytime(path, rows):
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE zTimeSpent (id INTEGER PRIMARY KEY, DateDashed DATE, Start TIME,'
                ' "End" TIME, ProjectID INT, ProjectDirectory TEXT, Description TEXT, Activity TEXT)')
    con.executemany("INSERT INTO zTimeSpent VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


@pytest.mark.parametrize("scope, kept, left_out", [
    ("semester", {"B", "1094RNAstrucDetResearchProgram"}, 1),
    ("legend", {"B"}, 2),
    ("all", {"B", "1094RNAstrucDetResearchProgram", "6005EveningCommute"}, 0),
])
def test_sync_scope_reads_the_current_semester_list(table_file, tmp_path, scope, kept, left_out):
    from writing_habit.track import mytime_sync
    source = tmp_path / "mytime.db"
    _mytime(str(source), [
        (1, "2026-10-12", "05:00", "06:30", 1006, "1006AIrxOpt", "", "g"),
        (2, "2026-10-12", "07:00", "08:00", 1094, "1094RNAstrucDetResearchProgram", "", "s"),
        (3, "2026-10-12", "17:00", "17:30", 6005, "6005EveningCommute", "", ""),
    ])
    con = db.connect(str(tmp_path / "habit.db"))
    db.init_db(con)
    report = mytime_sync.sync_mytime(con, str(source), since="2026-10-12",
                                     table=str(table_file), scope=scope)
    codes = {r["code"] for r in con.execute(
        "SELECT p.code FROM session JOIN project p USING (project_id)")}
    assert codes == kept
    assert report.skipped_not_in_legend == left_out
    assert report.semester_unplanned == (1 if scope == "semester" else 0)


# -- the editor ---------------------------------------------------------------

@pytest.fixture()
def editor(qapp, monkeypatch, table_file):
    pytest.importorskip("writing_schedule")
    from writing_habit.gui import settings
    from writing_habit.gui.schedule_editor import ScheduleEditor
    store = {}
    monkeypatch.setattr(settings, "get", lambda k: store.get(k, settings.DEFAULTS[k]))
    monkeypatch.setattr(settings, "put", lambda k, v: store.__setitem__(k, v))
    ed = ScheduleEditor()
    ed.open(str(table_file))
    return ed


def test_each_list_has_a_tab_beside_the_legend(editor):
    from writing_habit.gui.schedule_editor import LEGEND_TAB
    tabs = editor.project_tabs
    titles = [tabs.tabText(i) for i in range(tabs.count())]
    assert titles == [f"{LEGEND_TAB} (2)", "Current semester projects (3)",
                      "Carried over", "Completed this semester",
                      "Next semester projects (2)", "Next next semester projects",
                      "3*Next semester projects", "4*Next semester projects",
                      "5*Next semester projects", "6*Next semester projects",
                      "Grasscatcher"]
    assert not tabs.isTabVisible(2)                   # Carried over is empty
    panel = editor.list_panels[CURRENT]
    assert panel.model.columnCount() == editor.legend_model.columnCount()
    assert panel.model.index(1, 1).data() == "1006AIrxOpt"
    assert panel.model.index(1, 2).data() == "2026-12-15"


def test_copying_a_project_into_the_week(editor, table_file):
    panel = editor.list_panels["next-semester-projects"]
    panel.view.setCurrentIndex(panel.model.index(0, 1))
    at = panel.copy_to_legend()                       # no code yet, so a free one
    code, description, risk = editor.table.rows[at].parsed
    assert (description, risk) == ("1452PHFSboXt 2027-03-01", "safe")
    assert code not in ("B", "X")
    assert editor.project_tabs.currentIndex() == 0    # the legend is shown
    assert editor.project_tabs.tabText(0) == "This week (3)"   # the count follows
    current = editor.list_panels[CURRENT]
    current.view.setCurrentIndex(current.model.index(1, 1))
    assert current.copy_to_legend() is None           # B is already in the legend
    assert table_file.read_text(encoding="utf-8") == WEEK   # nothing saved yet


def test_list_edits_reach_the_file_on_save(editor, table_file):
    from writing_habit.gui.qt import Qt
    panel = editor.list_panels["next-next-semester-projects"]
    panel.add_project(Entry(None, "0001futureIdea 2028-01-15", "speculative"))
    panel.view.setCurrentIndex(panel.model.index(0, 0))
    assert panel.model.setData(panel.model.index(0, 0), "k", Qt.EditRole)
    assert not panel.model.setData(panel.model.index(0, 2), "Jan 15", Qt.EditRole)
    assert editor.table.dirty
    editor.table.path = str(table_file)
    table_file.write_text(editor.table.to_text(), encoding="utf-8")
    lists = read_lists(str(table_file))
    assert [e.text() for e in lists.entries("next-next-semester-projects")] == [
        "K: 0001futureIdea 2028-01-15 :risky:"]
    assert lists.entries(CURRENT)[0].code == "A"      # the other lists are untouched


def test_a_new_week_keeps_the_lists(editor):
    from writing_habit.gui.weekly_table import WeeklyTable
    fresh = WeeklyTable("| Time | M |\n|------+---|\n| 05:00-06:00 | A |\n")
    assert fresh.adopt_lists(editor.table)
    assert [e.code for e in fresh.lists.entries(CURRENT)] == ["A", "B", "X"]
    assert not fresh.adopt_lists(editor.table)        # never twice


def test_sort_by_project_number(editor, table_file):
    from writing_habit.project_lists import number_key
    assert number_key("0374qflip") < number_key("1006AIrxOpt") < number_key("email")
    panel = editor.list_panels[CURRENT]
    panel.add_project(Entry("E", "email @support"))
    panel.add_project(Entry("3", "0055early"))
    assert panel.sort()
    assert [e.project for e in editor.table.lists.entries(CURRENT)] == [
        "0055early", "0374qflip", "1006AIrxOpt", "1094RNAstrucDetResearchProgram", "email"]
    assert not panel.sort()                           # already in order
    assert editor.sort_legend()                       # B 1006 then X 0374
    assert list(editor.table.legend()) == ["X", "B"]
    assert editor.project_tabs.tabText(0) == "This week (2)"
    assert parse_entry_ok(editor.table.to_text())


def parse_entry_ok(text):
    parse_text = pytest.importorskip("writing_schedule").parse_text
    return len(parse_text(text).events) == 2


def test_seven_horizons_and_digit_codes_in_lists(table_file):
    from writing_habit.project_lists import NAMES
    assert NAMES[1] == "carried-over-projects"
    assert NAMES[2] == "completed-this-semester"
    assert NAMES[5:] == ["next-next-next-semester-projects",
                         "next-next-next-next-semester-projects",
                         "next-next-next-next-next-semester-projects",
                         "next-next-next-next-next-next-semester-projects",
                         "grasscatcher"]
    lists = ProjectLists([])
    lists.insert(NAMES[5], None, Entry("7", "1452PHFSboXt 2027-03-01", "safe"))
    assert lists.entries(NAMES[5])[0].code == "7"


def test_completed_list_reads_a_row_without_a_closing_bar_and_counts_in_sync(tmp_path):
    from writing_habit.track.mytime_sync import semester_numbers
    path = tmp_path / "week.org"
    path.write_text(WEEK.replace(
        "\n#+NAME: next-semester-projects",
        "\n#+NAME: completed-this-semester\n"
        "| Q: 3292ABRF-SC3-2026 2026-10-09 :safe: |\n"
        "| F: 4072UsersMeeting2026 2026-09-23 :safe:\n"
        "\n#+NAME: next-semester-projects"), encoding="utf-8")
    done = read_lists(str(path)).entries("completed-this-semester")
    assert [(e.code, e.project, e.deadline) for e in done] == [
        ("Q", "3292ABRF-SC3-2026", "2026-10-09"), ("F", "4072UsersMeeting2026", "2026-09-23")]
    assert {"3292", "4072", "1094"} <= semester_numbers(str(path))


def test_mark_completed_moves_the_project_across(editor, table_file):
    from writing_habit.project_lists import COMPLETED
    current = editor.list_panels[CURRENT]
    assert current.complete_button is not None
    assert editor.list_panels["next-semester-projects"].complete_button is None
    current.view.setCurrentIndex(current.model.index(1, 1))     # B 1006AIrxOpt
    entry = current.mark_completed()
    assert entry.project == "1006AIrxOpt"
    assert [e.code for e in editor.table.lists.entries(CURRENT)] == ["A", "X"]
    done = editor.table.lists.entries(COMPLETED)
    assert [(e.code, e.description, e.risk) for e in done] == [
        ("B", "1006AIrxOpt 2026-12-15", "safe")]
    titles = [editor.project_tabs.tabText(i) for i in range(editor.project_tabs.count())]
    assert "Current semester projects (2)" in titles
    assert "Completed this semester (1)" in titles
    assert editor.list_panels[COMPLETED].model.rowCount() == 1
    assert editor.table.dirty
    # The new list sits right after the current one in the file.
    lines = editor.table.lists.lines
    assert lines.index("#+NAME: completed-this-semester") < lines.index(
        "#+NAME: next-semester-projects")
    assert list(editor.table.legend()) == ["B", "X"]   # this week is untouched


def test_marking_a_project_completed_twice_keeps_one_row():
    from writing_habit.project_lists import COMPLETED
    lists = ProjectLists([])
    lists.insert(CURRENT, None, Entry("Q", "3292ABRF 2026-10-09"))
    lists.insert(COMPLETED, None, Entry("Q", "3292ABRF 2026-10-09"))
    lists.transfer(CURRENT, 0, COMPLETED)
    assert lists.entries(CURRENT) == []
    assert len(lists.entries(COMPLETED)) == 1
