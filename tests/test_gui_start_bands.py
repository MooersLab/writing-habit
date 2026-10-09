"""Rows that start at the same time share a shade, and the groups alternate.

The grid used to alternate gray and white row by row, which split the choices
for one start time across two shades. The model now shades every other run of
equal start times instead.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")
pytest.importorskip("PyQt5", reason="the graphical extra is not installed")

from writing_habit.gui.weekly_table import WeeklyTable  # noqa: E402

TABLE = (
    "| Time        | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| 05:00-05:30 |    |    |\n"
    "| 05:00-06:00 | gA |    |\n"
    "| 05:15-05:45 |    |    |\n"
    "| 05:15-06:15 |    |    |\n"
    "| Supporting: |    |    |\n"
    "| 05:15-07:15 |    |    |\n"
    "| 05:30-06:00 |    |    |\n"
    "|-------------+----+----|\n"
    "| A: one |  |  |\n"
)


@pytest.fixture()
def model(qtbot):
    from writing_habit.gui.table_model import WeeklyTableModel
    return WeeklyTableModel(WeeklyTable(TABLE))


def _shade(model, row, column=0):
    from writing_habit.gui.qt import Qt
    brush = model.data(model.index(row, column), Qt.BackgroundRole)
    return None if brush is None else brush.color().name()


def test_groups_of_equal_start_alternate(model):
    from writing_habit.gui.table_model import BAND_COLOR
    times = [model.data(model.index(r, 0)) for r in range(model.rowCount())]
    shades = dict(zip(times, (_shade(model, r) for r in range(model.rowCount()))))
    assert shades["05:00-05:30"] is None
    assert shades["05:00-06:00"] is None
    assert shades["05:15-05:45"] == BAND_COLOR
    assert shades["05:15-06:15"] == BAND_COLOR
    assert shades["05:15-07:15"] == BAND_COLOR      # a section row does not break a run
    assert shades["05:30-06:00"] is None


def test_empty_day_cells_take_the_group_shade(model):
    from writing_habit.gui.table_model import ACTIVITY_COLOR, BAND_COLOR
    assert _shade(model, 2, 2) == BAND_COLOR
    assert _shade(model, 1, 1) == ACTIVITY_COLOR["generative"]   # a filled cell keeps its tint


def test_the_view_no_longer_alternates_row_by_row(qtbot, monkeypatch):
    monkeypatch.setattr("writing_habit.gui.settings.get", lambda key: "")
    monkeypatch.setattr("writing_habit.gui.settings.put", lambda key, value: None)
    from writing_habit.gui.schedule_editor import ScheduleEditor
    editor = ScheduleEditor()
    qtbot.addWidget(editor)
    assert not editor.view.alternatingRowColors()
