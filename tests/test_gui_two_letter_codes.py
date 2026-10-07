"""Two-letter project codes, so a legend can hold more than 26 projects.

The single letters are offered first and the codes AA to ZZ follow. Both the
grid and the legend take a two-letter code, and both readers keep it whole. The
file name stays limited to single letters, so a week that puts a two-letter
code in a cell has no canonical name, and the Name panel says why.
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


def test_the_codes_run_from_a_to_zz():
    assert PROJECT_CODES[:26] == tuple(string.ascii_uppercase)
    assert PROJECT_CODES[26:29] == ("AA", "AB", "AC")
    assert PROJECT_CODES[-1] == "ZZ"
    assert len(PROJECT_CODES) == len(set(PROJECT_CODES)) == 702


def test_the_next_free_code_follows_z_with_aa():
    table = _full_table()
    assert len(table.legend()) == 26
    assert table.next_free_code() == "AA"
    table.insert_legend(None, False, "AA", "a 27th project")
    assert table.next_free_code() == "AB"


def test_a_two_letter_code_in_the_grid_is_not_offered_again():
    table = _full_table()
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
    editor.scaffold(30)
    codes = list(editor.table.legend())
    assert codes == list(PROJECT_CODES[:30])
    assert editor.legend_model.rowCount() == 30
    assert codes[-4:] == ["AA", "AB", "AC", "AD"]
    parse_text(editor.table.to_text())


def test_a_scaffold_of_26_is_the_schedulers_own(editor):
    editor.scaffold(26)
    assert editor.table.to_text() == template_string(26)


def test_the_insert_dialog_offers_aa_once_z_is_taken(editor, monkeypatch):
    editor.scaffold(26)
    offered = []
    monkeypatch.setattr(editor, "_ask_project",
                        lambda code: offered.append(code) or (code, "new", None))
    at = editor.insert_project(above=False)
    assert offered == ["AA"]
    assert editor.table.rows[at].parsed[0] == "AA"
    assert editor.legend_model.rowCount() == 27


def test_a_grid_cell_takes_a_two_letter_code(editor):
    editor.scaffold(27)
    grid_row = editor.model._rows.index(editor.table.block_rows[0])
    index = editor.model.index(grid_row, 1)
    assert "AA" in editor.model.codes()
    assert editor.model.setData(index, "aa")
    assert editor.model.data(index) == "AA"
    assert editor.model.tooltip("AA").startswith("AA:")
    assert "no canonical file name" in editor.name_panel.toPlainText()
