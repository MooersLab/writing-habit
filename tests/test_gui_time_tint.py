"""Selecting a Time cell tints yellow the rows whose times do not overlap it.

The rule under test is the scheduler's: half-open intervals, so blocks that
only touch are clear of each other, and a block past midnight wraps.
"""

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit.gui.weekly_table import WeeklyTable          # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "my-week.org"

DAY = (
    "| Time        | M |\n"
    "|-------------+---|\n"
    "| Generative: |   |\n"
    "| 04:00-05:30 | A |\n"
    "| 05:30-07:00 | A |\n"
    "| Rewriting:  |   |\n"
    "| 05:00-06:00 | B |\n"
    "| 04:00-05:30 |   |\n"
    "| Supporting: |   |\n"
    "| 23:00-01:00 | E |\n"
    "| 00:30-02:00 | E |\n"
    "| 13:00-14:00 | E |\n"
)


@pytest.fixture()
def day():
    return WeeklyTable(DAY)


def _row(table, text):
    return next(i for i in table.block_rows
                if "-".join(table.rows[i].parsed) == text)


def _times(table, rows):
    return sorted("-".join(table.rows[i].parsed) for i in rows)


def test_touching_blocks_are_clear(day):
    clear = _times(day, day.rows_clear_of(_row(day, "04:00-05:30")))
    assert "05:30-07:00" in clear
    assert "05:00-06:00" not in clear


def test_an_identical_range_overlaps(day):
    first = day.block_rows[0]
    assert _row(day, "04:00-05:30") == first
    twin = [i for i in day.block_rows if i != first
            and day.rows[i].parsed == ("04:00", "05:30")][0]
    assert twin not in day.rows_clear_of(first)


def test_the_selected_row_is_left_out(day):
    anchor = _row(day, "13:00-14:00")
    assert anchor not in day.rows_clear_of(anchor)


def test_an_overnight_block_wraps(day):
    clear = _times(day, day.rows_clear_of(_row(day, "23:00-01:00")))
    assert "13:00-14:00" in clear
    # 00:30-02:00 is compared on the same clock, as the scheduler does, so the
    # early-morning tail of the overnight block is not counted against it.
    assert "00:30-02:00" in clear


def test_clear_rows_cross_sections(day):
    clear = _times(day, day.rows_clear_of(_row(day, "05:00-06:00")))
    assert clear == ["00:30-02:00", "13:00-14:00", "23:00-01:00"]


def test_a_section_row_has_no_time():
    table = WeeklyTable(DAY)
    section = next(i for i, r in enumerate(table.rows) if r.kind == "section")
    with pytest.raises(ValueError):
        table.rows_clear_of(section)


# -- the widget ----------------------------------------------------------------
@pytest.fixture()
def editor(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    store = {}
    monkeypatch.setattr("writing_habit.gui.settings.get",
                        lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    path = tmp_path / "day.org"
    path.write_text(DAY)
    widget.open(str(path))
    return widget


def _background(editor, grid_row, column=0):
    from writing_habit.gui.qt import Qt
    brush = editor.model.data(editor.model.index(grid_row, column), Qt.BackgroundRole)
    return brush.color().name() if brush is not None else None


def _grid_row(editor, text):
    return editor.model._rows.index(_row(editor.table, text))


def _select(editor, grid_row, column=0):
    editor.view.setCurrentIndex(editor.model.index(grid_row, column))


def test_selecting_a_time_tints_the_clear_times_yellow(editor):
    from writing_habit.gui.table_model import CLEAR_COLOR
    _select(editor, _grid_row(editor, "05:00-06:00"))
    tinted = {editor.model.data(editor.model.index(r, 0))
              for r in editor.model.clear_of_selection()}
    assert tinted == {"00:30-02:00", "13:00-14:00", "23:00-01:00"}
    assert _background(editor, _grid_row(editor, "13:00-14:00")) == CLEAR_COLOR
    assert _background(editor, _grid_row(editor, "05:30-07:00")) is None


def test_the_whole_row_is_tinted(editor):
    from writing_habit.gui.table_model import CLEAR_COLOR
    _select(editor, _grid_row(editor, "05:00-06:00"))
    row = _grid_row(editor, "13:00-14:00")
    for column in range(editor.model.columnCount()):
        assert _background(editor, row, column) == CLEAR_COLOR
    overlapping = _grid_row(editor, "05:30-07:00")
    for column in range(editor.model.columnCount()):
        assert _background(editor, overlapping, column) != CLEAR_COLOR


def test_a_clash_cell_stays_red_inside_a_yellow_row(editor):
    from writing_habit.gui.table_model import CLEAR_COLOR, CONFLICT_COLOR
    # 04:00-05:30 and 05:00-06:00 clash on Monday; 13:00-14:00 is clear of both.
    _select(editor, _grid_row(editor, "13:00-14:00"))
    row = _grid_row(editor, "04:00-05:30")
    assert _background(editor, row, 0) == CLEAR_COLOR
    assert _background(editor, row, 1) == CONFLICT_COLOR


def test_a_day_cell_selection_clears_the_tint(editor):
    _select(editor, _grid_row(editor, "05:00-06:00"))
    assert editor.model.clear_of_selection()
    _select(editor, _grid_row(editor, "05:00-06:00"), column=1)
    assert editor.model.clear_of_selection() == []


def test_a_section_row_selection_clears_the_tint(editor):
    _select(editor, _grid_row(editor, "05:00-06:00"))
    section = next(r for r in range(editor.model.rowCount())
                   if editor.model.is_section(r))
    _select(editor, section)
    assert editor.model.clear_of_selection() == []


def test_the_tint_follows_an_inserted_row(editor):
    anchor = _grid_row(editor, "05:00-06:00")
    _select(editor, anchor, column=1)
    editor.insert_row(above=False, times="15:00-16:00")
    _select(editor, _grid_row(editor, "05:00-06:00"))
    tinted = {editor.model.data(editor.model.index(r, 0))
              for r in editor.model.clear_of_selection()}
    assert "15:00-16:00" in tinted


def test_opening_another_table_clears_the_tint(editor):
    _select(editor, _grid_row(editor, "05:00-06:00"))
    editor.open(str(EXAMPLE))
    assert editor.model.clear_of_selection() == []
