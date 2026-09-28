"""Inserting an empty time-block row above or below the selected row.

The document tests need no Qt. The widget tests check the two buttons, the row
selected after an insert, and that the legend panel still points at the right
lines once every row below the insert has moved down by one.
"""

import os
import shutil
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

#: A table whose Time column is padded on the left, as the scheduler writes it.
RIGHT_JUSTIFIED = (
    "|          Time | M | Tu |\n"
    "|---------------+---+----|\n"
    "| Generative:   |   |    |\n"
    "|   04:00-05:30 | A | B  |\n"
    "|---------------+---+----|\n"
    "| A: one        |   |    |\n"
    "| B: two        |   |    |\n"
)


@pytest.fixture()
def table():
    return WeeklyTable.from_file(str(EXAMPLE))


def _sections(table):
    return [i for i, row in enumerate(table.rows) if row.kind == SECTION]


# -- the document --------------------------------------------------------------
def test_insert_below_adds_exactly_one_line(table):
    before = table.to_text().splitlines()
    near = table.block_rows[0]
    at = table.insert_block(near, above=False, start="05:30", end="05:45")
    after = table.to_text().splitlines()
    assert len(after) == len(before) + 1
    assert at == near + 1
    offset = len(table._before)
    added = after.pop(offset + at)
    assert after == before
    assert added.startswith("| 05:30-05:45")
    assert table.dirty is True


def test_insert_above_takes_the_selected_rows_place(table):
    near = table.block_rows[1]
    at = table.insert_block(near, above=True, start="05:30", end="05:45")
    assert at == near
    assert table.rows[at + 1].parsed == ("05:45", "07:15")


def test_the_new_line_has_the_width_of_its_neighbour(table):
    near = table.block_rows[0]
    at = table.insert_block(near, above=False, start="05:30", end="05:45")
    assert len(table.rows[at].raw) == len(table.rows[near].raw)
    assert table.rows[at].raw.count("|") == table.rows[near].raw.count("|")


def test_the_new_row_is_empty_and_is_a_block(table):
    at = table.insert_block(table.block_rows[0], False, "05:30", "05:45")
    row = table.rows[at]
    assert row.kind == BLOCK
    assert all(cell == "" for cell in row.cells[1:])


def test_the_scheduler_reads_the_new_row(table):
    """The parser the tools use must see the same row the editor inserted."""
    rewriting = _sections(table)[1]
    table.insert_block(rewriting, above=False, start="08:00", end="09:00")
    text = table.to_text()
    reread = WeeklyTable(text)
    assert [r.kind for r in reread.rows] == [r.kind for r in table.rows]
    at = rewriting + 1
    assert reread.rows[at].parsed == ("08:00", "09:00")
    assert reread.rows[at].section == "Rewriting"
    parse_text(text)                                  # the scheduler accepts it


def test_above_a_section_header_joins_the_section_before(table):
    rewriting = _sections(table)[1]
    at = table.insert_block(rewriting, above=True, start="07:30", end="08:00")
    assert table.rows[at].section == "Generative"
    assert table.rows[at + 1].kind == SECTION


def test_below_a_section_header_joins_that_section(table):
    rewriting = _sections(table)[1]
    at = table.insert_block(rewriting, above=False, start="08:00", end="09:00")
    assert table.rows[at].section == "Rewriting"


def test_a_filled_new_row_counts_toward_the_totals(table):
    at = table.insert_block(table.block_rows[-1], False, "15:00", "16:00")
    column = table.columns[0][0]
    table.set_cell(at, column, "A")
    assert table.totals()["project"]["A"] > 0
    assert any(b.row == at for b in table.blocks())


@pytest.mark.parametrize("start,end", [("5:30", "abc"), ("10:00", "09:00"),
                                        ("", "")])
def test_a_bad_time_range_is_refused(table, start, end):
    before = table.to_text()
    with pytest.raises(ValueError):
        table.insert_block(table.block_rows[0], False, start, end)
    assert table.to_text() == before
    assert table.dirty is False


def test_a_legend_row_cannot_anchor_an_insert(table):
    with pytest.raises(ValueError):
        table.insert_block(table.legend_rows()[0], False, "05:30", "05:45")


def test_suggested_times_sit_flush_against_the_neighbour(table):
    first, second = table.block_rows[:2]
    assert table.suggest_times(first, above=True) == ("02:30", "04:00")
    assert table.suggest_times(second, above=False) == ("07:15", "08:45")


def test_suggested_times_beside_a_header_use_the_nearest_block(table):
    rewriting = _sections(table)[1]
    # Above the header, the new row follows the last block of Generative.
    assert table.suggest_times(rewriting, above=True) == ("07:15", "08:45")
    # Below the header, it precedes the first block of Rewriting.
    assert table.suggest_times(rewriting, above=False) == ("07:45", "09:15")


def test_suggested_times_never_run_past_midnight():
    table = WeeklyTable("| Time | M |\n|------+---|\n| 23:00-23:45 | A |\n")
    start, end = table.suggest_times(table.block_rows[0], above=False)
    assert (start, end) == ("23:45", "24:00")


def test_a_left_padded_time_column_stays_left_padded():
    table = WeeklyTable(RIGHT_JUSTIFIED)
    near = table.block_rows[0]
    at = table.insert_block(near, False, "05:30", "05:45")
    slot = table.rows[at].raw.split("|")[1]
    assert slot == "   05:30-05:45 "


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_every_shipped_table_accepts_an_insert(path):
    table = WeeklyTable.from_file(str(path))
    near = table.block_rows[0]
    start, end = table.suggest_times(near, above=False)
    at = table.insert_block(near, False, start, end)
    reread = WeeklyTable(table.to_text())
    assert reread.rows[at].kind == BLOCK
    assert reread.rows[at].parsed == (start, end)


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


def test_the_insert_buttons_wait_for_a_selection(editor):
    assert not editor.insert_above_button.isEnabled()
    assert not editor.insert_below_button.isEnabled()
    _select(editor, editor.table.block_rows[0])
    assert editor.insert_above_button.isEnabled()
    assert editor.insert_below_button.isEnabled()


def test_the_buttons_sit_right_of_reload(editor):
    bar = editor.layout().itemAt(0).layout()
    widgets = [bar.itemAt(i).widget() for i in range(bar.count())]
    reload_at = widgets.index(editor.reload_button)
    assert widgets[reload_at + 1] is editor.external_button
    assert widgets[reload_at + 2] is editor.insert_above_button
    assert widgets[reload_at + 3] is editor.insert_below_button


def test_insert_below_grows_the_grid_and_selects_the_new_row(editor):
    rows = editor.model.rowCount()
    near = editor.table.block_rows[0]
    _select(editor, near, column=3)
    at = editor.insert_row(above=False, times="05:30-05:45")
    assert at == near + 1
    assert editor.model.rowCount() == rows + 1
    current = editor.view.currentIndex()
    assert editor.model.document_row(current.row()) == at
    assert current.column() == 3
    assert editor.model.data(editor.model.index(current.row(), 0)) == "05:30-05:45"
    assert editor.save_button.isEnabled()
    assert editor.path_label.text().endswith("*")


def test_insert_above_places_the_row_before_the_selection(editor):
    near = editor.table.block_rows[1]
    _select(editor, near)
    at = editor.insert_row(above=True, times="05:30-05:45")
    assert at == near
    grid = editor.model._rows.index(at)
    assert editor.model.data(editor.model.index(grid + 1, 0)) == "05:45-07:15"


def test_the_new_row_takes_a_code(editor):
    _select(editor, editor.table.block_rows[0])
    at = editor.insert_row(above=False, times="05:30-05:45")
    grid = editor.model._rows.index(at)
    index = editor.model.index(grid, 1)
    assert editor.model.setData(index, "B")
    assert editor.table.cell(at, editor.table.columns[0][0]) == "B"


def test_the_legend_panel_follows_the_moved_rows(editor):
    codes = [editor.legend_model.entry(r)[0]
             for r in range(editor.legend_model.rowCount())]
    _select(editor, editor.table.block_rows[0])
    editor.insert_row(above=False, times="05:30-05:45")
    after = [editor.legend_model.entry(r)[0]
             for r in range(editor.legend_model.rowCount())]
    assert after == codes


def test_the_dialog_offers_the_suggested_range(editor, monkeypatch):
    seen = {}

    def fake(parent, title, label, mode, text):
        seen["text"] = text
        return text, True

    monkeypatch.setattr("writing_habit.gui.qt.QtWidgets.QInputDialog.getText", fake)
    near = editor.table.block_rows[1]
    _select(editor, near)
    at = editor.insert_row(above=False)
    assert seen["text"] == "07:15-08:45"
    assert editor.table.rows[at].parsed == ("07:15", "08:45")


def test_cancelling_the_dialog_changes_nothing(editor, monkeypatch):
    monkeypatch.setattr("writing_habit.gui.qt.QtWidgets.QInputDialog.getText",
                        lambda *a, **k: ("", False))
    before = editor.table.to_text()
    _select(editor, editor.table.block_rows[0])
    assert editor.insert_row(above=True) is None
    assert editor.table.to_text() == before
    assert editor.table.dirty is False


def test_a_bad_range_is_reported_not_inserted(editor, monkeypatch):
    shown = []
    monkeypatch.setattr("writing_habit.gui.qt.QtWidgets.QMessageBox.information",
                        lambda *args: shown.append(args[-1]))
    before = editor.table.to_text()
    _select(editor, editor.table.block_rows[0])
    assert editor.insert_row(above=False, times="10:00-09:00") is None
    assert editor.table.to_text() == before
    assert shown and "end after" in shown[0]


def test_saving_writes_the_inserted_row(editor):
    _select(editor, editor.table.block_rows[0])
    editor.insert_row(above=False, times="05:30-05:45")
    path = editor.save()
    assert "| 05:30-05:45" in Path(path).read_text()
