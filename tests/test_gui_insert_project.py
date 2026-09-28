"""Inserting a project into the legend above or below the selected entry."""

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_schedule import parse_text                          # noqa: E402

from writing_habit.gui.weekly_table import LEGEND, WeeklyTable   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "my-week.org"


@pytest.fixture()
def table():
    return WeeklyTable.from_file(str(EXAMPLE))


def _codes(table):
    return list(table.legend())


# -- the document --------------------------------------------------------------
def test_insert_below_adds_one_line_after_the_entry(table):
    before = table.to_text().splitlines()
    near = table.legend_rows()[1]                       # B
    at = table.insert_legend(near, False, "C", "new grant", "speculative")
    assert at == near + 1
    assert _codes(table) == ["A", "B", "C", "W", "T", "E"]
    after = table.to_text().splitlines()
    added = after.pop(len(table._before) + at)
    assert after == before
    assert added.startswith("| C: new grant :risky:")
    assert table.dirty is True


def test_insert_above_takes_the_entrys_place(table):
    at = table.insert_legend(table.legend_rows()[0], True, "Z")
    assert _codes(table)[0] == "Z"
    assert table.rows[at].parsed == ("Z", "", None)


def test_the_new_line_has_the_width_of_its_neighbour(table):
    near = table.legend_rows()[0]
    at = table.insert_legend(near, False, "C", "short")
    assert len(table.rows[at].raw) == len(table.rows[near].raw)


def test_no_anchor_appends_to_the_legend(table):
    at = table.insert_legend(None, False, "Q", "last")
    assert at == table.legend_rows()[-1]
    assert _codes(table)[-1] == "Q"


def test_a_lowercase_code_is_raised(table):
    at = table.insert_legend(None, False, "em2", "email")
    assert table.rows[at].parsed[0] == "EM2"


@pytest.mark.parametrize("code", ["", "1A", "ABCDE", "A-B"])
def test_a_bad_code_is_refused(table, code):
    before = table.to_text()
    with pytest.raises(ValueError):
        table.insert_legend(None, False, code)
    assert table.to_text() == before


def test_a_duplicate_code_is_refused(table):
    with pytest.raises(ValueError, match="already"):
        table.insert_legend(table.legend_rows()[0], False, "a")


def test_a_block_row_cannot_anchor_a_project(table):
    with pytest.raises(ValueError):
        table.insert_legend(table.block_rows[0], False, "C")


def test_both_readers_see_a_blank_project(table):
    """``Z:`` also has the shape of a section header, so check both parsers."""
    table.insert_legend(table.legend_rows()[0], True, "Z")
    text = table.to_text()
    reread = WeeklyTable(text)
    assert [r.kind for r in reread.rows] == [r.kind for r in table.rows]
    assert ("Z", "") in parse_text(text).legend


def test_the_next_free_code_skips_legend_and_grid(table):
    assert table.next_free_code() == "C"
    table.insert_legend(None, False, "C")
    assert table.next_free_code() == "D"


def test_sync_keeps_an_inserted_blank_project(table):
    table.insert_legend(None, False, "Q")
    block = table.block_rows[0]
    table.set_cell(block, 6, "B")
    table.sync_legend()
    assert "Q" in table.legend()


def test_sync_keeps_a_blank_project_read_from_the_file(table):
    table.insert_legend(None, False, "Q")
    reread = WeeklyTable(table.to_text())
    reread.set_cell(reread.block_rows[0], 6, "B")
    assert reread.sync_legend() is False
    assert "Q" in reread.legend()


def test_sync_still_removes_its_own_typo_row(table):
    block = table.block_rows[0]
    table.set_cell(block, 6, "X")
    table.sync_legend()
    assert "X" in table.legend()
    table.set_cell(block, 6, "")
    assert table.sync_legend() is True
    assert "X" not in table.legend()


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


def _select_legend(editor, legend_row):
    editor.legend_view.setCurrentIndex(editor.legend_model.index(legend_row, 0))


def _legend_codes(editor):
    return [editor.legend_model.entry(r)[0]
            for r in range(editor.legend_model.rowCount())]


def test_the_buttons_sit_above_the_legend(editor):
    box = editor.legend_view.parentWidget()
    layout = box.layout()
    bar = layout.itemAt(0).layout()
    widgets = [bar.itemAt(i).widget() for i in range(bar.count())]
    assert widgets[:2] == [editor.project_above_button, editor.project_below_button]
    assert layout.itemAt(1).widget() is editor.legend_view


def test_the_buttons_wait_for_a_table(qtbot, monkeypatch):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    assert not widget.project_above_button.isEnabled()
    assert not widget.project_below_button.isEnabled()


def test_insert_below_the_selected_project(editor):
    _select_legend(editor, 1)                           # B
    editor.insert_project(above=False, code="C", description="new", risk="safe")
    assert _legend_codes(editor) == ["A", "B", "C", "W", "T", "E"]
    current = editor.legend_view.currentIndex()
    assert current.row() == 2
    assert editor.save_button.isEnabled()


def test_insert_above_the_selected_project(editor):
    _select_legend(editor, 1)
    editor.insert_project(above=True, code="C")
    assert _legend_codes(editor) == ["A", "C", "B", "W", "T", "E"]


def test_no_selection_below_appends_and_above_prepends(editor):
    editor.insert_project(above=False, code="Y")
    editor.legend_view.setCurrentIndex(editor.legend_model.index(-1, -1))
    editor.insert_project(above=True, code="Z")
    codes = _legend_codes(editor)
    assert codes[-1] == "Y" and codes[0] == "Z"


def test_the_dialog_offers_the_next_free_code(editor, monkeypatch):
    seen = {}

    def ask(code):
        seen["code"] = code
        return code, "from the dialog", "speculative"

    monkeypatch.setattr(editor, "_ask_project", ask)
    _select_legend(editor, 0)
    at = editor.insert_project(above=False)
    assert seen["code"] == "C"
    assert editor.table.rows[at].parsed == ("C", "from the dialog", "speculative")


def test_cancelling_the_dialog_changes_nothing(editor, monkeypatch):
    monkeypatch.setattr(editor, "_ask_project", lambda code: None)
    before = editor.table.to_text()
    assert editor.insert_project(above=False) is None
    assert editor.table.to_text() == before


def test_a_duplicate_is_reported_not_inserted(editor, monkeypatch):
    shown = []
    monkeypatch.setattr("writing_habit.gui.qt.QtWidgets.QMessageBox.information",
                        lambda *args: shown.append(args[-1]))
    before = editor.table.to_text()
    assert editor.insert_project(above=False, code="A") is None
    assert editor.table.to_text() == before
    assert shown and "already" in shown[0]


def test_the_new_code_is_offered_in_the_grid(editor):
    editor.insert_project(above=False, code="C", description="new")
    assert "C" in editor.model.codes()


def test_a_grid_edit_does_not_remove_the_new_project(editor):
    editor.insert_project(above=False, code="Q")
    grid_row = editor.model._rows.index(editor.table.block_rows[0])
    editor.model.setData(editor.model.index(grid_row, 6), "B")
    assert "Q" in _legend_codes(editor)


def test_saving_writes_the_new_project(editor):
    editor.insert_project(above=False, code="C", description="new grant",
                          risk="safe")
    path = editor.save()
    assert "| C: new grant :safe:" in Path(path).read_text()
