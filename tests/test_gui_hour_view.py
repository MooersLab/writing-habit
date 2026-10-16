"""The hour view of the Schedule tab, its range picker, the Breaks panel, and
Drop unused time rows.
"""

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit.gui.weekly_table import WeeklyTable              # noqa: E402

#: Monday holds a two-hour block, Tuesday a run with no break.
WEEK = (
    "#+TITLE: hour view\n"
    "|        Time | M  | Tu | W |\n"
    "|-------------+----+----+---|\n"
    "| 04:00-05:00 |    |    |   |\n"
    "| 04:00-06:00 | gA |    |   |\n"
    "| 08:00-10:00 |    | gA |   |\n"
    "| 09:30-10:00 |    |    |   |\n"
    "| 10:00-11:00 |    | eB |   |\n"
    "| 13:00-14:00 |    |    |   |\n"
    "|-------------+----+----+---|\n"
    "| A: one 2026-11-01 :safe: |  |  |  |\n"
    "| B: two 2026-12-01 :risky: @editing |  |  |  |\n"
)


@pytest.fixture()
def store():
    return {}


@pytest.fixture()
def editor(qtbot, tmp_path, monkeypatch, store):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    monkeypatch.setattr("writing_habit.gui.settings.get",
                        lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    path = tmp_path / "week.org"
    path.write_text(WEEK, encoding="utf-8")
    widget.open(str(path))
    return widget


def _display(editor, hour, column):
    from writing_habit.gui.qt import Qt
    return editor.hour_model.data(editor.hour_model.index(hour, column), Qt.DisplayRole)


def _background(editor, hour, column):
    from writing_habit.gui.qt import Qt
    brush = editor.hour_model.data(editor.hour_model.index(hour, column),
                                   Qt.BackgroundRole)
    return None if brush is None else brush.color().name()


# -- the toggle ----------------------------------------------------------------
def test_the_hour_view_has_24_rows_and_the_days(editor):
    editor.hour_button.setChecked(True)
    assert editor.hour_view_shown()
    assert editor.hour_model.rowCount() == 24
    assert editor.hour_model.columnCount() == 4
    assert _display(editor, 0, 0) == "00:00"
    assert _display(editor, 23, 0) == "23:00"


def test_the_toggle_switches_back_and_remembers(editor, store):
    editor.hour_button.setChecked(True)
    assert store["hour_view"] == "true"
    assert not editor.insert_above_button.isEnabled()
    assert not editor.delete_row_button.isEnabled()
    editor.hour_button.setChecked(False)
    assert not editor.hour_view_shown()
    assert store["hour_view"] == "false"


def test_a_table_opens_in_the_view_last_used(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    store = {"hour_view": "true"}
    monkeypatch.setattr("writing_habit.gui.settings.get",
                        lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    path = tmp_path / "week.org"
    path.write_text(WEEK, encoding="utf-8")
    widget.open(str(path))
    assert widget.hour_view_shown()


# -- what a cell shows ---------------------------------------------------------
def test_a_cell_lists_the_blocks_that_start_in_its_hour(editor):
    assert _display(editor, 4, 1) == "gA 04:00-06:00"
    assert _display(editor, 10, 2) == "eB 10:00-11:00"


def test_a_long_block_continues_into_the_next_hour(editor):
    assert _display(editor, 5, 1) == "↓ gA"
    assert _display(editor, 6, 1) == ""


def test_a_run_with_no_break_is_amber(editor):
    from writing_habit.gui.table_model import BREAK_COLOR
    assert _background(editor, 8, 2) == BREAK_COLOR
    assert _background(editor, 10, 2) == BREAK_COLOR
    assert _background(editor, 4, 1) != BREAK_COLOR


def test_the_breaks_panel_names_the_run(editor):
    assert editor.panels.tabText(2) == "Breaks (1)"
    text = editor.break_panel.toPlainText()
    assert "Tu  08:00-11:00  (3:00)" in text
    assert "A 08:00-10:00" in text and "B 10:00-11:00" in text


def test_the_row_view_tints_the_run_too(editor):
    from writing_habit.gui.qt import Qt
    from writing_habit.gui.table_model import BREAK_COLOR
    row = editor.table.find_block_row("08:00", "10:00")
    grid_row = editor.model._rows.index(row)
    brush = editor.model.data(editor.model.index(grid_row, 2), Qt.BackgroundRole)
    assert brush.color().name() == BREAK_COLOR


def test_a_clash_is_red_in_the_hour_view(editor):
    from writing_habit.gui.table_model import CONFLICT_COLOR
    editor.place_block(0, "05:00", "06:00", "gB")
    assert _background(editor, 5, 1) == CONFLICT_COLOR


# -- the picker ----------------------------------------------------------------
def _answer(editor, monkeypatch, start=None, length=None, code=None, letter=None,
            remove=None):
    """Make the picker answer by clicking a range or a Remove button."""
    def run(dialog):
        if code is not None:
            dialog.code_box.setCurrentIndex(dialog.code_box.findData(code))
        if letter is not None:
            dialog.activity_buttons[letter].setChecked(True)
        if remove is not None:
            dialog.remove_buttons[remove].click()
            return True
        dialog.range_buttons[(start, length)].click()
        return dialog.result() == 1
    monkeypatch.setattr(editor, "run_picker", run)


def test_one_click_places_a_block_on_a_new_row(editor, monkeypatch):
    rows = len(editor.table.block_rows)
    _answer(editor, monkeypatch, start=15, length=90, code="A")
    choice = editor.open_picker(editor.hour_model.index(9, 3))
    assert choice == ("09:15", "10:45", "gA")
    assert len(editor.table.block_rows) == rows + 1
    assert _display(editor, 9, 3) == "gA 09:15-10:45"
    assert editor.table.dirty


def test_an_existing_row_is_reused(editor, monkeypatch):
    rows = len(editor.table.block_rows)
    _answer(editor, monkeypatch, start=30, length=30, code="A")
    editor.open_picker(editor.hour_model.index(9, 3))
    assert len(editor.table.block_rows) == rows
    row = editor.table.find_block_row("09:30", "10:00")
    assert editor.table.cell(row, editor.table.column_for(2)) == "gA"


def test_the_activity_starts_at_the_legend_default(editor, monkeypatch):
    _answer(editor, monkeypatch, start=0, length=60, code="B")
    assert editor.open_picker(editor.hour_model.index(13, 1)) == (
        "13:00", "14:00", "eB")


def test_the_activity_buttons_override(editor, monkeypatch):
    _answer(editor, monkeypatch, start=0, length=60, code="B", letter="s")
    assert editor.open_picker(editor.hour_model.index(13, 1))[2] == "sB"


def test_the_last_range_becomes_the_default(editor, monkeypatch, store):
    _answer(editor, monkeypatch, start=45, length=75, code="A")
    editor.open_picker(editor.hour_model.index(14, 3))
    from writing_habit.gui.hour_view import HourPicker
    dialog = HourPicker(editor.table, 2, "W", 16)
    dialog.code_box.setCurrentIndex(dialog.code_box.findData("A"))
    assert dialog.default_range() == (45, 75)
    dialog.code_box.setCurrentIndex(dialog.code_box.findData("B"))
    assert dialog.default_range() is None


def test_ranges_past_midnight_are_disabled(editor):
    from writing_habit.gui.hour_view import HourPicker
    dialog = HourPicker(editor.table, 0, "M", 23)
    assert dialog.range_buttons[(0, 30)].isEnabled()
    assert not dialog.range_buttons[(0, 60)].isEnabled()
    assert not dialog.range_buttons[(45, 15)].isEnabled()


def test_remove_clears_the_cell_and_keeps_the_row(editor, monkeypatch):
    lines = len(editor.table.to_text().splitlines())
    _answer(editor, monkeypatch, remove=0)
    result = editor.open_picker(editor.hour_model.index(4, 1))
    assert result[0] == "remove"
    assert _display(editor, 4, 1) == ""
    assert len(editor.table.to_text().splitlines()) == lines
    assert editor.table.find_block_row("04:00", "06:00") is not None


def test_the_hour_column_opens_no_picker(editor, monkeypatch):
    monkeypatch.setattr(editor, "run_picker",
                        lambda dialog: pytest.fail("no picker expected"))
    assert editor.open_picker(editor.hour_model.index(9, 0)) is None


def test_a_cancelled_picker_changes_nothing(editor, monkeypatch):
    text = editor.table.to_text()
    monkeypatch.setattr(editor, "run_picker", lambda dialog: False)
    assert editor.open_picker(editor.hour_model.index(9, 1)) is None
    assert editor.table.to_text() == text


def test_a_saved_block_reads_back(editor, monkeypatch):
    _answer(editor, monkeypatch, start=15, length=90, code="A")
    editor.open_picker(editor.hour_model.index(9, 3))
    path = editor.save()
    reread = WeeklyTable.from_file(path)
    assert any(b.start == "09:15" and b.letter == "A" and b.offset == 2
               for b in reread.blocks())


# -- Drop unused time rows -----------------------------------------------------
def test_drop_unused_rows_asks_and_keeps_a_backup(editor, monkeypatch):
    asked = []
    monkeypatch.setattr(editor, "_confirm",
                        lambda title, text: asked.append(text) or True)
    code = editor.table.code()
    assert editor.drop_unused_rows() == 3
    assert "3 empty" in asked[0] and "printed sheets do not change" in asked[0]
    assert Path(editor.table.path + ".bak").read_text(encoding="utf-8") == WEEK
    assert editor.table.code() == code
    assert len(editor.table.block_rows) == 3
    assert editor.model.rowCount() == 3


def test_drop_unused_rows_does_nothing_when_declined(editor, monkeypatch):
    monkeypatch.setattr(editor, "_confirm", lambda title, text: False)
    text = editor.table.to_text()
    assert editor.drop_unused_rows() == 0
    assert editor.table.to_text() == text
    assert not Path(editor.table.path + ".bak").exists()
