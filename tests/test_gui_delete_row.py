"""Deleting a time block from the grid and a project from the legend.

The document tests need no Qt. They check that a deletion removes exactly one
line, that only a time block or a legend entry can go, and that the sections
of the remaining blocks are unchanged. The widget tests check the two buttons,
when they are enabled, where the selection lands, and the confirmation asked
before a row or a project in use is deleted.
"""

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_schedule import parse_text                          # noqa: E402

from writing_habit.gui.weekly_table import (BLOCK, LEGEND,       # noqa: E402
                                            SECTION, WeeklyTable)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "my-week.org"


@pytest.fixture()
def table():
    return WeeklyTable.from_file(str(EXAMPLE))


def _codes(table):
    return [table.rows[i].parsed[0] for i in table.legend_rows()]


# -- the document: time blocks -------------------------------------------------
def test_deleting_a_block_removes_one_line(table):
    before = table.to_text().splitlines()
    target = table.block_rows[1]
    removed = table.rows[target].raw
    row = table.remove_block(target)
    after = table.to_text().splitlines()
    assert row.raw == removed
    assert len(after) == len(before) - 1
    assert after == [line for line in before if line != removed]
    assert table.dirty is True


def test_the_other_blocks_keep_their_sections(table):
    sections = {table.rows[i].parsed: table.rows[i].section
                for i in table.block_rows}
    target = table.block_rows[0]
    gone = table.rows[target].parsed
    table.remove_block(target)
    del sections[gone]
    assert {table.rows[i].parsed: table.rows[i].section
            for i in table.block_rows} == sections


def test_only_a_block_is_deleted(table):
    section = next(i for i, r in enumerate(table.rows) if r.kind == SECTION)
    legend = table.legend_rows()[0]
    for index in (section, legend, -1, len(table.rows)):
        assert not table.can_remove_block(index)
        with pytest.raises(ValueError, match="time-block"):
            table.remove_block(index)
    assert table.dirty is False


def test_the_totals_lose_the_deleted_block(table):
    target = table.block_rows[-1]           # the 13:15-14:45 support row
    table.remove_block(target)
    assert table.totals()["project"].get("E", 0) == 0
    assert "E" in table.legend()            # the legend entry stays


def test_the_scheduler_reads_the_table_after_a_deletion(table):
    table.remove_block(table.block_rows[2])
    parsed = parse_text(table.to_text())
    assert len(parsed.events) == len(table.blocks())


# -- the document: legend entries ----------------------------------------------
def test_deleting_a_project_removes_one_line(table):
    before = table.to_text().splitlines()
    table.remove_legend(table.legend_rows()[2])
    after = table.to_text().splitlines()
    assert len(after) == len(before) - 1
    assert _codes(table) == ["A", "B", "T", "E"]
    assert [r.raw for r in table.rows if r.kind == BLOCK] == [
        r.raw for r in WeeklyTable.from_file(str(EXAMPLE)).rows if r.kind == BLOCK]


def test_a_grid_row_is_not_deleted_as_a_project(table):
    with pytest.raises(ValueError, match="legend row"):
        table.remove_legend(table.block_rows[0])


def test_cells_using_counts_the_grid(table):
    assert table.cells_using("A") == 8
    assert table.cells_using("e") == 5
    assert table.cells_using("Q") == 0


def test_a_deleted_synced_code_is_forgotten():
    table = WeeklyTable(EXAMPLE.read_text())
    table.set_cell(table.block_rows[0], 6, "Q")
    table.sync_legend()
    assert "Q" in table._synced_codes
    table.remove_legend(table.legend_rows()[_codes(table).index("Q")])
    assert "Q" not in table._synced_codes


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


def _select_grid(editor, document_row, column=1):
    grid_row = editor.model._rows.index(document_row)
    editor.view.setCurrentIndex(editor.model.index(grid_row, column))
    return grid_row


def _select_legend(editor, legend_row, column=1):
    editor.legend_view.setCurrentIndex(editor.legend_model.index(legend_row, column))


def _shown_codes(editor):
    return [editor.legend_model.entry(r)[0]
            for r in range(editor.legend_model.rowCount())]


def test_delete_row_sits_right_of_move_down(editor):
    bar = editor.layout().itemAt(0).layout()
    widgets = [bar.itemAt(i).widget() for i in range(bar.count())]
    at = widgets.index(editor.move_down_button)
    assert widgets[at + 1] is editor.delete_row_button


def test_delete_project_sits_right_of_move_project_down(editor):
    bar = editor.project_below_button.parentWidget().layout().itemAt(0).layout()
    widgets = [bar.itemAt(i).widget() for i in range(bar.count())]
    at = widgets.index(editor.project_down_button)
    assert widgets[at + 1] is editor.delete_project_button


def test_delete_row_waits_for_a_time_block(editor):
    assert not editor.delete_row_button.isEnabled()
    section = next(i for i, r in enumerate(editor.table.rows) if r.kind == SECTION)
    _select_grid(editor, section)
    assert not editor.delete_row_button.isEnabled()
    _select_grid(editor, editor.table.block_rows[0])
    assert editor.delete_row_button.isEnabled()


def test_delete_project_waits_for_a_selection(editor):
    assert not editor.delete_project_button.isEnabled()
    _select_legend(editor, 0)
    assert editor.delete_project_button.isEnabled()


def test_deleting_a_row_moves_the_selection_to_the_next_row(editor):
    target = editor.table.block_rows[0]
    grid_row = _select_grid(editor, target, column=3)
    following = editor.table.rows[editor.table.block_rows[1]].raw
    assert editor.delete_row(confirm=False) == target
    current = editor.view.currentIndex()
    assert current.row() == grid_row
    assert current.column() == 3
    assert editor.table.rows[editor.model.document_row(grid_row)].raw == following
    assert editor.save_button.isEnabled()
    assert editor.path_label.text().endswith("*")


def test_deleting_the_last_row_selects_the_row_above(editor):
    _select_grid(editor, editor.table.block_rows[-1])
    editor.delete_row(confirm=False)
    assert editor.view.currentIndex().row() == editor.model.rowCount() - 1


def test_a_filled_row_asks_first(editor, monkeypatch):
    asked = []
    monkeypatch.setattr(editor, "_confirm",
                        lambda title, text: asked.append(text) or False)
    before = editor.table.to_text()
    _select_grid(editor, editor.table.block_rows[0])
    assert editor.delete_row() is None
    assert editor.table.to_text() == before
    assert "A B A B W" in asked[0]


def test_an_empty_row_goes_without_asking(editor, monkeypatch):
    monkeypatch.setattr(editor, "_confirm",
                        lambda *_a: pytest.fail("an empty row needs no question"))
    _select_grid(editor, editor.table.block_rows[0])
    at = editor.insert_row(above=False, times="05:30-05:45")
    _select_grid(editor, at)
    count = len(editor.table.block_rows)
    assert editor.delete_row() == at
    assert len(editor.table.block_rows) == count - 1


def test_a_section_header_is_not_deleted(editor):
    lines = []
    editor.logged.connect(lines.append)
    section = next(i for i, r in enumerate(editor.table.rows) if r.kind == SECTION)
    _select_grid(editor, section)
    before = editor.table.to_text()
    assert editor.delete_row(confirm=False) is None
    assert editor.table.to_text() == before
    assert "section header" in lines[-1]


def test_the_log_names_the_deleted_block(editor):
    lines = []
    editor.logged.connect(lines.append)
    _select_grid(editor, editor.table.block_rows[2])
    editor.delete_row(confirm=False)
    assert "Deleted the 09:15-10:45 block from Rewriting" in lines


def test_deleting_a_project_moves_the_selection(editor):
    _select_legend(editor, 1, column=2)
    editor.delete_project(confirm=False)
    assert _shown_codes(editor) == ["A", "W", "T", "E"]
    current = editor.legend_view.currentIndex()
    assert current.row() == 1
    assert current.column() == 2


def test_a_project_in_use_asks_first(editor, monkeypatch):
    asked = []
    monkeypatch.setattr(editor, "_confirm",
                        lambda title, text: asked.append(text) or False)
    _select_legend(editor, 0)
    assert editor.delete_project() is None
    assert _shown_codes(editor) == ["A", "B", "W", "T", "E"]
    assert "8 cell(s)" in asked[0]


def test_a_grid_edit_restores_a_project_still_in_use(editor):
    _select_legend(editor, 4)               # E, used by five cells
    editor.delete_project(confirm=False)
    assert "E" not in _shown_codes(editor)
    assert "E: not in the key" == editor.model.tooltip("E")
    # A later grid edit syncs the legend, and the writer's deletion stands
    # only until then, because the grid still uses E.
    _select_grid(editor, editor.table.block_rows[0], column=6)
    editor.model.setData(editor.view.currentIndex(), "A")
    assert "E" in _shown_codes(editor)


def test_saving_writes_both_deletions(editor):
    _select_grid(editor, editor.table.block_rows[0])
    editor.delete_row(confirm=False)
    _select_legend(editor, 3)               # T
    editor.delete_project(confirm=False)
    text = Path(editor.save()).read_text()
    assert "04:00-05:30" not in text
    assert "| T:" not in text
    assert len(text.splitlines()) == len(EXAMPLE.read_text().splitlines()) - 2
