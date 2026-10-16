"""Period names on the project tabs, the banner, Roll forward, the Carried over
list, the Periods dialog, and the Hour view button's place in the bar.
"""

import datetime as dt
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit import periods as pm                              # noqa: E402
from writing_habit.project_lists import CARRIED, COMPLETED, CURRENT  # noqa: E402

from test_periods import CALENDAR                                     # noqa: E402

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

#+NAME: completed-this-semester
| X: 0374qflip 2026-11-21 :risky: |

#+NAME: next-semester-projects
| - 1452PHFSboXt 2027-03-01 :safe: |
"""


@pytest.fixture()
def store():
    return {}


def _editor(qtbot, monkeypatch, store, path, today=dt.date(2026, 10, 15)):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    monkeypatch.setattr("writing_habit.gui.settings.get",
                        lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    widget.today = lambda: today
    widget.open(str(path))
    return widget


@pytest.fixture()
def folder(tmp_path):
    (tmp_path / "periods.org").write_text(CALENDAR, encoding="utf-8")
    return tmp_path


def _tab_titles(editor):
    tabs = editor.project_tabs
    return {tabs.tabText(i): tabs.isTabVisible(i) for i in range(tabs.count())}


# -- the Hour view button ------------------------------------------------------
def test_the_hour_button_comes_first(qtbot, monkeypatch, store, tmp_path):
    path = tmp_path / "week.org"
    path.write_text(WEEK)
    editor = _editor(qtbot, monkeypatch, store, path)
    bar = editor.layout().itemAt(0).layout()
    assert bar.itemAt(0).widget() is editor.hour_button
    assert bar.itemAt(1).widget() is editor.open_button


def test_the_hour_view_is_the_default_setting():
    from writing_habit.gui import settings
    assert settings.DEFAULTS["hour_view"] == "true"


# -- titles ---------------------------------------------------------------------
def test_without_a_calendar_the_titles_stay(qtbot, monkeypatch, store, tmp_path):
    path = tmp_path / "Oct12.org"
    path.write_text(WEEK)
    editor = _editor(qtbot, monkeypatch, store, path)
    assert "Current semester projects (2)" in _tab_titles(editor)
    assert not editor.period_banner.isVisibleTo(editor)


def test_the_calendar_names_the_tabs(qtbot, monkeypatch, store, folder):
    path = folder / "Oct12.org"
    path.write_text(WEEK)
    editor = _editor(qtbot, monkeypatch, store, path)
    titles = _tab_titles(editor)
    assert titles["Fall 2026 projects (2)"] is True
    assert titles["Completed in Fall 2026 (1)"] is True
    assert titles["Spring 2027 projects (1)"] is True
    assert "Summer 2027 projects" in titles
    assert "Fall 2027 projects" in titles
    assert "Spring 2028 projects" in titles
    assert titles["Carried over"] is False   # before Fall 2026 nothing is earlier
    index = list(editor.list_panels).index(CURRENT) + 1
    assert "2026-08-04" in editor.project_tabs.tabToolTip(index)
    assert "current-semester-projects" in editor.project_tabs.tabToolTip(index)


def test_the_file_name_date_beats_today(qtbot, monkeypatch, store, folder):
    path = folder / "Dec21.org"
    path.write_text(WEEK)
    editor = _editor(qtbot, monkeypatch, store, path, today=dt.date(2026, 12, 15))
    assert "Spring 2027 projects (2)" in _tab_titles(editor)


# -- the banner -----------------------------------------------------------------
def test_unfiled_lists_ask_for_their_period(qtbot, monkeypatch, store, folder):
    path = folder / "Oct12.org"
    path.write_text(WEEK)
    editor = _editor(qtbot, monkeypatch, store, path)
    assert editor.period_banner.isVisibleTo(editor)
    assert editor.period_choice.currentText() == "Fall 2026"
    assert not editor.roll_button.isVisibleTo(editor)
    assert editor.file_lists_under("Fall 2026")
    assert editor.table.lists.period() == "Fall 2026"
    assert editor.table.dirty
    assert not editor.period_banner.isVisibleTo(editor)


def test_a_new_period_offers_a_roll(qtbot, monkeypatch, store, folder):
    path = folder / "Jan4.org"
    path.write_text(WEEK.replace("#+NAME: current", "#+PROJECT_PERIOD: Fall 2026\n\n#+NAME: current"))
    editor = _editor(qtbot, monkeypatch, store, path, today=dt.date(2026, 12, 30))
    assert editor.period_banner.isVisibleTo(editor)
    assert editor.roll_button.text() == "Roll forward to Spring 2027"
    assert "filed under Fall 2026" in editor.period_label.text()


# -- rolling forward --------------------------------------------------------------
def _rolled(qtbot, monkeypatch, store, folder, today, stem="Jan4"):
    path = folder / f"{stem}.org"
    path.write_text(WEEK.replace("#+NAME: current", "#+PROJECT_PERIOD: Fall 2026\n\n#+NAME: current"))
    editor = _editor(qtbot, monkeypatch, store, path, today=today)
    asked = []
    monkeypatch.setattr(editor, "_confirm", lambda title, text: asked.append(text) or True)
    return editor, asked


def test_roll_forward_moves_the_lists_and_archives(qtbot, monkeypatch, store, folder):
    editor, asked = _rolled(qtbot, monkeypatch, store, folder, dt.date(2026, 12, 30))
    assert editor.roll_forward() == 1
    assert "1 completed project(s)" in asked[0] and "Carried over" in asked[0]
    lists = editor.table.lists
    assert lists.period() == "Spring 2027"
    assert [e.project for e in lists.entries(CARRIED)] == [
        "1094RNAstrucDetResearchProgram", "1006AIrxOpt"]
    assert [e.project for e in lists.entries(CURRENT)] == ["1452PHFSboXt"]
    assert lists.entries(COMPLETED) == []
    archive = (folder / "completed.org").read_text()
    assert "* Fall 2026" in archive and "0374qflip" in archive
    titles = _tab_titles(editor)
    assert titles["Carried over from Fall 2026 (2)"] is True
    assert editor.project_tabs.currentWidget() is editor.list_panels[CARRIED]
    assert not editor.period_banner.isVisibleTo(editor)
    assert editor.table.dirty


def test_a_declined_roll_changes_nothing(qtbot, monkeypatch, store, folder):
    editor, _asked = _rolled(qtbot, monkeypatch, store, folder, dt.date(2026, 12, 30))
    monkeypatch.setattr(editor, "_confirm", lambda title, text: False)
    text = editor.table.to_text()
    assert editor.roll_forward() == 0
    assert editor.table.to_text() == text
    assert not (folder / "completed.org").exists()


def test_a_long_absence_rolls_several_steps(qtbot, monkeypatch, store, folder):
    editor, asked = _rolled(qtbot, monkeypatch, store, folder,
                            dt.date(2027, 8, 20), stem="Aug16")
    assert editor.roll_forward() == 3
    assert "3 periods" in asked[0]
    assert editor.table.lists.period() == "Fall 2027"
    assert [e.project for e in editor.table.lists.entries(CARRIED)] == [
        "1094RNAstrucDetResearchProgram", "1006AIrxOpt", "1452PHFSboXt"]


def test_carried_projects_can_be_kept(qtbot, monkeypatch, store, folder):
    editor, _asked = _rolled(qtbot, monkeypatch, store, folder, dt.date(2026, 12, 30))
    editor.roll_forward()
    panel = editor.list_panels[CARRIED]
    panel.view.setCurrentIndex(panel.model.index(1, 0))
    assert panel.keep().project == "1006AIrxOpt"
    assert [e.project for e in editor.table.lists.entries(CURRENT)] == [
        "1452PHFSboXt", "1006AIrxOpt"]
    panel.view.setCurrentIndex(panel.model.index(0, 0))
    assert panel.delete().project == "1094RNAstrucDetResearchProgram"
    assert editor.table.lists.entries(CARRIED) == []
    assert _tab_titles(editor)["Carried over from Fall 2026"] is False


def test_a_rolled_table_saves_and_reopens(qtbot, monkeypatch, store, folder):
    editor, _asked = _rolled(qtbot, monkeypatch, store, folder, dt.date(2026, 12, 30))
    editor.roll_forward()
    saved = editor.save()
    again = _editor(qtbot, monkeypatch, store, Path(saved), today=dt.date(2026, 12, 30))
    assert again.table.lists.period() == "Spring 2027"
    assert not again.period_banner.isVisibleTo(again)


# -- the Periods dialog -------------------------------------------------------------
def test_the_dialog_shows_and_saves_the_calendar(qtbot, monkeypatch, store, folder):
    path = folder / "Oct12.org"
    path.write_text(WEEK)
    editor = _editor(qtbot, monkeypatch, store, path)

    def run(dialog):
        assert dialog.table.rowCount() == 7
        assert dialog.problem_list() == []
        dialog.table.item(0, 1).setText("Autumn 2026")
        return dialog.save() is not None

    monkeypatch.setattr(editor, "run_periods", run)
    assert editor.open_periods() == str(folder / "periods.org")
    assert "Autumn 2026" in (folder / "periods.org").read_text()
    assert "Autumn 2026 projects (2)" in _tab_titles(editor)
    assert store["period_kind"] == "semester"


def test_the_dialog_starts_a_calendar_from_a_template(qtbot, monkeypatch, store, tmp_path):
    path = tmp_path / "Oct12.org"
    path.write_text(WEEK)
    editor = _editor(qtbot, monkeypatch, store, path)

    def run(dialog):
        assert dialog.table.rowCount() == 0
        assert dialog.fill("semesters", 2026) == 3
        assert dialog.fill("semesters", 2027) == 3
        assert dialog.fill("semesters", 2027) == 0          # no duplicates
        dialog.sort_rows()
        return dialog.save() is not None

    monkeypatch.setattr(editor, "run_periods", run)
    editor.open_periods()
    cal = pm.Calendar.from_file(str(tmp_path / "periods.org"))
    assert [p.name for p in cal.of_kind("semester")][:3] == [
        "Spring 2026", "Summer 2026", "Fall 2026"]
    assert "Fall 2026 projects (2)" in _tab_titles(editor)


def test_the_dialog_reports_problems_before_saving(qtbot, monkeypatch, store, folder):
    from writing_habit.gui.periods_dialog import PeriodsDialog
    path = folder / "periods.org"
    dialog = PeriodsDialog(pm.Calendar.from_file(str(path)), path)
    qtbot.addWidget(dialog)
    dialog.table.item(1, 2).setText("2026-12-01")           # Spring overlaps Fall
    assert any("overlap" in p for p in dialog.problem_list())
    assert "overlap" in dialog.problems.text()
    monkeypatch.setattr(dialog, "confirm_problems", lambda problems: False)
    before = path.read_text()
    assert dialog.save() is None
    assert path.read_text() == before


def test_the_dialog_reorders_and_deletes(qtbot, folder):
    from writing_habit.gui.periods_dialog import PeriodsDialog
    path = folder / "periods.org"
    dialog = PeriodsDialog(pm.Calendar.from_file(str(path)), path)
    qtbot.addWidget(dialog)
    dialog.table.setCurrentCell(0, 1)
    dialog.move_row(up=False)
    assert [p.name for p in dialog.periods()][:2] == ["Spring 2027", "Fall 2026"]
    dialog.delete_row()
    assert len(dialog.periods()) == 6
    dialog.add_row()
    assert len(dialog.periods()) == 7


def test_before_a_roll_the_titles_follow_the_filed_period(qtbot, monkeypatch, store, folder):
    editor, _asked = _rolled(qtbot, monkeypatch, store, folder, dt.date(2026, 12, 30))
    titles = _tab_titles(editor)
    assert "Fall 2026 projects (2)" in titles
    assert "Completed in Fall 2026 (1)" in titles
    editor.roll_forward()
    titles = _tab_titles(editor)
    assert "Spring 2027 projects (1)" in titles
    assert "Completed in Spring 2027" in titles
