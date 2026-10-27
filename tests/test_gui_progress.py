"""The Progress tab and the next-week plan of the Schedule tab's Coach menu."""

import datetime as dt
import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit import db, progress                               # noqa: E402

from test_gui_coach import use_model                                 # noqa: E402

WEEK = (
    "#+TITLE: progress\n"
    "|        Time | M  | Tu | W  | Th | F  |\n"
    "|-------------+----+----+----+----+----|\n"
    "| 05:00-06:30 | gA | gB | gA | gB | gA |\n"
    "|-------------+----+----+----+----+----|\n"
    "| A: 1006AIrxOpt 2026-12-15 :safe: |  |  |  |  |  |\n"
    "| B: 0201dusp1 :safe: |  |  |  |  |  |\n"
    "\n"
    "#+NAME: current-semester-projects\n"
    "| A: 1006AIrxOpt 2026-12-15 :safe: |\n"
    "| B: 0201dusp1 :safe: |\n"
    "| - email |\n"
    "\n"
    "#+NAME: next week\n"
    "| - 0655VirtIssue25 |\n"
)

QUIET_TIME = dt.datetime(2026, 10, 14, 12, 0)


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / "habit.db"
    con = db.connect(str(path))
    db.init_db(con)
    con.close()
    mytime = tmp_path / "mytime.db"
    con = sqlite3.connect(mytime)
    con.execute('CREATE TABLE zTimeSpent (id INTEGER PRIMARY KEY, DateDashed DATE,'
                ' Start TIME, "End" TIME, ProjectID INT, ProjectDirectory TEXT,'
                ' Description TEXT, Activity TEXT)')
    con.executemany("INSERT INTO zTimeSpent VALUES (NULL,?,?,?,?,?,'','')", [
        ("2026-10-05", "05:00", "08:00", 1006, "1006AIrxOpt"),
        ("2026-10-06", "05:00", "05:30", 201, "0201dusp1")])
    con.commit()
    con.close()
    return {"db": str(path), "mytime_db": str(mytime), "ai_model": "tiny",
            "ai_url": "http://localhost:11434"}


@pytest.fixture()
def editor(qtbot, tmp_path, monkeypatch, store):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    monkeypatch.setattr("writing_habit.gui.settings.get", lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    widget.today = lambda: dt.date(2026, 10, 14)
    widget.coach_runner.background = False
    widget.coach_guard.now = lambda: QUIET_TIME
    widget.dialogs = []

    def answer(dialog):
        widget.dialogs.append(dialog)
        return getattr(widget, "accept_dialogs", True)

    widget.run_coach_dialog = answer
    qtbot.addWidget(widget)
    path = tmp_path / "Oct12.org"
    path.write_text(WEEK, encoding="utf-8")
    widget.open(str(path))
    return widget


@pytest.fixture()
def view(qtbot, editor):
    from writing_habit.gui.progress_view import ProgressView
    widget = ProgressView(editor)
    qtbot.addWidget(widget)
    return widget


def test_view_without_a_table_offers_to_make_one(view):
    assert view.rows == []
    assert "no progress table" in view.status.text()
    assert view.seed_button.isEnabled()
    assert not view.update_button.isEnabled()


def test_seed_makes_the_table_from_the_current_list(view, editor):
    assert view.seed() == 2
    rows = progress.read(editor.table.lists.lines)
    assert [(r.number, r.name) for r in rows] == [("0201", "dusp1"), ("1006", "AIrxOpt")]
    assert editor.table.dirty
    assert view.grid.rowCount() == 2
    assert view.seed() == 0


def test_the_table_is_saved_at_the_end_of_the_file(view, editor):
    view.seed()
    path = editor.table.save()
    text = open(path, encoding="utf-8").read()
    assert text.rstrip().splitlines()[-5] == "#+NAME: progress"
    assert "#+NAME: next week" in text
    editor.open(path)
    assert [r.number for r in progress.read(editor.table.lists.lines)] == ["0201", "1006"]


def test_update_reads_the_hours_from_mytime(view, editor):
    view.seed()
    assert view.update_hours() == 2
    rows = {r.number: r.spent for r in progress.read(editor.table.lists.lines)}
    assert rows == {"0201": 0.5, "1006": 3.0}
    assert view.grid.item(1, 3).text() == "3"
    assert view.update_hours() == 0


def test_update_says_when_mytime_is_missing(view, store):
    view.seed()
    store["mytime_db"] = "/nowhere/mytime.db"
    messages = []
    view.logged.connect(messages.append)
    assert view.update_hours() is None
    assert "Could not read the hours spent" in messages[-1]


def test_typing_an_estimate_and_weight_writes_the_file(view, editor):
    view.seed()
    view.grid.item(1, 2).setText("120")
    view.grid.item(1, 4).setText("5")
    row = progress.read(editor.table.lists.lines)[1]
    assert (row.estimate, row.weight) == (120, 5)
    assert view.chart.rows[1].estimate == 120


def test_a_word_is_not_an_estimate(view, editor):
    view.seed()
    view.grid.item(0, 2).setText("lots")
    assert progress.read(editor.table.lists.lines)[0].estimate is None
    assert view.grid.item(0, 2).text() == ""


def test_hours_spent_is_not_editable(view):
    from writing_habit.gui.qt import Qt
    view.seed()
    assert not view.grid.item(0, 3).flags() & Qt.ItemIsEditable


def test_remove_row(view, editor):
    view.seed()
    view.grid.selectRow(0)
    view.remove_selected()
    assert [r.number for r in progress.read(editor.table.lists.lines)] == ["1006"]


def test_chart_draws_bars_to_scale(view, qtbot):
    view.seed()
    view.grid.item(0, 2).setText("40")
    view.grid.item(1, 2).setText("100")
    view.update_hours()
    chart = view.chart
    chart.resize(600, chart.height())
    assert chart.scale_max() == 100
    whole = chart.bar_rect(1, 100)
    spent = chart.bar_rect(1, 3)
    assert spent.width() == pytest.approx(whole.width() * 0.03, abs=0.5)
    assert "Hours left: 97" in chart.tip(1)
    image = chart.grab().toImage()
    assert not image.isNull()


def test_chart_marks_an_overrun(view):
    view.chart.set_rows([progress.Row("0001", "late", 10, 12, 1)])
    assert view.chart.scale_max() >= 12
    assert "Over the estimate by 2 hours" in view.chart.tip(0)
    view.chart.grab()


def test_nice_step():
    from writing_habit.gui.progress_view import nice_step
    assert nice_step(100) == 20
    assert nice_step(12) == 2
    assert nice_step(0) == 1


# -- next week's plan --------------------------------------------------------------
def _weights(editor):
    lines = editor.table.lists.lines
    progress.write(lines, [progress.Row("0201", "dusp1", 40, 10, 1),
                           progress.Row("1006", "AIrxOpt", 100, 3, 3),
                           progress.Row("0655", "VirtIssue25")])


def test_plan_shares_the_open_week_by_weight(editor):
    _weights(editor)
    plan = editor.progress_plan()
    assert plan.capacity == 450
    shares = {r.number: m for r, m in plan.shares}
    assert shares == {"1006": 330, "0201": 120}
    assert [r.number for r in plan.left_out] == ["0655"]
    assert sum(int(b.end[:2]) * 60 + int(b.end[3:]) - int(b.start[:2]) * 60
               - int(b.start[3:]) for b in plan.blocks) == 450


def test_plan_needs_a_progress_table(editor):
    messages = []
    editor.logged.connect(messages.append)
    assert editor.plan_from_progress() is None
    assert "no progress table" in messages[-1]


def test_plan_adds_the_checked_projects_to_next_week(editor, store):
    _weights(editor)
    answer = editor.plan_from_progress()
    dialog = editor.dialogs[-1]
    assert dialog.boxes[0].text().startswith("1006 AIrxOpt: 5 h 30 min (")
    assert dialog.boxes[1].text().startswith("0201 dusp1: 2 h 00 min (")
    assert "go by weight" in answer.data["note"]
    projects = [e.project for e in editor.table.lists.entries("next week")]
    assert projects == ["0655VirtIssue25", "1006AIrxOpt", "0201dusp1"]
    assert editor.table.dirty
    from writing_habit.gui.qt import QtWidgets
    assert "AIrxOpt" in QtWidgets.QApplication.clipboard().text()


def test_plan_adds_nothing_twice(editor):
    _weights(editor)
    editor.plan_from_progress()
    editor.plan_from_progress()
    projects = [e.project for e in editor.table.lists.entries("next week")]
    assert projects.count("1006AIrxOpt") == 1


def test_plan_note_comes_from_the_model_when_it_keeps_the_numbers(editor, store,
                                                                  monkeypatch):
    _weights(editor)
    use_model(monkeypatch, store, "Most of the week goes to AIrxOpt, in your best "
              "morning hours.")
    answer = editor.plan_from_progress()
    assert answer.data["note"].startswith("Most of the week goes to AIrxOpt")
    con = db.connect(store["db"])
    tasks = [r[0] for r in con.execute("SELECT task FROM ai_log")]
    con.close()
    assert tasks[-1] == "progress_plan"


def test_plan_note_with_a_new_number_falls_back(editor, store, monkeypatch):
    _weights(editor)
    use_model(monkeypatch, store, "Spend 17 hours on AIrxOpt.")
    answer = editor.plan_from_progress()
    assert answer.data["note"].startswith("Next week's 7 h 30 min go by weight")


# -- saving, and updating the plan --------------------------------------------------
def test_save_writes_the_table_to_disk(view, editor):
    view.seed()
    view.grid.item(1, 2).setText("120")
    view.grid.item(1, 4).setText("5")
    assert view.save_button.isEnabled()
    assert "not saved yet" in view.status.text()
    path = view.save()
    assert not editor.table.dirty
    assert not view.save_button.isEnabled()
    assert "not saved yet" not in view.status.text()
    rows = progress.read(open(path, encoding="utf-8").read().splitlines())
    assert (rows[1].estimate, rows[1].weight) == (120, 5)


def test_unchecking_and_updating_shares_the_week_again(editor):
    _weights(editor)
    seen = {}

    def uncheck(dialog):
        editor.dialogs.append(dialog)
        dialog.boxes[1].setChecked(False)          # 0201 dusp1
        dialog.update_button.click()
        seen["texts"] = [box.text() for box in dialog.boxes]
        seen["note"] = dialog.intro_widget.text()
        return True

    editor.run_coach_dialog = uncheck
    editor.plan_from_progress()
    assert seen["texts"][0].startswith("1006 AIrxOpt: 7 h 30 min (")
    assert seen["texts"][1] == "0201 dusp1: not in this plan"
    assert seen["note"].startswith("All of next week's 7 h 30 min go to 1006 AIrxOpt.")
    projects = [e.project for e in editor.table.lists.entries("next week")]
    assert projects == ["0655VirtIssue25", "1006AIrxOpt"]
    from writing_habit.gui.qt import QtWidgets
    assert "dusp1" not in QtWidgets.QApplication.clipboard().text()


def test_accepting_after_unchecking_updates_the_plan_first(editor):
    _weights(editor)

    def uncheck(dialog):
        editor.dialogs.append(dialog)
        dialog.boxes[0].setChecked(False)          # 1006 AIrxOpt
        return True

    editor.run_coach_dialog = uncheck
    editor.plan_from_progress()
    dialog = editor.dialogs[-1]
    assert [r.number for r, _m in dialog.plan.shares] == ["0201"]
    projects = [e.project for e in editor.table.lists.entries("next week")]
    assert projects == ["0655VirtIssue25", "0201dusp1"]


def test_rechecking_brings_a_project_back(editor):
    _weights(editor)

    def toggle(dialog):
        editor.dialogs.append(dialog)
        dialog.boxes[1].setChecked(False)
        dialog.update_button.click()
        dialog.boxes[1].setChecked(True)
        dialog.update_button.click()
        return False

    editor.run_coach_dialog = toggle
    editor.plan_from_progress()
    dialog = editor.dialogs[-1]
    assert {r.number: m for r, m in dialog.plan.shares} == {"1006": 330, "0201": 120}


# -- the checked projects carry over, and heavy ones are highlighted ------------------
def _fractional(editor, dusp1_planned=True):
    progress.write(editor.table.lists.lines,
                   [progress.Row("0201", "dusp1", 40, 10, 0.4, dusp1_planned),
                    progress.Row("1006", "AIrxOpt", 100, 3, 0.9),
                    progress.Row("0655", "VirtIssue25")])


def test_accepted_choices_are_written_to_the_table(editor):
    _fractional(editor)

    def uncheck(dialog):
        editor.dialogs.append(dialog)
        dialog.boxes[1].setChecked(False)          # 0201 dusp1
        return True

    editor.run_coach_dialog = uncheck
    editor.plan_from_progress()
    rows = {r.number: r.planned for r in progress.read(editor.table.lists.lines)}
    assert rows == {"0201": False, "1006": True, "0655": True}
    assert editor.table.dirty


def test_the_choice_carries_over_to_the_next_plan(editor, tmp_path):
    _fractional(editor, dusp1_planned=False)
    path = editor.table.save()
    # Next week's file starts as a copy of this one.
    copy = tmp_path / "Nov02.org"
    copy.write_text(open(path, encoding="utf-8").read(), encoding="utf-8")
    editor.open(str(copy))
    editor.accept_dialogs = False
    editor.plan_from_progress()
    dialog = editor.dialogs[-1]
    assert [r.number for r in dialog.rows] == ["1006", "0201"]
    assert [b.isChecked() for b in dialog.boxes] == [True, False]
    assert [r.number for r, _m in dialog.plan.shares] == ["1006"]
    assert dialog.boxes[1].text() == "0201 dusp1: not in this plan"


def test_rechecking_a_project_brings_it_back_next_week(editor):
    _fractional(editor, dusp1_planned=False)

    def recheck(dialog):
        editor.dialogs.append(dialog)
        dialog.boxes[1].setChecked(True)
        return True

    editor.run_coach_dialog = recheck
    editor.plan_from_progress()
    assert [r.number for r, _m in editor.dialogs[-1].plan.shares] == ["1006", "0201"]
    assert all(r.planned for r in progress.read(editor.table.lists.lines))


def test_discarding_keeps_the_old_choices(editor):
    _fractional(editor)

    def uncheck(dialog):
        editor.dialogs.append(dialog)
        dialog.boxes[1].setChecked(False)
        dialog.update_button.click()
        return False

    editor.run_coach_dialog = uncheck
    editor.plan_from_progress()
    assert all(r.planned for r in progress.read(editor.table.lists.lines))


def test_nothing_checked_still_opens_the_dialog(editor):
    progress.write(editor.table.lists.lines,
                   [progress.Row("1006", "AIrxOpt", 100, 3, 0.9, planned=False)])
    editor.accept_dialogs = False
    answer = editor.plan_from_progress()
    assert "No project is checked" in answer.data["note"]
    assert [b.isChecked() for b in editor.dialogs[-1].boxes] == [False]


def test_checked_heavy_projects_are_highlighted_in_the_dialog(editor):
    _fractional(editor)
    editor.accept_dialogs = False
    editor.plan_from_progress()
    dialog = editor.dialogs[-1]
    assert [r.number for r in dialog.highlighted()] == ["1006"]
    assert "#fff1b8" in dialog.boxes[0].styleSheet()
    dialog.boxes[0].setChecked(False)
    assert dialog.highlighted() == []
    assert dialog.boxes[0].styleSheet() == ""


def test_the_grid_checkbox_and_highlight(view, editor):
    from writing_habit.gui.qt import Qt
    _fractional(editor)
    view.reload()
    assert view.grid.horizontalHeaderItem(7).text() == "Next week"
    assert view.highlighted() == ["1006"]
    view.grid.item(1, 7).setCheckState(Qt.Unchecked)          # 1006
    assert not progress.read(editor.table.lists.lines)[1].planned
    assert view.highlighted() == []
    view.grid.item(1, 7).setCheckState(Qt.Checked)
    assert view.highlighted() == ["1006"]


# -- deadlines ------------------------------------------------------------------------
@pytest.fixture()
def oct14(monkeypatch):
    monkeypatch.setattr(progress, "today", lambda: dt.date(2026, 10, 14))


def test_seed_brings_the_deadline_and_days(view, editor, oct14):
    view.seed()
    rows = {r.number: r.deadline for r in progress.read(editor.table.lists.lines)}
    assert rows == {"0201": None, "1006": "2026-12-15"}
    assert view.grid.item(1, 5).text() == "2026-12-15"
    assert view.grid.item(1, 6).text() == "62"
    from writing_habit.gui.qt import Qt
    assert not view.grid.item(1, 6).flags() & Qt.ItemIsEditable


def test_typing_a_deadline_updates_the_days(view, editor, oct14):
    view.seed()
    view.grid.item(0, 5).setText("2026-10-10")
    assert progress.read(editor.table.lists.lines)[0].deadline == "2026-10-10"
    assert view.grid.item(0, 6).text() == "-4"
    assert view.chart.days_label(view.chart.rows[0]) == "4 d late"
    view.grid.item(0, 5).setText("Friday")
    assert progress.read(editor.table.lists.lines)[0].deadline == "2026-10-10"
    view.grid.item(0, 5).setText("")
    assert progress.read(editor.table.lists.lines)[0].deadline is None


def test_update_fills_a_missing_deadline(view, editor, oct14):
    progress.write(editor.table.lists.lines, [progress.Row("1006", "AIrxOpt", 100)])
    view.reload()
    view.update_hours()
    assert progress.read(editor.table.lists.lines)[0].deadline == "2026-12-15"


def test_chart_draws_the_days_at_the_end_of_the_bar(view, oct14):
    from writing_habit.gui.progress_view import LATE, MUTED, SOON
    chart = view.chart
    chart.set_rows([progress.Row("0001", "a", 10, 2, deadline="2026-12-31"),
                    progress.Row("0002", "b", 10, 12, deadline="2026-10-20"),
                    progress.Row("0003", "c", None, 3, deadline="2026-10-01"),
                    progress.Row("0004", "d", 10, 1)])
    chart.resize(700, chart.height())
    assert [chart.days_label(r) for r in chart.rows] == ["78 d", "6 d", "13 d late", ""]
    assert [chart.days_color(r) for r in chart.rows[:3]] == [MUTED, SOON, LATE]
    assert chart.x_of(chart.scale_max()) <= chart.width() - chart.RIGHT
    assert "Deadline: 2026-10-20 (6 d)" in chart.tip(1)
    image = chart.grab().toImage()
    assert not image.isNull()
