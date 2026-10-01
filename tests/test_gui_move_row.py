"""Shifting a time-block row up or down in the Schedule tab.

The document tests need no Qt. They check that a move reorders lines without
rewriting any, that a block crossing a section header changes section, and that
the scheduler reads the moved file the same way. The widget tests check the two
buttons, their enabled state at the edges of the grid, the keyboard shortcuts,
and that the selection follows the moved row.
"""

import os
import shutil
from collections import Counter
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_schedule import parse_text                          # noqa: E402

from writing_habit.gui.weekly_table import (BLOCK, SECTION,      # noqa: E402
                                            WeeklyTable)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "my-week.org"
TEMPLATES = sorted((ROOT / "templates").glob("*.org"))


@pytest.fixture()
def table():
    return WeeklyTable.from_file(str(EXAMPLE))


def _sections(table):
    return [i for i, row in enumerate(table.rows) if row.kind == SECTION]


def _times(table):
    return [table.rows[i].parsed for i in table.block_rows]


# -- the document --------------------------------------------------------------
def test_moving_down_inside_a_section_swaps_two_lines(table):
    first, second = table.block_rows[:2]
    before = table.to_text().splitlines()
    at = table.move_block(first, up=False)
    after = table.to_text().splitlines()
    assert at == second
    assert table.rows[first].parsed == ("05:45", "07:15")
    assert table.rows[second].parsed == ("04:00", "05:30")
    changed = [n for n, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(changed) == 2
    assert table.dirty is True


def test_moving_up_undoes_moving_down(table):
    text = table.to_text()
    at = table.move_block(table.block_rows[0], up=False)
    table.move_block(at, up=True)
    assert table.to_text() == text


def test_a_move_keeps_every_line_byte_for_byte(table):
    """A move reorders lines and never rewrites one."""
    before = Counter(table.to_text().splitlines())
    table.move_block(table.block_rows[1], up=False)
    assert Counter(table.to_text().splitlines()) == before


def test_moving_down_past_a_header_joins_the_section_below(table):
    last_generative = table.block_rows[1]
    rewriting = _sections(table)[1]
    at = table.move_block(last_generative, up=False)
    assert at == rewriting
    assert table.rows[at].section == "Rewriting"
    assert table.rows[at - 1].kind == SECTION
    assert table.rows[at - 1].parsed == "Rewriting"


def test_moving_up_past_a_header_joins_the_section_above(table):
    rewriting = _sections(table)[1]
    first_rewriting = rewriting + 1
    at = table.move_block(first_rewriting, up=True)
    assert at == rewriting
    assert table.rows[at].section == "Generative"
    assert table.rows[at + 1].kind == SECTION


def test_the_moved_block_counts_toward_its_new_activity(table):
    before = table.totals()["category"]
    table.move_block(table.block_rows[1], up=False)
    after = table.totals()["category"]
    moved = 90 * 6                                  # 05:45-07:15 on six days
    assert after["generative"] == before["generative"] - moved
    assert after["editing"] == before["editing"] + moved


def test_the_scheduler_reads_the_moved_file(table):
    table.move_block(table.block_rows[1], up=False)
    text = table.to_text()
    reread = WeeklyTable(text)
    assert [r.kind for r in reread.rows] == [r.kind for r in table.rows]
    assert [r.section for r in reread.rows if r.kind == BLOCK] == \
        [r.section for r in table.rows if r.kind == BLOCK]
    parse_text(text)                                  # the scheduler accepts it


def test_nothing_moves_above_the_first_section(table):
    first = table.block_rows[0]
    assert not table.can_move(first, up=True)
    before = table.to_text()
    with pytest.raises(ValueError, match="top"):
        table.move_block(first, up=True)
    assert table.to_text() == before
    assert table.dirty is False


def test_nothing_moves_below_the_last_block(table):
    last = table.block_rows[-1]
    assert not table.can_move(last, up=False)
    with pytest.raises(ValueError, match="bottom"):
        table.move_block(last, up=False)


def test_a_section_or_legend_row_does_not_move(table):
    assert not table.can_move(_sections(table)[1], up=True)
    assert not table.can_move(table.legend_rows()[0], up=False)
    with pytest.raises(ValueError, match="time-block"):
        table.move_block(_sections(table)[1], up=False)


def test_a_table_without_sections_moves_freely():
    table = WeeklyTable("| Time | M |\n|------+---|\n"
                        "| 09:00-10:00 | A |\n| 10:00-11:00 | B |\n")
    first, second = table.block_rows
    assert table.can_move(second, up=True)
    at = table.move_block(second, up=True)
    assert at == first
    assert _times(table) == [("10:00", "11:00"), ("09:00", "10:00")]


def test_the_cells_travel_with_the_row(table):
    first = table.block_rows[0]
    cells = list(table.rows[first].cells)
    at = table.move_block(first, up=False)
    assert table.rows[at].cells == cells
    assert {b.letter for b in table.blocks() if b.row == at} == {"A", "B", "W"}


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_every_shipped_table_moves_a_row_and_back(path):
    table = WeeklyTable.from_file(str(path))
    text = table.to_text()
    movable = [i for i in table.block_rows if table.can_move(i, up=False)]
    if not movable:
        pytest.skip("no block can move down in this table")
    at = table.move_block(movable[0], up=False)
    parse_text(table.to_text())
    table.move_block(at, up=True)
    assert table.to_text() == text


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
    copy = tmp_path / "my-week.org"
    shutil.copy(EXAMPLE, copy)
    widget.open(str(copy))
    return widget


def _select(editor, document_row, column=1):
    grid_row = editor.model._rows.index(document_row)
    editor.view.setCurrentIndex(editor.model.index(grid_row, column))


def _current_document_row(editor):
    return editor.model.document_row(editor.view.currentIndex().row())


def test_the_move_buttons_wait_for_a_selection(editor):
    assert not editor.move_up_button.isEnabled()
    assert not editor.move_down_button.isEnabled()
    _select(editor, editor.table.block_rows[1])
    assert editor.move_up_button.isEnabled()
    assert editor.move_down_button.isEnabled()


def test_the_buttons_sit_right_of_insert_below(editor):
    bar = editor.layout().itemAt(0).layout()
    widgets = [bar.itemAt(i).widget() for i in range(bar.count())]
    at = widgets.index(editor.insert_below_button)
    assert widgets[at + 1] is editor.move_up_button
    assert widgets[at + 2] is editor.move_down_button


def test_the_buttons_follow_the_edges_of_the_grid(editor):
    _select(editor, editor.table.block_rows[0])
    assert not editor.move_up_button.isEnabled()
    assert editor.move_down_button.isEnabled()
    _select(editor, editor.table.block_rows[-1])
    assert editor.move_up_button.isEnabled()
    assert not editor.move_down_button.isEnabled()


def test_a_section_row_disables_both_buttons(editor):
    _select(editor, _sections(editor.table)[1], column=0)
    assert editor.insert_above_button.isEnabled()
    assert not editor.move_up_button.isEnabled()
    assert not editor.move_down_button.isEnabled()
    assert editor.move_row(up=True) is None


def test_the_selection_follows_the_moved_row(editor):
    first = editor.table.block_rows[0]
    _select(editor, first, column=4)
    at = editor.move_row(up=False)
    assert _current_document_row(editor) == at
    assert editor.view.currentIndex().column() == 4
    again = editor.move_row(up=False)
    assert again == at + 1
    assert editor.table.rows[again].section == "Rewriting"
    assert editor.save_button.isEnabled()
    assert editor.path_label.text().endswith("*")


def test_the_grid_shows_the_new_order(editor):
    first = editor.table.block_rows[0]
    _select(editor, first)
    editor.move_row(up=False)
    grid = editor.model._rows.index(first)
    assert editor.model.data(editor.model.index(grid, 0)) == "05:45-07:15"
    assert editor.model.data(editor.model.index(grid + 1, 0)) == "04:00-05:30"


def test_the_log_names_a_change_of_section(editor):
    lines = []
    editor.logged.connect(lines.append)
    _select(editor, editor.table.block_rows[1])
    editor.move_row(up=False)
    assert lines[-1] == "Moved the 05:45-07:15 block down into Rewriting"


def test_the_time_tint_follows_the_moved_row(editor):
    _select(editor, editor.table.block_rows[0], column=0)
    tinted = set(editor.model.clear_of_selection())
    at = editor.move_row(up=False)
    assert editor.model._anchor == at
    assert len(editor.model.clear_of_selection()) == len(tinted)


def test_the_legend_stays_in_place(editor):
    codes = [editor.legend_model.entry(r)[0]
             for r in range(editor.legend_model.rowCount())]
    _select(editor, editor.table.block_rows[1])
    editor.move_row(up=False)
    after = [editor.legend_model.entry(r)[0]
             for r in range(editor.legend_model.rowCount())]
    assert after == codes


def test_alt_down_and_alt_up_move_the_row(editor, qtbot):
    from writing_habit.gui.qt import Qt
    editor.show()
    first = editor.table.block_rows[0]
    _select(editor, first)
    editor.view.setFocus()
    text = editor.table.to_text()
    qtbot.keyClick(editor.view, Qt.Key_Down, Qt.AltModifier)
    assert _current_document_row(editor) == first + 1
    qtbot.keyClick(editor.view, Qt.Key_Up, Qt.AltModifier)
    assert _current_document_row(editor) == first
    assert editor.table.to_text() == text


def test_saving_writes_the_new_order(editor):
    first = editor.table.block_rows[0]
    _select(editor, first)
    editor.move_row(up=False)
    lines = Path(editor.save()).read_text().splitlines()
    early = next(n for n, line in enumerate(lines) if "04:00-05:30" in line)
    late = next(n for n, line in enumerate(lines) if "05:45-07:15" in line)
    assert late == early - 1
