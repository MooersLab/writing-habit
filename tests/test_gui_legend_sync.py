"""The legend follows the grid.

A project code typed into a cell needs a legend row, because a code with no
description reaches the database with no project name and no risk class. The
rows are added as the grid gains codes and dropped again while they are still
blank, so a typo does not leave a row behind that the interface offers no way
to delete.
"""
from __future__ import annotations

import pytest

from writing_habit.gui.weekly_table import WeeklyTable

TABLE = """#+TITLE: A week

| Time <l>    | M  | Tu | W  | Th | F  |
|-------------+----+----+----+----+----|
| Generative: |    |    |    |    |    |
| 09:00-09:30 | A  |    |    |    |    |
| 10:00-10:30 |    |    |    |    |    |
|-------------+----+----+----+----+----|
| A: main paper :safe: |  |  |  |  |  |
"""


def table() -> WeeklyTable:
    return WeeklyTable(TABLE)


def codes(t: WeeklyTable):
    return list(t.legend())


def test_a_new_code_gains_a_legend_row():
    """Typing B into a cell puts B in the legend."""
    t = table()
    assert codes(t) == ["A"]
    block = t.block_rows[1]
    t.set_cell(block, 1, "B")
    assert t.sync_legend() is True
    assert codes(t) == ["A", "B"]
    assert t.legend()["B"] == ("", None)


def test_the_added_row_is_a_real_line_of_the_file():
    """The row survives a round trip through the text, in the legend block."""
    t = table()
    t.set_cell(t.block_rows[1], 1, "B")
    t.sync_legend()
    text = t.to_text()
    assert "| B:" in text
    again = WeeklyTable(text)
    assert codes(again) == ["A", "B"]
    # The added line sits with the other legend rows, not above the grid.
    lines = text.splitlines()
    assert lines.index("| A: main paper :safe: |  |  |  |  |  |") < \
        [i for i, line in enumerate(lines) if line.startswith("| B:")][0]


def test_the_untouched_lines_are_left_alone():
    """Adding a legend row rewrites nothing else."""
    t = table()
    before = TABLE.splitlines()
    t.set_cell(t.block_rows[1], 1, "B")
    t.sync_legend()
    after = t.to_text().splitlines()
    # One line changed (the edited cell) and one line was added.
    assert len(after) == len(before) + 1
    changed = [line for line in before if line not in after]
    assert changed == ["| 10:00-10:30 |    |    |    |    |    |"]


def test_a_blank_row_goes_when_its_code_leaves_the_grid():
    """A typo cleans up after itself."""
    t = table()
    block = t.block_rows[1]
    t.set_cell(block, 1, "Q")
    t.sync_legend()
    assert "Q" in codes(t)
    t.set_cell(block, 1, "")
    assert t.sync_legend() is True
    assert codes(t) == ["A"]


def test_a_described_row_stays_when_its_code_leaves_the_grid():
    """Anything the writer typed survives, even once the code is unused."""
    t = table()
    block = t.block_rows[1]
    t.set_cell(block, 1, "Q")
    t.sync_legend()
    row = t.legend_rows()[-1]
    t.set_legend(row, "Q", "the grant", "speculative")
    t.set_cell(block, 1, "")
    assert t.sync_legend() is False
    assert codes(t) == ["A", "Q"]
    assert t.legend()["Q"] == ("the grant", "speculative")


def test_a_code_still_in_use_keeps_its_row():
    """A code used twice does not lose its legend when one cell is cleared."""
    t = table()
    first, second = t.block_rows[0], t.block_rows[1]
    t.set_cell(first, 2, "B")
    t.set_cell(second, 1, "B")
    t.sync_legend()
    t.set_cell(second, 1, "")
    assert t.sync_legend() is False
    assert "B" in codes(t)


def test_sync_reports_no_change_when_the_legend_already_fits():
    """A table whose legend covers its grid is left untouched."""
    t = table()
    text = t.to_text()
    assert t.sync_legend() is False
    assert t.to_text() == text


def test_a_table_with_no_legend_block_gets_one():
    """The first code adds the first legend line."""
    t = WeeklyTable("""| Time <l>    | M  | Tu |
|-------------+----+----|
| Generative: |    |    |
| 09:00-09:30 |    |    |
""")
    assert codes(t) == []
    t.set_cell(t.block_rows[0], 1, "A")
    assert t.sync_legend() is True
    assert codes(t) == ["A"]
    assert codes(WeeklyTable(t.to_text())) == ["A"]


def test_the_editor_syncs_on_a_grid_edit(qtbot, monkeypatch, tmp_path):
    """Typing in a cell refreshes the legend view, not just the document."""
    store = {"table_dir": str(tmp_path), "db": "", "out_dir": "",
             "timezone": "America/Chicago", "week": ""}
    for module in ("writing_habit.gui.settings",
                   "writing_habit.gui.schedule_editor.settings"):
        monkeypatch.setattr(f"{module}.get", lambda key: store.get(key, ""))
        monkeypatch.setattr(f"{module}.put",
                            lambda key, value: store.__setitem__(key, value))

    from writing_habit.gui.schedule_editor import ScheduleEditor

    path = tmp_path / "week.org"
    path.write_text(TABLE, encoding="utf-8")
    editor = ScheduleEditor()
    qtbot.addWidget(editor)
    editor.open(str(path))
    assert editor.legend_model.rowCount() == 1

    index = editor.model.index(editor.model.rowCount() - 1, 1)
    editor.model.setData(index, "B")
    assert editor.legend_model.rowCount() == 2
    assert editor.legend_model.index(1, 0).data() == "B"


def test_the_new_table_button_asks_for_a_count(qtbot, monkeypatch, tmp_path):
    """clicked carries a checked flag, which must not become the project count."""
    store = {"table_dir": str(tmp_path), "db": "", "out_dir": "",
             "timezone": "America/Chicago", "week": ""}
    for module in ("writing_habit.gui.settings",
                   "writing_habit.gui.schedule_editor.settings"):
        monkeypatch.setattr(f"{module}.get", lambda key: store.get(key, ""))
        monkeypatch.setattr(f"{module}.put",
                            lambda key, value: store.__setitem__(key, value))

    from writing_habit.gui import schedule_editor as module
    from writing_habit.gui.schedule_editor import ScheduleEditor

    asked = []

    def fake_get_int(parent, title, label, value=0, minimum=0, maximum=99):
        asked.append((label, value))
        return 3, True

    monkeypatch.setattr(module.QtWidgets.QInputDialog, "getInt",
                        staticmethod(fake_get_int))

    editor = ScheduleEditor()
    qtbot.addWidget(editor)
    messages = []
    editor.logged.connect(messages.append)

    editor.new_button.click()

    assert asked, "the button went straight past the dialog"
    assert editor.table is not None
    assert "3 project(s)" in messages[-1]
    # The scaffold is blank, so the three projects show up as legend rows
    # rather than as filled cells. With the checked flag arriving as the count,
    # template_string(0) was called and only one project was defined.
    assert list(editor.table.legend()) == ["A", "B", "C"]
    assert editor.legend_model.rowCount() == 3
