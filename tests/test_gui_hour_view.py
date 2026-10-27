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
    assert _display(editor, 5, 1) == "↓"          # only the arrow, no code
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


# -- half-transparent bars within an hour -------------------------------------
BARS = (
    "#+TITLE: bars\n"
    "|        Time | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| 05:00-05:30 | gA | gA |\n"
    "| 05:15-06:00 |    | eB |\n"
    "| 05:30-05:45 | eB |    |\n"
    "|-------------+----+----|\n"
    "| A: one :safe: |  |  |\n"
    "| B: two :safe: |  |  |\n"
)


def test_each_block_fills_only_its_minutes_of_the_hour(qtbot, tmp_path, monkeypatch, store):
    from writing_habit.gui.hour_view import SEGMENTS_ROLE
    from writing_habit.gui.table_model import ACTIVITY_COLOR
    editor_ = _open(qtbot, tmp_path, monkeypatch, store, BARS)
    model = editor_.hour_model
    monday = model.data(model.index(5, 1), SEGMENTS_ROLE)
    # Monday: 05:00-05:30 then 05:30-05:45 touch, and 05:45-06:00 is a break.
    assert [(s.top, s.bottom, s.lane) for s in monday] == [(0.0, 0.5, 0), (0.5, 0.75, 0)]
    assert [s.color for s in monday] == [ACTIVITY_COLOR["generative"],
                                         ACTIVITY_COLOR["editing"]]
    # Tuesday: 05:15-06:00 overlaps 05:00-05:30, so it takes the next lane.
    tuesday = model.data(model.index(5, 2), SEGMENTS_ROLE)
    assert [(s.top, s.bottom, s.lane) for s in tuesday] == [(0.0, 0.5, 0), (0.25, 1.0, 1)]
    assert model.data(model.index(7, 1), SEGMENTS_ROLE) == []


def test_a_long_block_fills_each_hour_it_runs_into(editor):
    from writing_habit.gui.hour_view import SEGMENTS_ROLE
    model = editor.hour_model
    # Tuesday 08:00-10:00, then 10:00-11:00: hour 9 is full, hour 10 holds B only.
    assert [(s.top, s.bottom) for s in model.data(model.index(9, 2), SEGMENTS_ROLE)] == [(0.0, 1.0)]
    assert [(s.top, s.bottom) for s in model.data(model.index(10, 2), SEGMENTS_ROLE)] == [(0.0, 1.0)]


def test_the_bars_are_painted_half_transparent(qtbot, tmp_path, monkeypatch, store):
    from writing_habit.gui.qt import QtGui
    editor_ = _open(qtbot, tmp_path, monkeypatch, store, BARS)
    editor_.set_hour_view(True)
    editor_.resize(900, 700)
    editor_.show()
    qtbot.waitExposed(editor_)
    view = editor_.hour_view
    view.setRowHeight(5, 80)
    rect = view.visualRect(editor_.hour_model.index(5, 1))
    image = view.viewport().grab().toImage()
    x = rect.left() + 3
    fill = QtGui.QColor(image.pixel(x, rect.top() + 10))          # inside 05:00-05:30
    gap = QtGui.QColor(image.pixel(x, rect.top() + rect.height() - 6))  # the 05:45 break
    assert gap.name() == "#ffffff"
    assert fill.name() not in ("#ffffff", "#dcebfa")              # blended, not solid


def _open(qtbot, tmp_path, monkeypatch, store, text):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    monkeypatch.setattr("writing_habit.gui.settings.get", lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    path = tmp_path / "bars.org"
    path.write_text(text, encoding="utf-8")
    widget.open(str(path))
    return widget


# -- resizing a block by dragging an edge -------------------------------------------
DRAG = (
    "#+TITLE: drag\n"
    "|        Time | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| 05:00-05:30 | gA |    |\n"
    "| 07:00-08:00 | eB | gA |\n"
    "|-------------+----+----|\n"
    "| A: one :safe: |  |  |\n"
    "| B: two :safe: |  |  |\n"
)


def test_plan_resize_checks_the_new_range(tmp_path):
    path = tmp_path / "drag.org"
    path.write_text(DRAG, encoding="utf-8")
    table = WeeklyTable.from_file(str(path))
    a = next(b for b in table.blocks() if b.letter == "A" and b.offset == 0)
    (row, column), moves = table.resize_block(a.row, a.column, "05:00", "06:15")
    assert table.rows[row].parsed == ("05:00", "06:15") and table.cell(row, column) == "gA"
    for start, end, why in [("05:00", "05:10", "at least 15"),
                            ("05:00", "07:15", "at most 120"),
                            ("06:15", "06:00", "at least 15")]:
        with pytest.raises(ValueError, match=why):
            table.plan_resize(row, column, start, end)
    # Growing into the next block pushes it down when asked.
    (row, column), moves = table.resize_block(row, column, "05:30", "07:30", push=True)
    assert [(m[0].letter, m[1], m[2]) for m in moves] == [("A", "05:30", "07:30"),
                                                          ("B", "07:30", "08:30")]


def _move(viewport, x, y):
    """Send a mouse move with the left button down, as a drag does."""
    from writing_habit.gui.qt import QtCore, QtGui, QtWidgets, Qt
    event = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, QtCore.QPointF(x, y),
                              Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(viewport, event)


def _edge_y(editor_, hour, column, fraction):
    rect = editor_.hour_view.visualRect(editor_.hour_model.index(hour, column))
    return rect, rect.top() + round(fraction * rect.height())


def test_dragging_the_bottom_edge_lengthens_the_block(qtbot, tmp_path, monkeypatch, store):
    from writing_habit.gui.qt import QtCore, Qt
    editor_ = _open(qtbot, tmp_path, monkeypatch, store, DRAG)
    editor_.push_box.setChecked(False)
    editor_.set_hour_view(True)
    editor_.resize(900, 900)
    editor_.show()
    qtbot.waitExposed(editor_)
    viewport = editor_.hour_view.viewport()
    rect, y = _edge_y(editor_, 5, 1, 0.5)          # the 05:30 end of gA
    x = rect.center().x()
    assert editor_.edge_dragger.edge_at(QtCore.QPoint(x, y))[1] == "bottom"
    qtbot.mousePress(viewport, Qt.LeftButton, pos=QtCore.QPoint(x, y))
    target, ty = _edge_y(editor_, 6, 1, 0.25)       # 06:15
    _move(viewport, x, ty)
    assert editor_.hour_model.preview[1:] == ("05:00", "06:15", 0)
    qtbot.mouseRelease(viewport, Qt.LeftButton, pos=QtCore.QPoint(x, ty))
    a = next(b for b in editor_.table.blocks() if b.letter == "A" and b.offset == 0)
    assert (a.start, a.end) == ("05:00", "06:15")
    assert editor_.hour_model.preview is None
    assert editor_.table.dirty


def test_dragging_the_top_edge_moves_the_start_and_escape_cancels(qtbot, tmp_path,
                                                                  monkeypatch, store):
    from writing_habit.gui.qt import QtCore, Qt
    editor_ = _open(qtbot, tmp_path, monkeypatch, store, DRAG)
    editor_.set_hour_view(True)
    editor_.resize(900, 900)
    editor_.show()
    qtbot.waitExposed(editor_)
    viewport = editor_.hour_view.viewport()
    rect, y = _edge_y(editor_, 7, 2, 0.0)          # the 07:00 start of Tuesday's gA
    x = rect.center().x()
    qtbot.mousePress(viewport, Qt.LeftButton, pos=QtCore.QPoint(x, y + 1))
    _r, ty = _edge_y(editor_, 6, 2, 0.5)            # 06:30
    _move(viewport, x, ty)
    qtbot.keyClick(editor_.hour_view, Qt.Key_Escape)
    assert editor_.hour_model.preview is None
    qtbot.mouseRelease(viewport, Qt.LeftButton, pos=QtCore.QPoint(x, ty))
    tue = next(b for b in editor_.table.blocks() if b.offset == 1)
    assert (tue.start, tue.end) == ("07:00", "08:00")
    qtbot.mousePress(viewport, Qt.LeftButton, pos=QtCore.QPoint(x, y + 1))
    _move(viewport, x, ty)
    qtbot.mouseRelease(viewport, Qt.LeftButton, pos=QtCore.QPoint(x, ty))
    tue = next(b for b in editor_.table.blocks() if b.offset == 1)
    assert (tue.start, tue.end) == ("06:30", "08:00")


def test_the_middle_of_a_block_is_not_an_edge(qtbot, tmp_path, monkeypatch, store):
    from writing_habit.gui.qt import QtCore
    editor_ = _open(qtbot, tmp_path, monkeypatch, store, DRAG)
    editor_.set_hour_view(True)
    editor_.resize(900, 900)
    editor_.show()
    qtbot.waitExposed(editor_)
    rect, y = _edge_y(editor_, 7, 1, 0.5)
    assert editor_.edge_dragger.edge_at(QtCore.QPoint(rect.center().x(), y)) is None


def _shown(qtbot, tmp_path, monkeypatch, store, text=DRAG):
    editor_ = _open(qtbot, tmp_path, monkeypatch, store, text)
    editor_.push_box.setChecked(False)
    editor_.set_hour_view(True)
    editor_.resize(900, 900)
    editor_.show()
    qtbot.waitExposed(editor_)
    return editor_


def test_dragging_the_middle_moves_the_block_later(qtbot, tmp_path, monkeypatch, store):
    from writing_habit.gui.qt import QtCore, Qt
    editor_ = _shown(qtbot, tmp_path, monkeypatch, store)
    viewport = editor_.hour_view.viewport()
    rect, y = _edge_y(editor_, 5, 1, 0.25)          # inside 05:00-05:30, not an edge
    x = rect.center().x()
    assert editor_.edge_dragger.grab_at(QtCore.QPoint(x, y))[1] == "move"
    qtbot.mousePress(viewport, Qt.LeftButton, pos=QtCore.QPoint(x, y))
    _r, ty = _edge_y(editor_, 6, 1, 0.25)           # one hour lower
    _move(viewport, x, ty)
    assert editor_.hour_model.preview[1:] == ("06:00", "06:30", 0)
    qtbot.mouseRelease(viewport, Qt.LeftButton, pos=QtCore.QPoint(x, ty))
    a = next(b for b in editor_.table.blocks() if b.letter == "A" and b.offset == 0)
    assert (a.start, a.end) == ("06:00", "06:30")


def test_dragging_the_middle_across_columns_moves_it_to_another_day(qtbot, tmp_path,
                                                                    monkeypatch, store):
    from writing_habit.gui.qt import QtCore, Qt
    editor_ = _shown(qtbot, tmp_path, monkeypatch, store)
    viewport = editor_.hour_view.viewport()
    rect, y = _edge_y(editor_, 5, 1, 0.25)
    tuesday = editor_.hour_view.visualRect(editor_.hour_model.index(5, 2))
    qtbot.mousePress(viewport, Qt.LeftButton, pos=QtCore.QPoint(rect.center().x(), y))
    _move(viewport, tuesday.center().x(), y)
    qtbot.mouseRelease(viewport, Qt.LeftButton, pos=QtCore.QPoint(tuesday.center().x(), y))
    blocks = [(b.letter, b.offset, b.start, b.end) for b in editor_.table.blocks()]
    assert ("A", 1, "05:00", "05:30") in blocks
    assert ("A", 0, "05:00", "05:30") not in blocks


def test_a_move_onto_a_held_slot_is_refused(qtbot, tmp_path, monkeypatch, store):
    editor_ = _shown(qtbot, tmp_path, monkeypatch, store)
    messages = []
    editor_.logged.connect(messages.append)
    b = next(b for b in editor_.table.blocks() if b.letter == "B")
    assert editor_.drag_block(b, "07:00", "08:00", 1) is None
    assert any("already holds" in m for m in messages)
    assert next(x for x in editor_.table.blocks() if x.letter == "B").offset == 0


def test_a_click_on_the_middle_only_selects(qtbot, tmp_path, monkeypatch, store):
    from writing_habit.gui.qt import QtCore, Qt
    editor_ = _shown(qtbot, tmp_path, monkeypatch, store)
    viewport = editor_.hour_view.viewport()
    rect, y = _edge_y(editor_, 7, 2, 0.5)
    before = editor_.table.to_text()
    qtbot.mouseClick(viewport, Qt.LeftButton, pos=QtCore.QPoint(rect.center().x(), y))
    assert editor_.table.to_text() == before
    assert editor_.hour_view.currentIndex().row() == 7
    assert editor_.hour_view.currentIndex().column() == 2
