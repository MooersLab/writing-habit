"""Quick capture on the grasscatcher, and the stuck sign in the review panel."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit import db, review                               # noqa: E402
from writing_habit.project_lists import GRASSCATCHER               # noqa: E402
from writing_habit.review import BlockKey                          # noqa: E402

from test_gui_coach import (IN_BLOCK, _log, _panel, editor, store,  # noqa: E402,F401
                            use_model)


def _last_task(editor):
    entry = editor.table.lists.entries(GRASSCATCHER)[-1]
    return entry.code, entry.description


# -- quick capture ---------------------------------------------------------------------
def test_capture_files_the_task_with_its_project_and_priority(editor, store):
    before = len(editor.table.lists.entries(GRASSCATCHER))
    messages = []
    editor.logged.connect(messages.append)
    answer = editor.capture_task("remember to email the reviewer about figure 3 "
                                 "for 1006, priority A")
    assert len(editor.table.lists.entries(GRASSCATCHER)) == before + 1
    assert _last_task(editor) == ("A", "[#A] Email the reviewer about figure 3 for 1006")
    assert answer.source.startswith("plain")
    assert any(m.startswith("Captured A: [#A] Email the reviewer") and
               "project from its number 1006" in m for m in messages)
    assert editor.table.dirty
    assert editor.dialogs == []                        # no dialog interrupts a capture


def test_the_capture_box_and_its_shortcut(editor, store):
    panel = editor.list_panels[GRASSCATCHER]
    editor.show()
    editor.project_tabs.setCurrentIndex(0)
    editor.capture_shortcut.activated.emit()
    assert editor.project_tabs.currentWidget() is panel
    assert editor.focusWidget() is panel.capture_edit
    panel.capture_edit.setText("tidy the RNAediting figures")
    panel.capture_button.click()
    assert _last_task(editor) == ("B", "Tidy the RNAediting figures")
    assert panel.capture_edit.text() == ""


def test_a_thought_with_no_project_is_kept_without_a_code(editor, store):
    editor.capture_task("buy printer toner")
    assert _last_task(editor) == (None, "Buy printer toner")


def test_the_model_rewords_and_the_lookup_confirms(editor, store, monkeypatch):
    use_model(monkeypatch, store, {"code": "A", "task": "Email the reviewer about figure 3"})
    answer = editor.capture_task("remember to email the reviewer about figure 3 for 1006")
    assert answer.source == "local model tiny"
    assert _last_task(editor) == ("A", "Email the reviewer about figure 3")
    assert _log(store)[-1]["task"] == "capture"


def test_a_model_project_the_words_do_not_name_is_not_used(editor, store, monkeypatch):
    use_model(monkeypatch, store, {"code": "B", "task": "Email the reviewer about figure 3"})
    editor.capture_task("email the reviewer about figure 3 for 1006")
    assert _last_task(editor)[0] == "A"


def test_capture_during_a_block_is_plain_and_asks_nothing(editor, store, monkeypatch):
    use_model(monkeypatch, store, {"code": "B", "task": "anything"})
    editor.coach_guard.now = lambda: IN_BLOCK
    asked = []
    editor.coach_guard.confirm = lambda text: asked.append(text) or True
    answer = editor.capture_task("draft the abstract for 1006")
    assert answer.source.startswith("plain")
    assert asked == [] and _log(store) == []
    assert _last_task(editor) == ("A", "Draft the abstract for 1006")


# -- stuck projects --------------------------------------------------------------------
def _stuck_history(store):
    con = db.connect(store["db"])
    review.ensure(con)
    db.get_or_create_project(con, "A", "1006AIrxOpt", "safe")
    for day in ("2026-10-05", "2026-10-07"):
        key = BlockKey(day, "05:00", "A")
        review.mark(con, review.add_objective(con, key, "Draft aim 2"), False)
    con.commit()
    con.close()


def test_the_review_panel_shows_the_stuck_sign_and_fills_suggest(editor, store):
    _stuck_history(store)
    panel = _panel(editor)
    assert panel.stuck_label.isVisibleTo(panel)
    assert "“Draft aim 2” has gone unmet in 2 of the last 2 blocks" in panel.stuck_label.text()
    assert "Press Suggest" in panel.stuck_label.text()
    assert panel.objective_edit.text() == "Draft aim 2"


def test_suggest_tells_the_model_the_task_is_stuck(editor, store, monkeypatch):
    _stuck_history(store)
    use_model(monkeypatch, store, {"objectives": ["Outline aim 2 in five bullets",
                                                  "Draft the first aim 2 sentence"],
                                   "if_then": "If I stall, then I will write a bullet."})
    panel = _panel(editor)
    panel.suggest_objectives()
    facts = _log(store)[-1]["facts"]
    assert "Stuck: “Draft aim 2” has gone unmet" in facts
    assert "Break the task into smaller steps." in facts


def test_a_project_that_is_not_stuck_shows_no_sign(editor, store):
    panel = _panel(editor)
    assert not panel.stuck_label.isVisibleTo(panel)
    assert panel.objective_edit.text() == ""


def test_find_stuck_projects_reports_them(editor, store):
    _stuck_history(store)
    found = editor.find_stuck()
    assert [s.code for s in found] == ["A"]
    assert "Suggest breaks it into smaller objectives" in editor.dialogs[-1].answer.text


def test_find_stuck_with_nothing_stuck_says_so(editor, store):
    messages = []
    editor.logged.connect(messages.append)
    assert editor.find_stuck() == []
    assert any("No project shows a sign of being stuck" in m for m in messages)
