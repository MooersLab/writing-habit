"""Shifting a project up or down in the legend of the Schedule tab.

The document tests need no Qt. They check that a move reorders legend lines
without rewriting any, that it never leaves the legend, and that it decides
which definition of a duplicated code the readers keep. The widget tests check
the two buttons, their state at the ends of the legend, the keyboard shortcuts,
and that the selection follows the moved project.
"""

import os
import shutil
from collections import Counter
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_schedule import parse_text                          # noqa: E402

from writing_habit.gui.weekly_table import LEGEND, WeeklyTable   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "my-week.org"

#: A legend that defines H twice, as examples/aug24.org once did.
DUPLICATE = (
    "| Time | M |\n"
    "|------+---|\n"
    "| Generative: |  |\n"
    "| 09:00-10:00 | H |\n"
    "|------+---|\n"
    "| H: first :safe: |  |\n"
    "| H: second :risky: |  |\n"
)


@pytest.fixture()
def table():
    return WeeklyTable.from_file(str(EXAMPLE))


def _codes(table):
    return [table.rows[i].parsed[0] for i in table.legend_rows()]


# -- the document --------------------------------------------------------------
def test_moving_a_project_down_swaps_two_lines(table):
    first, second = table.legend_rows()[:2]
    before = table.to_text().splitlines()
    at = table.move_legend(first, up=False)
    after = table.to_text().splitlines()
    assert at == second
    assert _codes(table) == ["B", "A", "W", "T", "E"]
    changed = [n for n, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(changed) == 2
    assert table.dirty is True


def test_moving_up_undoes_moving_down(table):
    text = table.to_text()
    at = table.move_legend(table.legend_rows()[2], up=False)
    table.move_legend(at, up=True)
    assert table.to_text() == text


def test_a_move_keeps_every_line_byte_for_byte(table):
    before = Counter(table.to_text().splitlines())
    table.move_legend(table.legend_rows()[3], up=True)
    assert Counter(table.to_text().splitlines()) == before


def test_the_grid_is_not_touched(table):
    blocks = [(r.raw, r.section) for r in table.rows if r.kind != LEGEND]
    table.move_legend(table.legend_rows()[0], up=False)
    assert [(r.raw, r.section) for r in table.rows if r.kind != LEGEND] == blocks
    assert table.totals() == WeeklyTable.from_file(str(EXAMPLE)).totals()


def test_nothing_moves_past_the_ends_of_the_legend(table):
    rows = table.legend_rows()
    assert not table.can_move_legend(rows[0], up=True)
    assert not table.can_move_legend(rows[-1], up=False)
    before = table.to_text()
    with pytest.raises(ValueError, match="top"):
        table.move_legend(rows[0], up=True)
    with pytest.raises(ValueError, match="bottom"):
        table.move_legend(rows[-1], up=False)
    assert table.to_text() == before
    assert table.dirty is False


def test_a_grid_row_does_not_move_as_a_project(table):
    assert not table.can_move_legend(table.block_rows[0], up=False)
    with pytest.raises(ValueError, match="legend row"):
        table.move_legend(table.block_rows[0], up=False)


def test_the_scheduler_reads_the_moved_legend(table):
    table.move_legend(table.legend_rows()[0], up=False)
    text = table.to_text()
    assert _codes(WeeklyTable(text)) == _codes(table)
    parse_text(text)


def test_the_order_decides_which_duplicate_is_kept():
    table = WeeklyTable(DUPLICATE)
    assert table.project_info("H")["risk"] == "safe"
    table.move_legend(table.legend_rows()[1], up=True)
    assert table.project_info("H")["risk"] == "risky"


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


def _select(editor, legend_row, column=1):
    editor.legend_view.setCurrentIndex(editor.legend_model.index(legend_row, column))


def _shown_codes(editor):
    return [editor.legend_model.entry(r)[0]
            for r in range(editor.legend_model.rowCount())]


def test_the_buttons_wait_for_a_selection(editor):
    assert not editor.project_up_button.isEnabled()
    assert not editor.project_down_button.isEnabled()
    _select(editor, 2)
    assert editor.project_up_button.isEnabled()
    assert editor.project_down_button.isEnabled()


def test_the_buttons_sit_right_of_insert_project_below(editor):
    bar = editor.project_below_button.parentWidget().layout().itemAt(0).layout()
    widgets = [bar.itemAt(i).widget() for i in range(bar.count())]
    at = widgets.index(editor.project_below_button)
    assert widgets[at + 1] is editor.project_up_button
    assert widgets[at + 2] is editor.project_down_button


def test_the_buttons_follow_the_ends_of_the_legend(editor):
    _select(editor, 0)
    assert not editor.project_up_button.isEnabled()
    assert editor.project_down_button.isEnabled()
    _select(editor, editor.legend_model.rowCount() - 1)
    assert editor.project_up_button.isEnabled()
    assert not editor.project_down_button.isEnabled()


def test_the_selection_follows_the_moved_project(editor):
    _select(editor, 0, column=2)
    editor.move_project(up=False)
    editor.move_project(up=False)
    assert _shown_codes(editor) == ["B", "W", "A", "T", "E"]
    current = editor.legend_view.currentIndex()
    assert current.row() == 2
    assert current.column() == 2
    assert editor.save_button.isEnabled()
    assert editor.path_label.text().endswith("*")


def test_the_grid_selection_survives_a_project_move(editor):
    grid_row = editor.model._rows.index(editor.table.block_rows[1])
    editor.view.setCurrentIndex(editor.model.index(grid_row, 3))
    _select(editor, 1)
    editor.move_project(up=True)
    assert editor.view.currentIndex().row() == grid_row
    assert editor.view.currentIndex().column() == 3


def test_the_log_names_the_project(editor):
    lines = []
    editor.logged.connect(lines.append)
    _select(editor, 3)
    editor.move_project(up=True)
    assert lines[-1] == "Moved project T up in the legend"


def test_a_press_at_the_end_changes_nothing(editor):
    before = editor.table.to_text()
    _select(editor, 0)
    assert editor.move_project(up=True) is None
    assert editor.table.to_text() == before


def test_alt_keys_move_the_project_when_the_legend_has_focus(editor, qtbot):
    from writing_habit.gui.qt import Qt
    editor.show()
    qtbot.waitExposed(editor)
    _select(editor, 1)
    editor.legend_view.setFocus()
    qtbot.waitUntil(editor.legend_view.hasFocus)
    grid_text = [r.raw for r in editor.table.rows if r.kind != LEGEND]
    qtbot.keyClick(editor.legend_view, Qt.Key_Down, Qt.AltModifier)
    assert _shown_codes(editor) == ["A", "W", "B", "T", "E"]
    qtbot.keyClick(editor.legend_view, Qt.Key_Up, Qt.AltModifier)
    assert _shown_codes(editor) == ["A", "B", "W", "T", "E"]
    assert [r.raw for r in editor.table.rows if r.kind != LEGEND] == grid_text


def test_saving_writes_the_new_order(editor):
    _select(editor, 0)
    editor.move_project(up=False)
    lines = Path(editor.save()).read_text().splitlines()
    a = next(n for n, line in enumerate(lines) if line.startswith("| A:"))
    b = next(n for n, line in enumerate(lines) if line.startswith("| B:"))
    assert a == b + 1
