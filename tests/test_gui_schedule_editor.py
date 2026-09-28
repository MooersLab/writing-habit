"""The read-only weekly-table grid of build step 4.

The document itself is covered by test_gui_weekly_table.py, so these tests cover
the seam between the document and the widgets: what the grid shows, what it
refuses (every edit, until step 5), and what the four panels report.
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit.gui.qt import Qt, QtWidgets                    # noqa: E402
from writing_habit.gui.schedule_editor import ScheduleEditor      # noqa: E402
from writing_habit.gui.table_model import WeeklyTableModel        # noqa: E402
from writing_habit.gui.weekly_table import WeeklyTable            # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "my-week.org"
CANONICAL = ROOT / "templates" / "5gAeA.org"

CLASH = (
    "| Time <l>    | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| Generative: |    |    |\n"
    "| 04:00-05:30 | A  |    |\n"
    "| Rewriting:  |    |    |\n"
    "| 05:00-06:30 | B  | A  |\n"
    "|-------------+----+----|\n"
    "| A: one :safe: |  |  |\n"
    "| B: two        |  |  |\n"
)


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture()
def blank_settings(monkeypatch):
    store = {}
    monkeypatch.setattr("writing_habit.gui.settings.get",
                        lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr("writing_habit.gui.schedule_editor.settings.get",
                        lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.schedule_editor.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    return store


@pytest.fixture()
def model(app):
    return WeeklyTableModel(WeeklyTable.from_file(str(EXAMPLE)))


def test_the_grid_shows_the_sections_and_the_blocks(model):
    table = model.table
    assert model.rowCount() == len([r for r in table.rows
                                    if r.kind in ("section", "block")])
    assert model.columnCount() == 1 + len(table.columns)


def test_the_columns_are_the_days_the_header_names(model):
    headers = [model.headerData(i, Qt.Horizontal, Qt.DisplayRole)
               for i in range(model.columnCount())]
    assert headers == ["Time", "M", "Tu", "W", "Th", "F", "Sa"]


def test_a_block_row_shows_its_time_and_its_codes(model):
    rows = {model.data(model.index(r, 0), Qt.DisplayRole): r
            for r in range(model.rowCount())}
    row = rows["04:00-05:30"]
    codes = [model.data(model.index(row, c), Qt.DisplayRole)
             for c in range(1, model.columnCount())]
    assert codes == ["A", "B", "A", "B", "W", ""]


def test_a_section_row_is_bold_and_names_only_itself(model):
    rows = {model.data(model.index(r, 0), Qt.DisplayRole): r
            for r in range(model.rowCount())}
    row = rows["Generative"]
    assert model.is_section(row)
    assert model.data(model.index(row, 1), Qt.DisplayRole) == ""
    assert model.data(model.index(row, 0), Qt.FontRole).bold()


def test_a_code_cell_explains_itself_through_the_legend(model):
    rows = {model.data(model.index(r, 0), Qt.DisplayRole): r
            for r in range(model.rowCount())}
    row = rows["13:15-14:45"]
    tip = model.data(model.index(row, 1), Qt.ToolTipRole)
    assert tip == "E: email\nRisk: not tagged"
    generative = rows["04:00-05:30"]
    assert model.data(model.index(generative, 1), Qt.ToolTipRole) == \
        "A: DNPH1 docking\nRisk: safe"


def test_a_block_cell_is_editable_and_a_section_row_is_not(model):
    rows = {model.data(model.index(r, 0), Qt.DisplayRole): r
            for r in range(model.rowCount())}
    block = rows["04:00-05:30"]
    assert model.flags(model.index(block, 1)) & Qt.ItemIsEditable
    assert not (model.flags(model.index(block, 0)) & Qt.ItemIsEditable)   # the time
    section = rows["Generative"]
    assert not (model.flags(model.index(section, 1)) & Qt.ItemIsEditable)


def _tinted(model, color):
    return [(r, c)
            for r in range(model.rowCount())
            for c in range(1, model.columnCount())
            if (model.data(model.index(r, c), Qt.BackgroundRole) or None)
            and model.data(model.index(r, c), Qt.BackgroundRole).color().name()
            == color]


def test_a_clashing_cell_is_tinted(app):
    from writing_habit.gui.table_model import CONFLICT_COLOR, SECTION_COLOR

    model = WeeklyTableModel(WeeklyTable(CLASH))
    tinted = _tinted(model, CONFLICT_COLOR)
    assert len(tinted) == 2
    assert all(c == 1 for _r, c in tinted)          # both blocks are on Monday
    # the section rows are shaded, and that shading is a different color
    assert _tinted(model, SECTION_COLOR)
    assert not set(_tinted(model, SECTION_COLOR)) & set(tinted)


def test_no_cell_is_tinted_when_nothing_clashes(app):
    from writing_habit.gui.table_model import CONFLICT_COLOR

    model = WeeklyTableModel(WeeklyTable(CLASH.replace("05:00-06:30", "05:30-07:00")))
    assert _tinted(model, CONFLICT_COLOR) == []


def test_the_editor_opens_a_table_and_fills_its_panels(app, blank_settings, tmp_path):
    editor = ScheduleEditor()
    opened = []
    editor.opened.connect(opened.append)
    editor.open(str(CANONICAL))
    try:
        assert opened == [str(CANONICAL)]
        assert editor.path_label.text() == str(CANONICAL)
        assert editor.reload_button.isEnabled()
        assert "5gAeA.org" in editor.name_panel.toPlainText()
        assert "No overlapping time blocks" in editor.clash_panel.toPlainText()
        assert "Planned minutes" in editor.totals_panel.toPlainText()
        assert "resolves to one legend entry" in editor.legend_panel.toPlainText()
        assert blank_settings["table_dir"] == str(CANONICAL.parent)
    finally:
        editor.close()


def test_a_week_without_a_name_says_why(app, blank_settings, tmp_path):
    table = tmp_path / "multi.org"
    table.write_text(
        "| Time <l>    | M  |\n"
        "|-------------+----|\n"
        "| Supporting: |    |\n"
        "| 13:15-14:45 | EM |\n"
        "|-------------+----|\n"
        "| EM: email   |    |\n",
        encoding="utf-8")
    editor = ScheduleEditor()
    editor.open(str(table))
    try:
        text = editor.name_panel.toPlainText()
        assert "no canonical file name" in text
        assert "single-letter alias" in text
    finally:
        editor.close()


def test_the_clash_tab_counts_what_it_found(app, blank_settings, tmp_path):
    table = tmp_path / "clash.org"
    table.write_text(CLASH, encoding="utf-8")
    editor = ScheduleEditor()
    editor.open(str(table))
    try:
        assert editor.panels.tabText(1) == "Clashes (1)"
        assert "overlaps" in editor.clash_panel.toPlainText()
    finally:
        editor.close()


def test_the_view_explains_what_an_edit_costs(app, blank_settings):
    editor = ScheduleEditor()
    try:
        assert "one line" in editor.note.text()
    finally:
        editor.close()


# -- build step 5: editing, saving, and the scaffold -----------------------

def test_setting_a_cell_writes_through_to_the_document(model):
    rows = {model.data(model.index(r, 0), Qt.DisplayRole): r
            for r in range(model.rowCount())}
    index = model.index(rows["04:00-05:30"], 6)          # the Saturday cell
    edits = []
    model.edited.connect(lambda: edits.append(True))
    assert model.setData(index, "b", Qt.EditRole)        # lower case is accepted
    assert model.data(index, Qt.DisplayRole) == "B"
    assert model.table.dirty and edits == [True]


def test_a_refused_edit_reports_false(model):
    rows = {model.data(model.index(r, 0), Qt.DisplayRole): r
            for r in range(model.rowCount())}
    section = model.index(rows["Generative"], 1)
    assert model.setData(section, "A", Qt.EditRole) is False
    time_cell = model.index(rows["04:00-05:30"], 0)
    assert model.setData(time_cell, "05:00-06:00", Qt.EditRole) is False


def test_the_cell_editor_offers_the_legend_codes_and_a_blank(app, model):
    from writing_habit.gui.table_model import CodeDelegate

    assert model.codes() == ["", "A", "B", "W", "T", "E"]
    delegate = CodeDelegate()
    editor = delegate.createEditor(None, None, model.index(1, 1))
    try:
        assert [editor.itemText(i) for i in range(editor.count())] == model.codes()
    finally:
        editor.deleteLater()


def test_the_legend_model_edits_the_risk_tag(app):
    from writing_habit.gui.legend_model import CODE, DESCRIPTION, LegendModel, RISK

    table = WeeklyTable.from_file(str(EXAMPLE))
    legend = LegendModel(table)
    codes = [legend.data(legend.index(r, CODE)) for r in range(legend.rowCount())]
    assert codes == ["A", "B", "W", "T", "E"]
    assert legend.data(legend.index(2, RISK)) == "risky"      # W is speculative
    assert legend.data(legend.index(4, RISK)) == "none"       # E carries no tag

    assert legend.setData(legend.index(4, RISK), "risky", Qt.EditRole)
    assert table.legend()["E"][1] == "speculative"
    assert ":risky:" in table.rows[legend.document_row(4)].raw

    assert legend.setData(legend.index(4, DESCRIPTION), "electronic mail", Qt.EditRole)
    assert table.legend()["E"][0] == "electronic mail"


def test_saving_writes_the_file_and_clears_the_marker(app, blank_settings, tmp_path):
    source = tmp_path / "week.org"
    source.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    editor = ScheduleEditor()
    saved = []
    editor.saved.connect(saved.append)
    editor.open(str(source))
    try:
        assert not editor.save_button.isEnabled()        # nothing to save yet
        row = editor.model.index(1, 6)
        editor.model.setData(row, "B", Qt.EditRole)
        assert editor.save_button.isEnabled()
        assert editor.path_label.text().endswith("*")

        editor.save()
        assert saved == [str(source)]
        assert not editor.path_label.text().endswith("*")
        assert source.read_text(encoding="utf-8") == editor.table.to_text()
    finally:
        editor.close()


def test_the_suggested_name_is_the_canonical_one(app, blank_settings):
    editor = ScheduleEditor()
    editor.open(str(CANONICAL))
    try:
        assert editor.suggested_name() == "5gAeA.org"
    finally:
        editor.close()


def test_the_scaffold_starts_a_blank_week(app, blank_settings):
    editor = ScheduleEditor()
    try:
        editor.scaffold(3)
        assert editor.table is not None
        assert list(editor.table.legend()) == ["A", "B", "C"]
        assert editor.table.blocks() == []               # a scaffold plans nothing
        assert editor.table.dirty
        assert editor.save_button.isEnabled()
        assert not editor.reload_button.isEnabled()      # it came from no file
        assert "unsaved" in editor.path_label.text()
    finally:
        editor.close()


def test_the_rename_button_follows_the_state_of_the_name(app, blank_settings, tmp_path):
    """It offers itself only when the file is saved and misnamed."""
    source = tmp_path / "week.org"
    source.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    editor = ScheduleEditor()
    editor.open(str(source))
    try:
        assert editor.rename_button.isEnabled()          # saved, and misnamed

        editor.model.setData(editor.model.index(1, 6), "B", Qt.EditRole)
        assert not editor.rename_button.isEnabled()      # unsaved edits first
        editor.save()
        assert editor.rename_button.isEnabled()

        path = editor.rename_to_canonical()
        assert path is not None and path.endswith(".org")
        assert not editor.rename_button.isEnabled()      # the name now matches
        assert editor.table.name_matches_code()
    finally:
        editor.close()


def test_a_canonically_named_table_offers_no_rename(app, blank_settings, tmp_path):
    source = tmp_path / "5gAeA.org"
    source.write_text(CANONICAL.read_text(encoding="utf-8"), encoding="utf-8")
    editor = ScheduleEditor()
    editor.open(str(source))
    try:
        assert not editor.rename_button.isEnabled()
    finally:
        editor.close()
