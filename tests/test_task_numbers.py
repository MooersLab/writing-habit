"""Grasscatcher tasks name their project by number, which outlasts the code."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit.gui.weekly_table import WeeklyTable          # noqa: E402
from writing_habit.project_lists import (GRASSCATCHER, Entry,   # noqa: E402
                                         ProjectLists)


def _week(legend, tasks, lists=""):
    rows = "\n".join(f"| {cell} |  |" for cell in legend)
    return ("|        Time | M  |\n|-------------+----|\n| 05:00-06:00 | gA |\n"
            "|-------------+----|\n" + rows + "\n" + lists +
            "\n#+NAME: grasscatcher\n" + "\n".join(f"| {t} |" for t in tasks) + "\n")


LAST_WEEK = ["A: 0142RETKinase", "B: 1006AIrxOpt", "E: email"]
THIS_WEEK = ["A: 1006AIrxOpt", "1: 0142RETKinase", "E: email"]   # codes moved


def test_a_written_number_wins_over_a_stale_code():
    table = WeeklyTable(_week(THIS_WEEK, ["A: 0142 [#A1] Read the reviews",
                                          "B: 1006 tidy the figures"]))
    tasks = table.lists.entries(GRASSCATCHER)
    assert [(t.code, t.number, t.description) for t in tasks] == [
        ("1", "0142", "[#A1] Read the reviews"), ("A", "1006", "tidy the figures")]


def test_align_rewrites_stale_codes_and_says_so():
    table = WeeklyTable(_week(THIS_WEEK, ["A: 0142 [#A1] Read the reviews",
                                          "E: answer the dean"]))
    notes = table.lists.align_tasks()
    assert notes == ["Gave the grasscatcher task “[#A1] Read the reviews” the code 1 "
                     "of project 0142 (it was A)"]
    assert "| 1: 0142 [#A1] Read the reviews |" in table.to_text()
    assert "| E: answer the dean |" in table.to_text()          # no number, untouched
    assert table.lists.align_tasks() == []


def test_a_year_at_the_start_of_a_task_is_not_a_project():
    table = WeeklyTable(_week(THIS_WEEK, ["E: 2026 budget for the core"]))
    task = table.lists.entries(GRASSCATCHER)[0]
    assert (task.code, task.number, task.description) == ("E", None,
                                                          "2026 budget for the core")


def test_new_rows_carry_the_number_of_their_code():
    table = WeeklyTable(_week(THIS_WEEK, []))
    table.lists.insert(GRASSCATCHER, None, Entry("1", "draft the methods"))
    table.lists.insert(GRASSCATCHER, None, Entry("E", "file receipts"))
    assert "| 1: 0142 draft the methods |" in table.to_text()
    assert "| E: file receipts " in table.to_text()            # email has no number
    gone = table.lists.remove(GRASSCATCHER, 0)
    assert (gone.code, gone.number, gone.description) == ("1", "0142", "draft the methods")


def test_a_project_on_a_list_gives_its_number_too():
    lists = "\n#+NAME: current-semester-projects\n| C: 2003reviewArticle |\n| - 5005bookChapter |\n"
    table = WeeklyTable(_week(THIS_WEEK, ["C: outline the review", "- 5005 index terms"],
                              lists))
    tasks = table.lists.entries(GRASSCATCHER)
    assert [(t.code, t.number) for t in tasks] == [("C", "2003"), (None, "5005")]


def test_carrying_the_lists_to_a_new_week_keeps_each_task_with_its_project():
    old = WeeklyTable(_week(LAST_WEEK, ["A: read the reviews", "B: tidy the figures",
                                        "E: answer the dean"]))
    new = WeeklyTable(_week(THIS_WEEK, []).split("\n#+NAME: grasscatcher")[0] + "\n")
    assert new.adopt_lists(old)
    tasks = new.lists.entries(GRASSCATCHER)
    assert [(t.code, t.number, t.description) for t in tasks] == [
        ("1", "0142", "read the reviews"), ("A", "1006", "tidy the figures"),
        ("E", None, "answer the dean")]


def test_lists_without_a_number_map_read_as_before():
    lists = ProjectLists(["#+NAME: grasscatcher", "| A: 0142 read it |"])
    task = lists.entries(GRASSCATCHER)[0]
    assert (task.code, task.number, task.description) == ("A", None, "0142 read it")


def test_opening_a_file_with_stale_codes_fixes_and_reports_them(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    store = {}
    monkeypatch.setattr("writing_habit.gui.settings.get", lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    path = tmp_path / "Oct19.org"
    path.write_text(_week(THIS_WEEK, ["A: 0142 [#A1] Read the reviews"]), encoding="utf-8")
    editor = ScheduleEditor()
    qtbot.addWidget(editor)
    editor.open(str(path))
    assert editor.table.dirty
    assert "the code 1 of project 0142 (it was A)" in editor.layout_banner.text()
    panel = editor.list_panels[GRASSCATCHER]
    assert panel.model.index(0, 0).data() == "1"
    assert "0142" not in panel.model.index(0, 1).data()
