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
