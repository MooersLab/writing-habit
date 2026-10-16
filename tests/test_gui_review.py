"""The review panel in the hour picker, the Review dialog, the grasscatcher
list, and reviews that follow a shifted block."""

import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit import db, review                                  # noqa: E402
from writing_habit.review import BlockKey, Review                    # noqa: E402

WEEK = (
    "#+TITLE: review\n"
    "|        Time | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| 05:00-07:00 | gA |    |\n"
    "| 07:00-08:00 | eB |    |\n"
    "|-------------+----+----|\n"
    "| A: 1006AIrxOpt 2026-11-01 :safe: |  |  |\n"
    "| B: 1002RNAediting 2026-12-01 :safe: |  |  |\n"
    "\n"
    "#+NAME: grasscatcher\n"
    "| A: find three citations for rigor |\n"
    "| - tidy the bib file |\n"
)

MONDAY = dt.date(2026, 10, 12)
KEY_A = BlockKey("2026-10-12", "05:00", "A")


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
    qtbot.addWidget(widget)
    path = tmp_path / "Oct12.org"
    path.write_text(WEEK, encoding="utf-8")
    widget.open(str(path))
    widget.set_hour_view(True)
    return widget


def _con(store):
    return db.connect(store["db"])


def _picker(editor, hour=5, column=1):
    """Open the picker on a cell and hand back the dialog without showing it."""
    seen = {}

    def keep(dialog):
        seen["dialog"] = dialog
        return False

    editor.run_picker = keep
    editor.open_picker(editor.hour_model.index(hour, column))
    return seen["dialog"]


def test_the_week_comes_from_the_file_name(editor):
    assert editor.week_monday() == MONDAY


def test_the_picker_shows_the_panel_for_the_hours_blocks(editor):
    dialog = _picker(editor)
    panel = dialog.review_panel
    assert panel is not None and panel.ready()
    assert panel.block_box.count() == 1
    assert panel.block_box.itemText(0).startswith("A 05:00-07:00")
    # An hour a long block runs into reviews that block too.
    assert _picker(editor, hour=6).review_panel.block().letter == "A"
    # An empty hour has no panel, so the picker stays narrow.
    assert _picker(editor, hour=12).review_panel is None


def test_objectives_save_at_once_and_drive_the_counts(editor, store):
    panel = _picker(editor).review_panel
    panel.objective_edit.setText("Draft aim 2")
    panel.add_objective()
    panel.add_objective("Write the rigor paragraph")
    from writing_habit.gui.qt import Qt
    panel.objective_list.item(0).setCheckState(Qt.Checked)
    assert (panel.committed_spin.value(), panel.met_spin.value()) == (2, 1)
    assert not panel.committed_spin.isEnabled()
    con = _con(store)
    assert review.counts(con, KEY_A) == (2, 1)
    con.close()


def test_more_than_three_objectives_warns(editor):
    panel = _picker(editor).review_panel
    for text in ("one", "two", "three", "four"):
        panel.add_objective(text)
    assert panel.limit_label.isVisibleTo(panel)


def test_save_review_and_reload(editor, store):
    panel = _picker(editor).review_panel
    panel.focus_spin.setValue(4)
    panel.interruption_spin.setValue(2)
    panel.next_edit.setText("Start at the second paragraph")
    stored = panel.save()
    assert stored.focus == 4 and stored.interruptions == 2
    again = _picker(editor).review_panel
    assert again.focus_spin.value() == 4
    assert again.next_edit.text() == "Start at the second paragraph"


def test_closing_the_picker_saves_a_changed_review(editor, store):
    dialog = _picker(editor)
    dialog.review_panel.focus_spin.setValue(3)
    dialog.reject()
    con = _con(store)
    assert review.review(con, KEY_A).focus == 3
    con.close()


def test_a_bad_count_is_refused_in_the_status_line(editor):
    panel = _picker(editor).review_panel
    panel.committed_spin.setValue(1)
    panel.met_spin.setValue(3)
    assert panel.save() is None
    assert "more objectives met" in panel.status.text()


def test_the_last_next_step_greets_the_next_block(editor, store):
    con = _con(store)
    review.save_review(con, BlockKey("2026-10-09", "05:00", "A"),
                       Review(next_step="Open the results draft"))
    con.close()
    panel = _picker(editor).review_panel
    assert "Open the results draft" in panel.last_label.text()


def test_no_database_disables_the_panel_with_a_reason(editor, store):
    store["db"] = ""
    panel = _picker(editor).review_panel
    assert not panel.ready()
    assert "database" in panel.problem.text()


# -- the grasscatcher ---------------------------------------------------------------
def test_the_grasscatcher_has_its_own_tab_and_buttons(editor):
    from writing_habit.project_lists import GRASSCATCHER
    panel = editor.list_panels[GRASSCATCHER]
    assert panel.commit_button is not None
    assert panel.model.rowCount() == 2
    assert panel.model.headerData(1, 1) == "Task"


def test_commit_from_the_grasscatcher_tab_to_the_selected_block(editor, store):
    from writing_habit.project_lists import GRASSCATCHER
    editor.hour_view.setCurrentIndex(editor.hour_model.index(5, 1))
    objective_id = editor.commit_grasscatcher(0)
    assert objective_id is not None
    assert [e.description for e in editor.table.lists.entries(GRASSCATCHER)] == [
        "tidy the bib file"]
    assert editor.table.dirty
    con = _con(store)
    items = review.objectives(con, KEY_A)
    con.close()
    assert [(o.text, o.origin) for o in items] == [
        ("find three citations for rigor", "grasscatcher")]


def test_commit_needs_a_selected_block(editor):
    editor.hour_view.setCurrentIndex(editor.hour_model.index(12, 1))
    assert editor.commit_grasscatcher(0) is None


def test_the_panel_lists_the_blocks_project_tasks_first_and_parks(editor, store):
    from writing_habit.project_lists import GRASSCATCHER
    panel = _picker(editor).review_panel
    assert panel.catch_box.itemText(0) == "A: find three citations for rigor"
    panel.commit_from_grasscatcher()
    assert panel.objective_list.count() == 1
    panel.objective_list.setCurrentRow(0)
    panel.park_objective()
    assert panel.objective_list.count() == 0
    entries = editor.table.lists.entries(GRASSCATCHER)
    assert ("A", "find three citations for rigor") in [
        (e.code, e.description) for e in entries]


# -- the Review dialog and the debrief ---------------------------------------------
def test_the_review_button_opens_the_selected_block(editor):
    editor.hour_view.setCurrentIndex(editor.hour_model.index(7, 1))
    assert editor.review_button.isEnabled()
    editor.run_review = lambda dialog: None
    dialog = editor.open_review()
    assert dialog.panel.block().letter == "B"


def test_the_debrief_without_a_model_is_a_local_summary(editor, store):
    panel = _picker(editor).review_panel
    panel.add_objective("Draft aim 2")
    from writing_habit.gui.qt import Qt
    panel.objective_list.item(0).setCheckState(Qt.Checked)
    panel.model_box.setChecked(False)
    text = panel.run_debrief()
    assert "Draft aim 2" in text
    assert "without a model" in panel.source_label.text()
    con = _con(store)
    assert review.review(con, KEY_A).debrief == text
    con.close()


def test_the_debrief_asks_the_model_when_it_is_on(editor, store):
    panel = _picker(editor).review_panel
    calls = []

    def fake(facts, use_model, model, url):
        calls.append((facts.project, use_model, model, url))
        return "Good block.", f"local model {model}"

    panel.ask = fake
    panel.model_box.setChecked(True)
    assert store["ai_debrief"] == "true"
    assert panel.run_debrief() == "Good block."
    assert calls == [("1006AIrxOpt", True, "tiny", "http://localhost:11434")]


# -- reviews follow their block ----------------------------------------------------
def test_a_shift_carries_the_objectives_and_review_along(editor, store):
    con = _con(store)
    review.add_objective(con, KEY_A, "Draft aim 2")
    review.save_review(con, KEY_A, Review(focus=5))
    con.close()
    editor.hour_view.setCurrentIndex(editor.hour_model.index(5, 1))
    editor.shift_selected(60)            # A to 06:00, B pushed to 08:00
    con = _con(store)
    moved = BlockKey("2026-10-12", "06:00", "A")
    assert [o.text for o in review.objectives(con, moved)] == ["Draft aim 2"]
    assert review.review(con, moved).focus == 5
    assert review.objectives(con, KEY_A) == []
    con.close()


def test_a_canonical_name_finds_its_week_in_the_database(editor, store, tmp_path):
    path = tmp_path / "gAeB-gA.org"
    path.write_text(WEEK, encoding="utf-8")
    con = _con(store)
    con.execute("INSERT INTO plan_week(week_start, schedule_code, table_path)"
                " VALUES ('2026-10-19', 'gAeB-gA', ?)", (str(path),))
    con.commit()
    con.close()
    editor.open(str(path))
    assert editor.week_monday() == dt.date(2026, 10, 19)
