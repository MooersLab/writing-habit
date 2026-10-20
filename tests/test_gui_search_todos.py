"""The project search box, and Sync to-dos and Sort by priority on the grasscatcher."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit.project_lists import GRASSCATCHER          # noqa: E402

WEEK = """\
| Time <l>    | M  | Tu |
|-------------+----+----|
| 05:00-06:30 | g1 | gX |
| 07:00-08:00 | eX |    |
|-------------+----+----|
| 1: 0142RETKinaseCovalentInhibitors 2026-10-30 :safe: |  |  |
| X: 0374qflip 2026-11-21 :risky:  |  |  |
| E: email |  |  |

#+NAME: current-semester-projects
| 1: 0142RETKinaseCovalentInhibitors :safe: |
| B: 1006AIrxOpt 2026-12-15 :safe:         |
| X: 0374qflip 2026-11-21 :risky:          |

#+NAME: grasscatcher
| 1: [#B] Measure the cysteine distances in 7JU6 |
| 1: Run GNINA with the covalent option |
| X: [#A] Fix the flip tests |
"""

LOG = """\
#+TITLE: Writing log for 0142
* Daily log
** 2026 October 19

* Project TODOS

** TODO [#A1] Read the key review articles on covlent docking.
** DONE [#B] Measure the cysteine distances in 7JU6
"""


@pytest.fixture()
def world(tmp_path):
    projects = tmp_path / "home"
    folder = projects / "0142RETKinaseCovalentInhibitors"
    folder.mkdir(parents=True)
    (folder / "log0142.org").write_text(LOG, encoding="utf-8")
    table = tmp_path / "Oct19.org"
    table.write_text(WEEK, encoding="utf-8")
    return table, projects, folder / "log0142.org"


@pytest.fixture()
def editor(qtbot, monkeypatch, world):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    table, projects, _log = world
    store = {"projects_root": str(projects), "hour_view": "false"}
    monkeypatch.setattr("writing_habit.gui.settings.get",
                        lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    widget.open(str(table))
    return widget


def _tabs(editor):
    tabs = editor.project_tabs
    return [tabs.tabText(i) for i in range(tabs.count()) if tabs.isTabVisible(i)]


def _visible(view):
    return [r for r in range(view.model().rowCount()) if not view.isRowHidden(r)]


# -- the search box ---------------------------------------------------------------
def test_typing_filters_every_tab(editor):
    editor.search_box.setText("qflip")
    assert _visible(editor.legend_view) == [1]
    current = editor.list_panels["current-semester-projects"]
    assert _visible(current.view) == [2]
    tabs = _tabs(editor)
    assert tabs[0] == "This week (1 of 3)"
    assert "Current semester projects (1 of 3)" in tabs
    assert "Grasscatcher (0 of 3)" in tabs
    assert editor.search_status.text() == "2 match(es)"


def test_a_code_matches_exactly(editor):
    editor.search_box.setText("e")                 # code E, and every "e" in names
    assert 2 in _visible(editor.legend_view)
    editor.search_box.setText("x")                 # code X; no name holds an x
    assert _visible(editor.legend_view) == [1]


def test_matching_projects_are_tinted_in_both_views(editor):
    from writing_habit.gui.qt import Qt
    from writing_habit.gui.table_model import FIND_COLOR
    editor.search_box.setText("qflip")
    assert editor.model.highlight == {"X"} == editor.hour_model.highlight
    brush = editor.hour_model.data(editor.hour_model.index(5, 2), Qt.BackgroundRole)
    assert brush.color().name() == FIND_COLOR
    other = editor.hour_model.data(editor.hour_model.index(5, 1), Qt.BackgroundRole)
    assert other.color().name() != FIND_COLOR


def test_clearing_shows_everything_again(editor):
    editor.search_box.setText("qflip")
    editor.search_box.clear()
    assert _visible(editor.legend_view) == [0, 1, 2]
    assert editor.model.highlight == set()
    assert _tabs(editor)[0] == "This week (3)"
    assert editor.search_status.text() == ""


def test_enter_goes_to_the_next_tab_with_a_match(editor):
    editor.search_box.setText("gnina")
    assert editor.next_match() == list(editor.list_panels).index(GRASSCATCHER) + 1
    panel = editor.list_panels[GRASSCATCHER]
    assert editor.project_tabs.currentWidget() is panel
    assert panel.view.currentIndex().row() == 1


def test_the_filter_survives_an_edit(editor):
    editor.search_box.setText("qflip")
    panel = editor.list_panels["current-semester-projects"]
    panel.view.setCurrentIndex(panel.model.index(2, 1))
    panel.add_project()
    assert "0374qflip" in [e.description.split()[0] for e in panel.model.entries()
                           if e.code == "X"]
    hidden = [r for r in range(panel.model.rowCount()) if panel.view.isRowHidden(r)]
    assert len(hidden) == panel.model.rowCount() - 1


# -- Sort by priority -----------------------------------------------------------------
def test_sort_by_priority(editor):
    panel = editor.list_panels[GRASSCATCHER]
    assert panel.sort_priority()
    assert [e.description for e in panel.model.entries()] == [
        "[#A] Fix the flip tests", "[#B] Measure the cysteine distances in 7JU6",
        "Run GNINA with the covalent option"]
    assert editor.table.dirty


# -- Sync to-dos ----------------------------------------------------------------------
def test_sync_brings_both_sides_up_to_date(editor, monkeypatch, world):
    _table, _projects, log = world
    asked = []
    monkeypatch.setattr(editor, "_confirm",
                        lambda title, text: asked.append(text) or True)
    result = editor.sync_todos()
    assert result == {"grasscatcher": 2, "logs": 1}
    text = asked[0]
    assert "to the grasscatcher: [#A1] Read the key review" in text
    assert "to the log as TODO: Run GNINA" in text
    assert "done in the log, off the grasscatcher: [#B] Measure" in text
    assert "X: 0374qflip: no log file found" in text
    tasks = [(e.code, e.description)
             for e in editor.table.lists.entries(GRASSCATCHER)]
    assert tasks == [("1", "Run GNINA with the covalent option"),
                     ("X", "[#A] Fix the flip tests"),
                     ("1", "[#A1] Read the key review articles on covlent docking.")]
    assert log.read_text().endswith("** TODO Run GNINA with the covalent option\n")
    assert (log.parent / "log0142.org~").read_text() == LOG
    assert editor.table.dirty
    # A second sync finds nothing to do and asks nothing.
    asked.clear()
    assert editor.sync_todos() == {"grasscatcher": 0, "logs": 0}
    assert asked == []


def test_a_declined_sync_changes_nothing(editor, monkeypatch, world):
    _table, _projects, log = world
    monkeypatch.setattr(editor, "_confirm", lambda title, text: False)
    before = editor.table.to_text()
    assert editor.sync_todos() is None
    assert editor.table.to_text() == before
    assert log.read_text() == LOG


def test_an_open_emacs_buffer_is_warned_about(editor, monkeypatch, world):
    _table, _projects, log = world
    (log.parent / ".#log0142.org").write_text("lock")
    asked = []
    monkeypatch.setattr(editor, "_confirm",
                        lambda title, text: asked.append(text) or False)
    editor.sync_todos()
    assert "open in Emacs" in asked[0]


def test_the_grasscatcher_has_the_two_buttons(editor):
    panel = editor.list_panels[GRASSCATCHER]
    assert panel.sync_button.text() == "Sync to-dos"
    assert panel.priority_button.text() == "Sort by priority"
    other = editor.list_panels["current-semester-projects"]
    assert other.sync_button is None
