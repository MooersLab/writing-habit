"""Digit and two-letter project codes, so a legend can hold more than 26 projects.

The single letters are offered first, then the digits 0 to 9, and then the
codes AA to ZZ. Both the grid and the legend take every one of them, and both
readers keep a two-letter code whole. The file name carries the 36
one-character codes, so a week that puts a two-letter code in a cell has no
canonical name, and the Name panel says why.
"""

import os
import string

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_schedule import parse_text                          # noqa: E402
from writing_schedule.template import template_string            # noqa: E402

from writing_habit.gui.weekly_table import (PROJECT_CODES,       # noqa: E402
                                            WeeklyTable)


def _full_table():
    return WeeklyTable(template_string(26))


def _full_36():
    table = _full_table()
    for digit in string.digits:
        table.insert_legend(None, False, digit, f"project {digit}")
    return table


def test_the_codes_run_from_a_to_z_then_digits_then_aa_to_zz():
    assert PROJECT_CODES[:26] == tuple(string.ascii_uppercase)
    assert PROJECT_CODES[26:36] == tuple(string.digits)
    assert PROJECT_CODES[36:39] == ("AA", "AB", "AC")
    assert PROJECT_CODES[-1] == "ZZ"
    assert len(PROJECT_CODES) == len(set(PROJECT_CODES)) == 712


def test_the_next_free_code_follows_z_with_0_and_9_with_aa():
    table = _full_table()
    assert len(table.legend()) == 26
    assert table.next_free_code() == "0"
    table = _full_36()
    assert table.next_free_code() == "AA"
    table.insert_legend(None, False, "AA", "a 37th project")
    assert table.next_free_code() == "AB"


def test_a_two_letter_code_in_the_grid_is_not_offered_again():
    table = _full_36()
    table.set_cell(table.block_rows[0], 1, "ab")
    assert table.next_free_code() == "AA"
    table.insert_legend(None, False, "AA")
    assert table.next_free_code() == "AC"


def test_the_legend_holds_more_than_26_projects():
    table = _full_table()
    for _n in range(10):
        table.insert_legend(None, False, table.next_free_code(), "x")
    assert len(table.legend()) == 36
    parsed = parse_text(table.to_text())
    assert [code for code, _desc in parsed.legend][-10:] == list(PROJECT_CODES[26:36])


def test_a_two_letter_cell_reaches_the_readers_whole():
    table = _full_table()
    table.insert_legend(None, False, "AB", "a 28th project :safe:")
    table.set_cell(table.block_rows[0], 1, "AB")
    assert table.blocks()[0].letter == "AB"
    assert table.project_info("AB")["risk"] == "safe"
    assert table.totals()["project"]["AB"] > 0
    events = parse_text(table.to_text()).events
    assert [e.letter for e in events] == ["AB"]


def test_a_two_letter_cell_has_no_canonical_name():
    table = _full_table()
    table.set_cell(table.block_rows[0], 1, "AB")
    code, problem = table.code_or_problem()
    assert code is None
    assert "one uppercase letter" in problem


# -- the widget ----------------------------------------------------------------
@pytest.fixture()
def editor(qtbot, monkeypatch):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    store = {}
    monkeypatch.setattr("writing_habit.gui.settings.get",
                        lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    return widget


def test_a_scaffold_can_hold_more_than_26_projects(editor):
    editor.scaffold(40)
    codes = list(editor.table.legend())
    assert codes == list(PROJECT_CODES[:40])
    assert editor.legend_model.rowCount() == 40
    assert codes[26:28] == ["0", "1"]
    assert codes[-4:] == ["AA", "AB", "AC", "AD"]
    parse_text(editor.table.to_text())


def test_a_scaffold_of_26_is_the_schedulers_own(editor):
    editor.scaffold(26)
    assert editor.table.to_text() == template_string(26)


def test_the_insert_dialog_offers_0_after_z_and_aa_after_9(editor, monkeypatch):
    editor.scaffold(26)
    offered = []
    monkeypatch.setattr(editor, "_ask_project",
                        lambda code: offered.append(code) or (code, "new", None))
    at = editor.insert_project(above=False)
    assert offered == ["0"]
    assert editor.table.rows[at].parsed[0] == "0"
    editor.scaffold(36)
    editor.insert_project(above=False)
    assert offered == ["0", "AA"]
    assert editor.legend_model.rowCount() == 37


def test_a_grid_cell_takes_a_two_letter_code(editor):
    editor.scaffold(37)
    grid_row = editor.model._rows.index(editor.table.block_rows[0])
    index = editor.model.index(grid_row, 1)
    assert "AA" in editor.model.codes()
    assert editor.model.setData(index, "aa")
    assert editor.model.data(index) == "AA"
    assert editor.model.tooltip("AA").startswith("AA:")
    assert "no canonical file name" in editor.name_panel.toPlainText()


def test_a_digit_code_works_in_the_grid_and_in_the_file_name():
    table = _full_36()
    table.set_cell(table.block_rows[0], 1, "g3")
    table.set_cell(table.block_rows[0], 2, "7")
    assert table.blocks()[0].letter == "3"
    code, problem = table.code_or_problem()
    assert problem is None and "g3" in code
    events = parse_text(table.to_text()).events
    assert sorted(e.letter for e in events) == ["3", "7"]
