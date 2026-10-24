"""The coach in the window: Suggest objectives, Rank, Read my weeks, Size this
week's plan, and the Rule 10 switches."""

import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit import coach, db, review                        # noqa: E402
from writing_habit.review import BlockKey                          # noqa: E402
from writing_habit.track import manual                             # noqa: E402

from test_coach import fake_model                                   # noqa: E402

WEEK = (
    "#+TITLE: coach\n"
    "|        Time | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| 05:00-07:00 | gA |    |\n"
    "| 07:00-08:00 | eB |    |\n"
    "|-------------+----+----|\n"
    "| A: 1006AIrxOpt 2026-11-01 :safe: |  |  |\n"
    "| B: 1002RNAediting 2026-12-01 :safe: |  |  |\n"
    "\n"
    "#+NAME: grasscatcher\n"
    "| B: tidy the methods |\n"
    "| A: find three citations |\n"
    "| - clean the desk |\n"
)

QUIET_TIME = dt.datetime(2026, 10, 14, 12, 0)     # a Wednesday with no block
IN_BLOCK = dt.datetime(2026, 10, 12, 5, 30)       # inside Monday's A block


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / "habit.db"
    con = db.connect(str(path))
    db.init_db(con)
    con.close()
    return {"db": str(path), "ai_model": "tiny", "ai_url": "http://localhost:11434"}


@pytest.fixture()
def editor(qtbot, tmp_path, monkeypatch, store):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    monkeypatch.setattr("writing_habit.gui.settings.get",
                        lambda key: store.get(key, ""))
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
    widget.set_hour_view(True)
    return widget


def use_model(monkeypatch, store, reply, api="ollama"):
    """Turn the model on and answer every request with ``reply``."""
    store["ai_debrief"] = "true"
    store["ai_api"] = api
    real = coach.Client

    def make(**kwargs):
        kwargs["opener"] = fake_model(reply, api=api)
        return real(**kwargs)

    monkeypatch.setattr("writing_habit.gui.coach_runner.coach.Client", make)


def _panel(editor):
    from test_gui_review import quiet
    editor.hour_view.setCurrentIndex(editor.hour_model.index(5, 1))
    editor.run_review = lambda dialog: None
    panel = quiet(editor.open_review().panel, QUIET_TIME)
    panel.dialogs = []

    def answer(dialog):
        panel.dialogs.append(dialog)
        return True

    panel.run_dialog = answer
    return panel


def _log(store):
    con = db.connect(store["db"])
    rows = [dict(r) for r in con.execute("SELECT * FROM ai_log ORDER BY log_id")]
    con.close()
    return rows


# -- Suggest objectives ---------------------------------------------------------------
def test_suggest_adds_the_checked_objectives_with_the_ai_origin(editor, store, monkeypatch):
    use_model(monkeypatch, store, {"objectives": ["Draft aim 2", "Find 3 citations"],
                                   "if_then": "If email calls, then I will park it."})
    panel = _panel(editor)
    panel.focus_spin.setValue(3)                     # a field being typed survives
    panel.objective_edit.setText("work on the R01")
    ids = panel.suggest_objectives()
    assert len(ids) == 2
    dialog = panel.dialogs[0]
    assert "Task: work on the R01" in dialog.answer.facts
    assert "find three citations" in dialog.answer.facts       # A's waiting task
    con = db.connect(store["db"])
    items = review.objectives(con, BlockKey("2026-10-12", "05:00", "A"))
    con.close()
    assert [(o.text, o.origin) for o in items] == [("Draft aim 2", "ai"),
                                                   ("Find 3 citations", "ai")]
    assert "park it" in panel.note_edit.text()
    assert panel.focus_spin.value() == 3
    log = _log(store)
    assert log[0]["task"] == "objectives" and log[0]["accepted"] == 1


def test_suggest_needs_a_task_in_the_box(editor):
    panel = _panel(editor)
    assert panel.suggest_objectives() is None
    assert "Type the task" in panel.limit_label.text()


def test_suggest_in_a_block_asks_first(editor, store):
    panel = _panel(editor)
    panel.guard.now = lambda: IN_BLOCK
    panel.guard.confirm = lambda text: False
    panel.objective_edit.setText("work on the R01")
    assert panel.suggest_objectives() is None
    assert "silent during deep work" in panel.limit_label.text()
    assert _log(store) == []
    panel.guard.confirm = lambda text: True
    panel.suggest_objectives()
    assert len(_log(store)) == 1


def test_the_debrief_is_logged(editor, store):
    panel = _panel(editor)
    panel.model_box.setChecked(False)
    panel.run_debrief()
    log = _log(store)
    assert log[0]["task"] == "debrief"
    assert "Project: 1006AIrxOpt" in log[0]["facts"]


# -- Rank the grasscatcher -------------------------------------------------------------
def test_rank_without_a_model_orders_by_deadline_and_reorders_on_accept(editor, store):
    from writing_habit.project_lists import GRASSCATCHER
    panel = editor.list_panels[GRASSCATCHER]
    assert panel.rank_button.isEnabled()
    panel.rank_button.click()
    entries = [e.description for e in editor.table.lists.entries(GRASSCATCHER)]
    assert entries == ["find three citations", "tidy the methods", "clean the desk"]
    assert editor.table.dirty
    assert _log(store)[0]["accepted"] == 1


def test_rank_discarded_leaves_the_list(editor, store):
    from writing_habit.project_lists import GRASSCATCHER
    editor.accept_dialogs = False
    editor.rank_grasscatcher()
    entries = [e.description for e in editor.table.lists.entries(GRASSCATCHER)]
    assert entries[0] == "tidy the methods"
    assert _log(store)[0]["accepted"] == 0


# -- Read my weeks and Size this week's plan ------------------------------------------
def _history(store):
    con = db.connect(store["db"])
    pid = db.get_or_create_project(con, "A", "1006AIrxOpt", "safe")
    for week in ("2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05"):
        for offset, actual in ((0, 120), (2, 30)):
            day = (dt.date.fromisoformat(week) + dt.timedelta(days=offset)).isoformat()
            con.execute("INSERT INTO plan_block(day, start_time, end_time, project_id,"
                        " category_id) VALUES (?, '05:00', '07:00', ?, 1)", (day, pid))
            manual.add_session(con, day=day, project_code="A", minutes=actual,
                               category="generative")
    con.commit()
    con.close()


def test_read_my_weeks_shows_the_numbers_behind_it(editor, store):
    _history(store)
    answer = editor.read_weeks()
    assert "Wednesday" in answer.text
    dialog = editor.dialogs[-1]
    assert dialog.answer is answer
    assert _log(store)[-1]["task"] == "weeks"


def test_read_my_weeks_with_a_model_keeps_its_wording(editor, store, monkeypatch):
    _history(store)
    use_model(monkeypatch, store, {"patterns": ["Wednesdays hold 25% over 5 weeks.",
                                                "Mondays hold 100% over 5 weeks."],
                                   "change": "Move Wednesday writing to Monday."},
              api="openai")
    answer = editor.read_weeks()
    assert answer.source == "local model tiny"
    assert answer.data["change"] == "Move Wednesday writing to Monday."


def test_size_this_weeks_plan_uses_the_open_table(editor, store):
    _history(store)
    answer = editor.size_week()
    # 150 minutes written in each earlier week; the open table plans 180.
    assert answer.data["minutes"] == 150
    assert answer.data["current"] == 180
    assert "2 h 30 min" in answer.data["text"]


def test_size_with_no_history_says_so(editor, store):
    messages = []
    editor.logged.connect(messages.append)
    assert editor.size_week() is None
    assert any("no earlier planned weeks" in m for m in messages)


# -- Rule 10 switches ------------------------------------------------------------------
def test_ai_off_this_week_silences_every_coach_task(editor, store):
    _history(store)
    editor.ai_off_action.setChecked(True)
    assert store["ai_off_week"] == "2026-10-12"
    messages = []
    editor.logged.connect(messages.append)
    assert editor.read_weeks() is None
    assert any("AI-off week" in m for m in messages)
    assert _log(store) == []
    editor.ai_off_action.setChecked(False)
    assert store["ai_off_week"] == ""


def test_the_model_switch_is_the_shared_setting(editor, store):
    editor.model_action.setChecked(True)
    assert store["ai_debrief"] == "true"
    from writing_habit.gui import coach_runner
    client = coach_runner.client()
    assert client is not None and client.model == "tiny"
    store["ai_debrief"] = "false"
    assert coach_runner.client() is None


def test_the_coach_needs_the_database(editor, store):
    store["db"] = ""
    messages = []
    editor.logged.connect(messages.append)
    assert editor.read_weeks() is None
    assert any("habit database" in m for m in messages)


# -- Coach settings --------------------------------------------------------------------
def test_settings_lists_the_installed_models_and_saves(editor, store):
    editor.list_models = lambda url, api, allow_remote=False: [
        "llama3.2:latest", "qwen2.5:7b"]
    seen = {}

    def run(dialog):
        seen["dialog"] = dialog
        assert dialog.model_box.count() == 2
        assert dialog.model_box.currentText() == "tiny"          # not installed
        assert "tiny is not among them" in dialog.status.text()
        dialog.model_box.setCurrentIndex(1)
        dialog.use_box.setChecked(True)
        dialog.accept()
        return True

    editor.run_coach_settings = run
    editor.open_coach_settings()
    assert store["ai_model"] == "qwen2.5:7b"
    assert store["ai_debrief"] == "true"
    assert store["ai_api"] == "ollama"
    assert editor.model_action.isChecked()


def test_settings_matches_a_latest_tag_and_switches_port(editor, store):
    store["ai_model"] = "llama3.2"
    calls = []

    def lister(url, api, allow_remote=False):
        calls.append((url, api))
        return ["llama3.2:latest"] if api == "ollama" else ["gemma"]

    editor.list_models = lister
    dialogs = []
    editor.run_coach_settings = lambda d: dialogs.append(d) or False
    editor.open_coach_settings()
    dialog = dialogs[0]
    assert dialog.model_box.currentText() == "llama3.2:latest"
    dialog.api_box.setCurrentIndex(1)                      # OpenAI-style
    assert dialog.url_edit.text() == "http://localhost:1234"
    assert calls[-1] == ("http://localhost:1234", "openai")
    assert store.get("ai_api", "") != "openai"             # not saved on cancel


def test_settings_says_when_the_server_is_down(editor, store):
    def down(url, api, allow_remote=False):
        raise coach.CoachError("no model server answered at x")

    editor.list_models = down
    editor.run_coach_settings = lambda d: False
    dialog = editor.open_coach_settings()
    assert "Is the server running" in dialog.status.text()
    assert dialog.model_box.currentText() == "tiny"


# -- Rule 8: the partner summary -------------------------------------------------------
def _partner_week(store):
    """The open week, Oct 12: Monday's block kept, nothing else written."""
    con = db.connect(store["db"])
    pid = db.get_or_create_project(con, "A", "1006AIrxOpt", "safe")
    con.execute("INSERT INTO plan_block(day, start_time, end_time, project_id,"
                " category_id) VALUES ('2026-10-12', '05:00', '07:00', ?, 1)", (pid,))
    manual.add_session(con, day="2026-10-12", project_code="A", minutes=90,
                       category="generative")
    review.ensure(con)
    oid = review.add_objective(con, BlockKey("2026-10-12", "05:00", "A"),
                               "Draft the second aim paragraph")
    review.mark(con, oid, True)
    con.commit()
    con.close()


def test_partner_summary_copies_the_edited_draft(editor, store):
    from writing_habit.gui.qt import QtWidgets
    _partner_week(store)
    shown = []

    def edit_and_copy(dialog):
        shown.append(dialog.text())
        dialog.editor.setPlainText(dialog.text() + " See you Monday.")
        return True

    editor.run_coach_dialog = edit_and_copy
    answer = editor.partner_summary()
    assert answer.data["kept_pct"] == 75
    assert "which is 75% of the plan" in shown[0]
    assert "I met the one objective I committed to." in shown[0]
    assert 'The objective I met was "Draft the second aim paragraph".' in shown[0]
    copied = QtWidgets.QApplication.clipboard().text()
    assert copied.startswith("Here is my writing week of October 12.")
    assert copied.endswith("See you Monday.")
    rows = _log(store)
    assert [r["task"] for r in rows] == ["partner"]
    assert rows[0]["accepted"] == 1


def test_partner_summary_uses_the_model_when_it_is_on(editor, store, monkeypatch):
    _partner_week(store)
    use_model(monkeypatch, store, "I drafted the second aim paragraph and kept 75% "
                                  "of my plan this week.")
    answer = editor.partner_summary()
    assert answer.source == "local model tiny"
    assert editor.dialogs[-1].text().startswith("I drafted the second aim paragraph")


def test_partner_summary_in_an_ai_off_week_is_plain_and_unlogged(editor, store,
                                                                monkeypatch):
    _partner_week(store)
    use_model(monkeypatch, store, "anything")
    editor.ai_off_action.setChecked(True)
    answer = editor.partner_summary()
    assert answer is not None
    assert "AI-off week" in answer.source
    assert answer.data["text"].startswith("Here is my writing week")
    assert _log(store) == []


def test_partner_summary_without_a_plan_says_so(editor, store):
    messages = []
    editor.logged.connect(messages.append)
    answer = editor.partner_summary()
    assert answer.data is None
    assert any("nothing to summarize" in m for m in messages)
    assert editor.dialogs == []
