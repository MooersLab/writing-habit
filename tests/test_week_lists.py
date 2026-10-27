"""The six week lists: next week through six weeks out."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from writing_habit import columns                                    # noqa: E402
from writing_habit.project_lists import (WEEKS, Entry, ProjectLists,  # noqa: E402
                                         parse_entry)

AFTER = [
    "",
    "#+NAME: next week",
    "| A: 1094RNAstrucDetResearchProgram :safe: |",
    "",
    "#+PROJECT_PERIOD: Fall 2026",
    "",
    "#+NAME: current-semester-projects",
    "| B: 1006AIrxOpt 2026-12-15 :safe: |",
    "",
    "#+NAME: next-semester-projects",
    "| - 1452PHFSboXt 2027-03-01 :safe: |",
]


def test_a_new_week_list_goes_after_the_earlier_weeks_and_before_the_period():
    lists = ProjectLists(list(AFTER))
    lists.insert("three weeks out", None, Entry(None, "0655VirtIssue25"))
    lists.insert("two weeks out", None, Entry(None, "0201dusp1"))
    names = [line for line in lists.lines if line.startswith("#+NAME:")]
    assert names == ["#+NAME: next week", "#+NAME: two weeks out",
                     "#+NAME: three weeks out", "#+NAME: current-semester-projects",
                     "#+NAME: next-semester-projects"]
    period = lists.lines.index("#+PROJECT_PERIOD: Fall 2026")
    assert lists.lines.index("#+NAME: three weeks out") < period


def test_a_first_week_list_goes_above_the_period_line():
    lines = [line for line in AFTER if line not in AFTER[1:4]]
    lists = ProjectLists(lines)
    lists.insert("six weeks out", None, Entry(None, "0655VirtIssue25"))
    assert lists.lines.index("#+NAME: six weeks out") < \
        lists.lines.index("#+PROJECT_PERIOD: Fall 2026")


def test_the_period_line_is_written_below_the_week_lists():
    lines = [line for line in AFTER if not line.startswith("#+PROJECT_PERIOD")]
    lists = ProjectLists(lines)
    lists.set_period("Spring 2027")
    assert lists.lines.index("#+NAME: next week") < \
        lists.lines.index("#+PROJECT_PERIOD: Spring 2027") < \
        lists.lines.index("#+NAME: current-semester-projects")


def test_a_semester_roll_leaves_the_weeks_alone():
    lists = ProjectLists(list(AFTER))
    lists.roll_forward("Spring 2027")
    assert [e.project for e in lists.entries("next week")] == ["1094RNAstrucDetResearchProgram"]
    assert [e.project for e in lists.entries("current-semester-projects")] == ["1452PHFSboXt"]


def test_other_spellings_are_read_as_the_week_lists():
    lists = ProjectLists(["#+NAME: three week out", "| - 0655VirtIssue25 |",
                          "", "#+NAME: 2 weeks out", "| - 0201dusp1 |"])
    notes = lists.tidy_names()
    assert "#+NAME: three weeks out" in lists.lines
    assert "#+NAME: two weeks out" in lists.lines
    assert any("three week out" in n for n in notes)


def test_week_tables_in_columns_are_written_back_in_columns():
    text = [
        "#+NAME: next week",
        "| Code | Project Number | Project Name | Deadline | Risk tag | Default activity |",
        "|------+----------------+--------------+----------+----------+------------------|",
        "| A:   | 1094           | RNAstrucDet  |          | :safe:   |                  |",
        "",
        "#+NAME: my own table",
        "| Code | Project Number | Project Name | Deadline | Risk tag | Default activity |",
        "|------+----------------+--------------+----------+----------+------------------|",
        "| Z:   | 9999           | Untouched    |          |          |                  |",
    ]
    lines, legend, tasks, found = columns.to_one_cell(text)
    assert "| A: 1094RNAstrucDet :safe: |" in lines
    # A table the program does not keep stays exactly as written.
    assert lines[3:] == text[5:]
    out = columns.to_columns(lines, [], {"next week": "Next week"}, tasks)
    assert out[0] == "#+NAME: next week"
    assert out[2].startswith("| Code ")
    assert out[-4:] == text[-4:]


def test_the_attached_file_keeps_its_week_tables(tmp_path):
    pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")
    from writing_habit.gui.weekly_table import WeeklyTable
    source = Path(__file__).parent / "fixtures" / "weeks-in-columns.org"
    table = WeeklyTable.from_file(str(source))
    assert [e.project for e in table.lists.entries("six weeks out")] == ["1094RNAstrucDetResearchProgram"]
    block = table.blocks()[0]
    value = table.cell(block.row, block.column)
    table.set_cell(block.row, block.column, "")
    table.set_cell(block.row, block.column, value)
    table.dirty = True
    table.set_cell(block.row, block.column, "g0")
    text = table.to_text()
    at = text.index("#+NAME: next week")
    assert "| Code | Project Number |" in text[at:at + 200]
    assert text.index("#+NAME: six weeks out") < text.index("#+PROJECT_PERIOD:")


# -- in the window ---------------------------------------------------------------
@pytest.fixture()
def editor(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")
    store = {}
    monkeypatch.setattr("writing_habit.gui.settings.get", lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    path = tmp_path / "Oct26.org"
    path.write_text((Path(__file__).parent / "fixtures" / "weeks-in-columns.org")
                    .read_text(encoding="utf-8"), encoding="utf-8")
    widget.open(str(path))
    return widget


def test_the_weeks_and_the_semesters_have_a_row_each(editor):
    from writing_habit.gui.project_tabs import SEMESTER_ROW, WEEK_ROW
    tabs = editor.project_tabs

    def row_titles(row):
        return [item.widget().text().split(" (")[0] for item in tabs.flows[row]._items]

    assert row_titles(WEEK_ROW) == ["This week", "Next week", "Two weeks out",
                                    "Three weeks out", "Four weeks out", "Five weeks out",
                                    "Six weeks out", "Seven weeks out", "Eight weeks out",
                                    "Grasscatcher"]
    assert row_titles(SEMESTER_ROW)[0].startswith("Current semester projects")
    assert "Grasscatcher" not in row_titles(SEMESTER_ROW)


def test_a_week_button_shows_its_list_and_one_is_checked_at_a_time(editor):
    tabs = editor.project_tabs
    panel = editor.list_panels["two weeks out"]
    index = tabs.indexOf(panel)
    tabs.button(index).click()
    assert tabs.currentWidget() is panel
    assert [i for i in range(tabs.count()) if tabs.button(i).isChecked()] == [index]
    tabs.button(tabs.indexOf(editor.list_panels["next-semester-projects"])).click()
    assert not tabs.button(index).isChecked()


def test_a_project_waiting_next_week_can_be_copied_to_this_week(editor):
    panel = editor.list_panels["next week"]
    editor.show_list("next week")
    panel.view.setCurrentIndex(panel.model.index(0, 1))
    before = len(editor.table.legend())
    at = panel.copy_to_legend()
    assert at is not None
    legend = editor.table.legend()
    assert len(legend) == before + 1
    assert any(desc.startswith("1094RNAstrucDetResearchProgram")
               for desc, _risk in legend.values())
    # The project stays on next week's list until you delete it.
    assert [e.project for e in editor.table.lists.entries("next week")] == \
        ["1094RNAstrucDetResearchProgram"]


def test_each_week_names_its_dates_in_its_tooltip(editor):
    tabs = editor.project_tabs
    tip = tabs.tabToolTip(tabs.indexOf(editor.list_panels["next week"]))
    assert tip.startswith("The week of November 2 to November 8.")


def test_the_seventh_and_eighth_weeks_are_read(editor):
    assert [e.project for e in editor.table.lists.entries("eight weeks out")] == \
        ["1094RNAstrucDetResearchProgram"]
    tip = editor.project_tabs.tabToolTip(
        editor.project_tabs.indexOf(editor.list_panels["eight weeks out"]))
    assert tip.startswith("The week of December 21 to December 27.")


def test_the_rows_never_overlap_and_a_chosen_button_keeps_its_size(editor):
    from writing_habit.gui.project_tabs import SEMESTER_ROW, WEEK_ROW
    editor.resize(700, 900)
    editor.show()
    tabs = editor.project_tabs
    from writing_habit.gui.qt import QtWidgets
    QtWidgets.QApplication.processEvents()
    week, semester = tabs.rows[WEEK_ROW], tabs.rows[SEMESTER_ROW]
    assert week.geometry().bottom() < semester.geometry().top()
    # The narrow window wraps the week row onto more than one line.
    tops = {item.geometry().top() for item in tabs.flows[WEEK_ROW]._items}
    assert len(tops) > 1
    button = tabs.button(0)
    width = button.sizeHint().width()
    tabs.setCurrentIndex(3)
    tabs.setCurrentIndex(0)
    assert button.isChecked() and button.sizeHint().width() == width


def test_the_rows_wrap_to_the_width_the_window_shows(editor, qtbot):
    from writing_habit.gui.qt import QtWidgets
    from writing_habit.gui.project_tabs import BUTTON_SCALE
    # The Schedule tab sits in a scroll area, which keeps it wide enough for
    # its toolbars, so the rows must wrap at the width the window shows.
    area = QtWidgets.QScrollArea()
    qtbot.addWidget(area)
    area.setWidgetResizable(True)
    area.setWidget(editor)
    tabs = editor.project_tabs
    lines = {}
    for width in (1900, 1000):
        area.resize(width, 900)
        area.show()
        for _ in range(3):
            QtWidgets.QApplication.processEvents()
        viewport = area.viewport()
        lines[width] = sum(len({i.geometry().top() for i in f._items}) for f in tabs.flows)
        for flow in tabs.flows:
            for item in flow._items:
                right = item.widget().mapTo(viewport, item.widget().rect().topRight()).x()
                assert right <= viewport.width()
    assert lines[1000] > lines[1900]
    base = QtWidgets.QApplication.font().pointSizeF()
    assert abs(tabs.button(0).font().pointSizeF() - base * BUTTON_SCALE) < 0.01
