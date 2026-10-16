"""The shift buttons of the Schedule tab, in the hour view and the row view."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

WEEK = (
    "#+TITLE: shift\n"
    "|        Time | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| 04:00-05:00 | gA |    |\n"
    "| 05:00-06:00 | eB |    |\n"
    "| 08:00-09:00 |    | gA |\n"
    "|-------------+----+----|\n"
    "| A: one 2026-11-01 :safe: |  |  |\n"
    "| B: two 2026-12-01 :risky: |  |  |\n"
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


def _monday(editor):
    table = editor.table
    return sorted((b.start, b.end, table.cell(b.row, b.column))
                  for b in table.blocks() if b.offset == 0)


def test_the_buttons_wait_for_a_selected_block(editor):
    editor.set_hour_view(True)
    editor.hour_view.setCurrentIndex(editor.hour_model.index(12, 1))
    assert not any(b.isEnabled() for b in editor.shift_buttons.values())
    editor.hour_view.setCurrentIndex(editor.hour_model.index(4, 1))
    assert all(b.isEnabled() for b in editor.shift_buttons.values())


def test_later_one_hour_in_the_hour_view_pushes_and_follows(editor):
    editor.set_hour_view(True)
    editor.hour_view.setCurrentIndex(editor.hour_model.index(4, 1))
    editor.shift_buttons[60].click()
    assert _monday(editor) == [("05:00", "06:00", "gA"), ("06:00", "07:00", "eB")]
    # The selection followed the block to the 05:00 hour.
    assert editor.hour_view.currentIndex().row() == 5
    assert editor.table.dirty


def test_the_push_box_off_leaves_a_clash(editor, store):
    editor.set_hour_view(True)
    editor.push_box.setChecked(False)
    assert store["push_blocks"] == "false"
    editor.hour_view.setCurrentIndex(editor.hour_model.index(4, 1))
    editor.shift_selected(30)
    assert ("05:00", "06:00", "eB") in _monday(editor)
    assert editor.table.conflicting_cells()


def test_a_continuation_hour_selects_the_long_block(editor):
    editor.set_hour_view(True)
    editor.hour_view.setCurrentIndex(editor.hour_model.index(4, 1))
    editor.shift_selected(15)            # 04:15-05:15 now runs into 05:00
    editor.hour_view.setCurrentIndex(editor.hour_model.index(5, 1))
    block = editor.selected_block()
    assert block is not None


def test_the_row_view_shifts_the_cell_under_the_cursor(editor):
    editor.set_hour_view(False)
    table = editor.table
    doc_row = table.find_block_row("08:00", "09:00")
    grid_row = editor.model._rows.index(doc_row)
    editor.view.setCurrentIndex(editor.model.index(grid_row, 2))
    moves = editor.shift_selected(-15)
    assert moves is not None
    tuesday = [(b.start, b.end) for b in table.blocks() if b.offset == 1]
    assert tuesday == [("07:45", "08:45")]


def test_a_refused_shift_says_why_and_changes_nothing(editor, qtbot):
    editor.set_hour_view(True)
    editor.hour_view.setCurrentIndex(editor.hour_model.index(4, 1))
    before = editor.table.to_text()
    messages = []
    editor.logged.connect(messages.append)
    assert editor.shift_selected(-6 * 60) is None
    assert editor.table.to_text() == before
    assert any("Cannot shift" in m for m in messages)


def test_the_picker_pushes_when_its_box_is_checked(editor):
    editor.set_hour_view(True)

    def answer(dialog):
        dialog.push_box.setChecked(True)
        dialog.choose("03:00", "05:00")
        return True

    editor.run_picker = answer
    editor.open_picker(editor.hour_model.index(3, 1))
    assert _monday(editor)[:3] == [("03:00", "05:00", "gA"),
                                   ("05:00", "06:00", "gA"),
                                   ("06:00", "07:00", "eB")]
