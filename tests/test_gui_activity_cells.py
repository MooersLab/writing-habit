"""Activity letters in the cells and default activities in the legend.

A cell may name its activity with a lowercase letter before the code, so
``eA`` is editing on project A. A legend entry may name a default activity with
a tag such as ``@support``. Otherwise the section header decides, as before.
The document tests need no Qt; the widget tests check the cell editor, the
tint, the tooltip, the legend column, the panels, the starter days, and the
command that moves the activities into the cells.
"""

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_schedule import parse_text                          # noqa: E402
from writing_schedule.parser import split_cell as schedule_split  # noqa: E402

from writing_habit import name as namemod                        # noqa: E402
from writing_habit.gui.weekly_table import (SECTION, WeeklyTable,  # noqa: E402
                                            normalize_cell, split_cell)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "my-week.org"

FREE = (
    "| Time        | M  | Tu | W  |\n"
    "|-------------+----+----+----|\n"
    "| 12:15-13:00 | sE | E  | sE |\n"
    "| 17:30-19:00 | eB | eA |    |\n"
    "| 21:00-23:30 | gA | gB | B  |\n"
    "|-------------+----+----+----|\n"
    "| A: DNPH1 docking :safe: |  |  |  |\n"
    "| B: DUSP1 radiation |  |  |  |\n"
    "| E: email @support |  |  |  |\n"
)


@pytest.fixture()
def table():
    return WeeklyTable.from_file(str(EXAMPLE))


def _scheduler(table):
    """Return ``{(offset, start, letter): section}`` as the scheduler reads it."""
    return {(e.offset, e.start, e.letter): e.section
            for e in parse_text(table.to_text()).events}


def _editor(table):
    return {(e.offset, e.start, e.letter): e.section for e in table.events()}


# -- the cell rule -------------------------------------------------------------
@pytest.mark.parametrize("cell", ["gA", "eEM", "sW2", "A", "ga", "gem", " sE ",
                                  "xA", "", "Zebra", "q"])
def test_the_cell_rule_matches_the_schedulers(cell):
    assert split_cell(cell) == schedule_split(cell)


@pytest.mark.parametrize("typed, stored", [
    ("gA", "gA"), ("ea", "EA"), ("a", "A"), (" sEM ", "sEM"), ("", "")])
def test_a_cell_keeps_its_letter_and_raises_the_code(typed, stored):
    assert normalize_cell(typed) == stored


def test_set_cell_keeps_the_activity_letter(table):
    row = table.block_rows[0]
    assert table.set_cell(row, 1, "eA")
    assert table.cell(row, 1) == "eA"
    assert table.set_cell(row, 1, "ea")
    assert table.cell(row, 1) == "EA"


# -- the activity of a block ---------------------------------------------------
def test_a_prefix_beats_the_section(table):
    row = table.block_rows[0]                  # Generative
    table.set_cell(row, 1, "eA")
    block = next(b for b in table.blocks() if b.row == row and b.column == 1)
    assert block.letter == "A"
    assert block.category == "editing"
    assert block.activity_source == "cell"
    assert block.event_section == "Rewriting"


def test_a_legend_default_beats_the_section(table):
    legend = table.legend_rows()[table.legend_rows().__len__() - 1]   # E
    table.set_legend(legend, "E", "email", None, "editing")
    blocks = [b for b in table.blocks() if b.letter == "E"]
    assert {b.category for b in blocks} == {"editing"}
    assert {b.activity_source for b in blocks} == {"legend"}


def test_without_a_header_or_letter_the_block_is_generative():
    table = WeeklyTable(FREE)
    by = {(b.offset, b.start): b for b in table.blocks()}
    assert by[(2, "21:00")].category == "generative"
    assert by[(2, "21:00")].activity_source == "none"
    assert [b.letter for b in table.activity_fallbacks()] == ["B"]


def test_the_editor_and_the_scheduler_agree():
    table = WeeklyTable(FREE)
    assert _editor(table) == _scheduler(table)


def test_they_agree_on_a_sectioned_table_with_overrides(table):
    table.set_cell(table.block_rows[0], 2, "sB")
    table.set_legend(table.legend_rows()[3], "T", "teaching", None, "support")
    assert _editor(table) == _scheduler(table)


def test_the_totals_follow_the_resolved_activity():
    totals = WeeklyTable(FREE).totals()["category"]
    assert totals == {"support": 45 * 3, "editing": 90 * 2, "generative": 150 * 3}


def test_the_canonical_name_spells_the_resolved_activity():
    code = WeeklyTable(FREE).code()
    assert code == "sEeBgA-sEeAgB-sEgB"


def test_clashes_are_found_in_prefixed_cells():
    text = FREE.replace("| 17:30-19:00 |", "| 12:30-19:00 |")
    table = WeeklyTable(text)
    assert table.conflicting_cells()


def test_the_code_without_its_letter_is_what_the_legend_sees():
    table = WeeklyTable(FREE)
    assert table.used_codes() == ["E", "B", "A"]
    assert table.cells_using("A") == 2
    assert table.cells_using("gA") == 2
    assert table.project_info("sE")["activity"] == "support"


def test_prefix_overrides_are_listed(table):
    table.set_cell(table.block_rows[0], 1, "eA")
    table.set_cell(table.block_rows[1], 1, "gA")    # agrees with Generative
    overrides = table.prefix_overrides()
    assert [(b.row, b.column) for b in overrides] == [(table.block_rows[0], 1)]


# -- legend default activities -------------------------------------------------
def test_the_name_module_strips_the_activity_tag():
    assert namemod.parse_legend_cell("E: email @support :safe:") == ("E", "email", "safe")
    assert namemod.parse_legend_cell("E: email :safe: @support") == ("E", "email", "safe")
    assert namemod.legend_activity("E: email @Support") == "support"
    assert namemod.legend_activity("E: me@support.org") is None


def test_set_legend_keeps_the_default_activity():
    table = WeeklyTable(FREE)
    row = table.legend_rows()[2]
    table.set_legend(row, "E", "inbox", "safe")
    assert table.rows[row].cells[0] == "E: inbox @support :safe:"
    table.set_legend(row, "E", "inbox", "safe", None)
    assert table.rows[row].cells[0] == "E: inbox :safe:"


def test_a_new_project_can_carry_a_default():
    table = WeeklyTable(FREE)
    at = table.insert_legend(None, False, "T", "teaching", None, "support")
    assert table.rows[at].cells[0] == "T: teaching @support"
    assert table.legend_defaults()["T"] == "support"


def test_the_first_definition_decides_the_default():
    text = FREE + "| E: again @editing |  |  |  |\n"
    assert WeeklyTable(text).legend_defaults()["E"] == "support"


# -- moving the activity into the cells ----------------------------------------
def test_moving_activities_writes_the_section_letter(table):
    before = _editor(table)
    categories = {(b.offset, b.start, b.letter): b.category for b in table.blocks()}
    changed = table.move_activities_into_cells()
    assert changed == len(table.blocks())
    assert table.cell(table.block_rows[0], 1) == "gA"
    assert table.cell(table.block_rows[2], 1) == "eB"
    assert table.cell(table.block_rows[3], 1) == "sE"
    assert {(b.offset, b.start, b.letter): b.category
            for b in table.blocks()} == categories
    removed = table.remove_section_rows()
    assert removed == 3
    assert not any(r.kind == SECTION for r in table.rows)
    assert {(b.offset, b.start, b.letter): b.category
            for b in table.blocks()} == categories
    assert set(_scheduler(table).values()) == set(before.values())


def test_moving_activities_leaves_legend_defaults_bare():
    table = WeeklyTable(FREE.replace("| 12:15-13:00 |", "| Supporting: |  |  |  |\n| 12:15-13:00 |", 1))
    table.move_activities_into_cells()
    assert table.cell(table.block_rows[0], 2) == "E"        # E is @support


def test_moving_twice_changes_nothing(table):
    table.move_activities_into_cells()
    text = table.to_text()
    assert table.move_activities_into_cells() == 0
    assert table.to_text() == text


# -- plan import ---------------------------------------------------------------
def test_plan_import_stores_the_resolved_activity(tmp_path):
    from writing_habit.db import connect, init_db
    from writing_habit.plan_import import import_org
    path = tmp_path / "free.org"
    path.write_text(FREE)
    con = connect(str(tmp_path / "h.db"))
    init_db(con)
    import_org(con, str(path), "2026-01-19")
    rows = con.execute(
        "SELECT p.code, c.name, b.day, b.start_time FROM plan_block b "
        "JOIN project p USING(project_id) JOIN category c USING(category_id) "
        "ORDER BY b.day, b.start_time").fetchall()
    got = {(code, day, start): cat for code, cat, day, start in rows}
    assert got[("E", "2026-01-20", "12:15")] == "support"     # legend default
    assert got[("B", "2026-01-19", "17:30")] == "editing"     # prefix
    assert got[("A", "2026-01-19", "21:00")] == "generative"
    assert got[("B", "2026-01-21", "21:00")] == "generative"  # fallback
    desc = con.execute("SELECT description FROM project WHERE code='E'").fetchone()[0]
    assert desc == "email"


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


def _index(editor, document_row, column=1):
    return editor.model.index(editor.model._rows.index(document_row), column)


def test_the_cell_editor_writes_the_pressed_letter(editor):
    from writing_habit.gui.table_model import CodeDelegate
    index = _index(editor, editor.table.block_rows[0])
    delegate = CodeDelegate()
    widget = delegate.createEditor(None, None, index)
    try:
        delegate.setEditorData(widget, index)
        assert widget.box.currentText() == "A"
        assert widget.activity() is None
        widget.buttons["e"].setChecked(True)
        delegate.setModelData(widget, editor.model, index)
        assert editor.table.cell(editor.table.block_rows[0], 1) == "eA"
        delegate.setEditorData(widget, index)
        assert widget.buttons["e"].isChecked()
        widget.buttons["s"].setChecked(True)
        assert not widget.buttons["e"].isChecked()
        widget.buttons["s"].setChecked(False)
        delegate.setModelData(widget, editor.model, index)
        assert editor.table.cell(editor.table.block_rows[0], 1) == "A"
        widget.box.setCurrentText("gB")
        delegate.setModelData(widget, editor.model, index)
        assert editor.table.cell(editor.table.block_rows[0], 1) == "gB"
    finally:
        widget.deleteLater()


def test_cells_are_tinted_by_activity(editor):
    from writing_habit.gui.qt import Qt
    from writing_habit.gui.table_model import ACTIVITY_COLOR
    gen = _index(editor, editor.table.block_rows[0])
    sup = _index(editor, editor.table.block_rows[3])
    assert editor.model.data(gen, Qt.BackgroundRole).color().name() == ACTIVITY_COLOR["generative"]
    assert editor.model.data(sup, Qt.BackgroundRole).color().name() == ACTIVITY_COLOR["support"]
    editor.model.setData(gen, "sA")
    assert editor.model.data(gen, Qt.BackgroundRole).color().name() == ACTIVITY_COLOR["support"]
    empty = _index(editor, editor.table.block_rows[0], 6)
    assert editor.model.data(empty, Qt.BackgroundRole) is None


def test_the_tooltip_names_the_activity_and_its_source(editor):
    from writing_habit.gui.qt import Qt
    index = _index(editor, editor.table.block_rows[0])
    assert "Activity: generative (from the section)" in editor.model.data(index, Qt.ToolTipRole)
    editor.model.setData(index, "eA")
    tip = editor.model.data(index, Qt.ToolTipRole)
    assert tip.startswith("A: DNPH1 docking")
    assert "Activity: editing (from the cell)" in tip


def test_the_legend_has_a_default_activity_column(editor):
    from writing_habit.gui.legend_model import ACTIVITY
    from writing_habit.gui.qt import Qt
    model = editor.legend_model
    assert model.headerData(ACTIVITY, Qt.Horizontal) == "Default activity"
    assert model.data(model.index(4, ACTIVITY)) == "none"
    assert model.setData(model.index(4, ACTIVITY), "editing", Qt.EditRole)
    assert "E: email @editing" in editor.table.rows[editor.table.legend_rows()[4]].raw
    assert model.data(model.index(4, ACTIVITY)) == "editing"
    assert "Default activities: E editing" in editor.legend_panel.toPlainText()


def test_insert_project_takes_a_default_activity(editor):
    at = editor.insert_project(above=False, code="C", description="talks",
                               activity="support")
    assert editor.table.rows[at].cells[0] == "C: talks @support"


def test_the_panels_report_overrides_and_fallbacks(editor):
    editor.model.setData(_index(editor, editor.table.block_rows[0]), "eA")
    assert "overrides their section" in editor.legend_panel.toPlainText()
    free = WeeklyTable(FREE)
    editor.table = free
    editor.model.set_table(free)
    editor.legend_model.set_table(free)
    editor.refresh()
    assert "counted as generative" in editor.totals_panel.toPlainText()


def test_the_more_menu_moves_activities_into_cells(editor):
    assert editor.more_button.isEnabled()
    lines = []
    editor.logged.connect(lines.append)
    changed = editor.move_activities_into_cells(delete_sections=True)
    assert changed == 22
    assert not any(r.kind == SECTION for r in editor.table.rows)
    assert editor.model.rowCount() == len(editor.table.block_rows)
    assert "deleted 3 section row(s)" in lines[-1]
    assert editor.save_button.isEnabled()
    assert editor.table.code() == WeeklyTable.from_file(str(EXAMPLE)).code()


@pytest.mark.parametrize("style, first", [("morning", "05:30-07:30"),
                                          ("evening", "12:15-13:00"),
                                          ("split", "06:00-07:30")])
def test_new_from_template_offers_starter_days(editor, style, first):
    editor.scaffold(3, style)
    blocks = editor.table.block_rows
    assert len(blocks) == 3
    assert editor.table.rows[blocks[0]].parsed == tuple(first.split("-"))


def test_the_starter_day_is_asked_for(editor, monkeypatch):
    from writing_habit.gui.qt import QtWidgets
    monkeypatch.setattr(QtWidgets.QInputDialog, "getInt",
                        staticmethod(lambda *a, **k: (2, True)))
    monkeypatch.setattr(QtWidgets.QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: ("Evening writer (three blocks)", True)))
    editor.scaffold()
    assert editor.table.rows[editor.table.block_rows[-1]].parsed == ("21:00", "23:30")
