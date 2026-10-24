"""Deadline coverage and the Energy tab in the window (Rules 2 and 3)."""

import datetime as dt
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit import db, energy, review                        # noqa: E402
from writing_habit.review import BlockKey                          # noqa: E402

from test_gui_coach import use_model                                # noqa: E402

# Today is Wednesday Oct 14, so Monday and Tuesday have passed.
WEEK = (
    "#+TITLE: plan checks\n"
    "|        Time | M  | Tu | W  | Th | F  |\n"
    "|-------------+----+----+----+----+----|\n"
    "| 05:00-06:30 | gA | sE | gC | sE | gC |\n"
    "| 14:00-15:30 |    | gB |    | gC |    |\n"
    "|-------------+----+----+----+----+----|\n"
    "| A: 1006AIrxOpt 2026-10-30 :safe: |  |  |  |  |  |\n"
    "| B: 1002RNAediting 2027-03-01 :safe: |  |  |  |  |  |\n"
    "| C: 2003reviewArticle :safe: |  |  |  |  |  |\n"
    "| E: email |  |  |  |  |  |\n"
    "\n"
    "#+NAME: current-semester-projects\n"
    "| - 1452PHFSboXt 2026-11-02 :safe: |\n"
)

QUIET_TIME = dt.datetime(2026, 10, 14, 12, 0)


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
    return widget


def _cell(editor, offset, start):
    for block in editor.table.blocks():
        if (block.offset, block.start) == (offset, start):
            return editor.table.cell(block.row, block.column)
    return None


def _log(store):
    con = db.connect(store["db"])
    rows = [dict(r) for r in con.execute("SELECT * FROM ai_log ORDER BY log_id")]
    con.close()
    return rows


# -- deadline coverage -----------------------------------------------------------------
def test_coverage_proposes_a_block_for_each_project_due_soon(editor, store):
    editor.accept_dialogs = False
    answer = editor.check_coverage()
    dialog = editor.dialogs[-1]
    lines = [box.text() for box in dialog.boxes]
    assert lines == [
        "Give Wednesday 05:00-06:30 (generative) to A 1006AIrxOpt, taking it from "
        "C 2003reviewArticle",
        "Give Thursday 14:00-15:30 (generative) to 1452PHFSboXt, taking it from "
        "C 2003reviewArticle"]
    assert "A 1006AIrxOpt is due 2026-10-30, in 16 days" in answer.data["note"]
    assert _cell(editor, 2, "05:00") == "gC"            # nothing changes on Discard
    assert _log(store)[-1]["task"] == "coverage"
    assert _log(store)[-1]["accepted"] == 0


def test_accepting_coverage_gives_the_blocks_and_adds_a_list_project(editor, store):
    editor.check_coverage()
    assert _cell(editor, 2, "05:00") == "gA"
    new = editor.table.cell(*next((b.row, b.column) for b in editor.table.blocks()
                                  if (b.offset, b.start) == (3, "14:00")))
    code = new[1:]
    assert new.startswith("g")
    assert editor.table.project_info(code)["name"] == "1452PHFSboXt"
    assert editor.table.dirty
    # The check now finds nothing at risk.
    editor.dialogs.clear()
    messages = []
    editor.logged.connect(messages.append)
    editor.check_coverage()
    assert editor.dialogs == []
    assert any("has time left in this week's plan" in m for m in messages)


def test_coverage_counts_only_the_set_number_of_days(editor, store):
    store["coverage_days"] = "5"
    messages = []
    editor.logged.connect(messages.append)
    editor.check_coverage()
    assert editor.dialogs == []
    assert any("No project in the legend or the lists is due in the next 5 days"
               in m for m in messages)


def test_coverage_runs_without_a_database_and_logs_nothing(editor, store):
    store["db"] = ""
    editor.accept_dialogs = False
    answer = editor.check_coverage()
    assert answer is not None and answer.log_id is None
    assert len(editor.dialogs[-1].boxes) == 2


def test_coverage_in_an_ai_off_week_is_plain_and_unlogged(editor, store, monkeypatch):
    use_model(monkeypatch, store, "anything")
    editor.ai_off_action.setChecked(True)
    editor.accept_dialogs = False
    answer = editor.check_coverage()
    assert "AI-off week" in answer.source
    assert _log(store) == []


def test_the_model_words_the_coverage_note(editor, store, monkeypatch):
    note = "Your grant is due in 16 days and has no time left, so give it Wednesday."
    use_model(monkeypatch, store, note)
    editor.accept_dialogs = False
    answer = editor.check_coverage()
    assert answer.data["note"] == note
    assert len(editor.dialogs[-1].boxes) == 2       # the proposals stay the software's


# -- the Energy tab --------------------------------------------------------------------
def test_the_energy_tab_counts_the_blocks_that_do_not_fit(editor):
    index = editor.panels.indexOf(editor.energy_panel)
    assert editor.panels.tabText(index) == "Energy (4)"
    report = editor.energy_panel.report.toPlainText()
    assert report.startswith("4 blocks do not fit your energy profile.")
    assert "Tuesday 05:00-06:30  support E uses your high hours" in report


def test_clicking_a_cell_steps_the_level_and_saves_the_profile(editor, store):
    panel = editor.energy_panel
    assert panel.level(14, "generative") == energy.LOW
    panel.step(14, 0)
    assert panel.grid.item(14, 0).text() == "Medium"
    saved = json.loads(store["energy_profile"])
    assert saved["generative"][14] == energy.MEDIUM
    panel.step(14, 0)
    panel.step(14, 0)
    assert json.loads(store["energy_profile"])["generative"][14] == energy.LOW
    panel.reset()
    assert energy.load(store["energy_profile"]) == energy.default_profile()


def test_a_saved_profile_is_read_when_the_window_opens(qtbot, monkeypatch, store):
    profile = energy.default_profile()
    profile["generative"] = [energy.HIGH] * 24
    store["energy_profile"] = energy.dump(profile)
    monkeypatch.setattr("writing_habit.gui.settings.get", lambda key: store.get(key, ""))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    assert widget.energy_panel.level(14, "generative") == energy.HIGH


def test_matching_swaps_only_blocks_still_ahead(editor, store):
    editor.match_energy()
    dialog = editor.dialogs[-1]
    assert [box.text() for box in dialog.boxes] == [
        "Thursday: swap support E at 05:00-06:30 with generative C at 14:00-15:30"]
    assert _cell(editor, 3, "05:00") == "gC"
    assert _cell(editor, 3, "14:00") == "sE"
    assert _cell(editor, 1, "05:00") == "sE"           # Tuesday has passed
    index = editor.panels.indexOf(editor.energy_panel)
    assert editor.panels.tabText(index) == "Energy (2)"


def test_a_swap_carries_the_objectives_with_their_project(editor, store):
    con = db.connect(store["db"])
    review.ensure(con)
    review.add_objective(con, BlockKey("2026-10-15", "14:00", "C"), "Draft section 3")
    con.commit()
    con.close()
    editor.match_energy()
    con = db.connect(store["db"])
    moved = review.objectives(con, BlockKey("2026-10-15", "05:00", "C"))
    con.close()
    assert [o.text for o in moved] == ["Draft section 3"]


def test_the_profile_follows_the_focus_ratings(editor, store):
    con = db.connect(store["db"])
    review.ensure(con)
    pid = db.get_or_create_project(con, "B", "1002RNAediting", "safe")
    generative = con.execute("SELECT category_id FROM category WHERE name = 'generative'"
                             ).fetchone()[0]
    for day in ("2026-10-06", "2026-10-07", "2026-10-08"):
        con.execute("INSERT INTO plan_block(day, start_time, end_time, project_id,"
                    " category_id) VALUES (?, '14:00', '15:00', ?, ?)",
                    (day, pid, generative))
        review.save_review(con, BlockKey(day, "14:00", "B"), review.Review(focus=5))
    con.commit()
    con.close()
    changes = editor.energy_from_reviews()
    assert [(c.activity, c.hour, c.new) for c in changes] == [
        ("generative", 14, energy.HIGH)]
    assert editor.dialogs[-1].boxes[0].text() == (
        "Generative at 14:00 from low to high, mean focus 5.0 over 3 blocks")
    assert editor.energy_panel.level(14, "generative") == energy.HIGH
    assert json.loads(store["energy_profile"])["generative"][14] == energy.HIGH


def test_no_focus_ratings_say_so(editor, store):
    messages = []
    editor.logged.connect(messages.append)
    assert editor.energy_from_reviews() == []
    assert any("needs 3 rated blocks" in m for m in messages)


def test_energy_matching_with_nothing_to_fix(editor, store):
    flat = {a: [energy.HIGH] * 24 for a in energy.ACTIVITIES}
    flat["support"] = [energy.LOW] * 24
    flat["generative"] = [energy.MEDIUM] * 24
    editor.energy_panel.set_profile(flat)
    messages = []
    editor.logged.connect(messages.append)
    editor.match_energy()
    assert editor.dialogs == []
    assert any("Every block of the week fits" in m for m in messages)
