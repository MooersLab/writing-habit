"""The Legend panel's Project and Deadline columns, and the split action."""

import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")
pytest.importorskip("PyQt5", reason="the graphical extra is not installed")

from writing_habit.gui.weekly_table import WeeklyTable          # noqa: E402

OCT5 = date(2026, 10, 5)
TABLE = (
    "| Time <l>    | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| 04:00-05:30 | gA | eZ |\n"
    "|-------------+----+----|\n"
    "| A: 1003molGraphicsR01, Need a new NIH institute, :safe: |  |  |\n"
    "| B: 1006AIrxOpt, NSF Dec 15 :safe:  |  |  |\n"
    "| E: email @support                  |  |  |\n"
    "| X: 0374qflip :risky:               |  |  |\n"
    "| Z: 1008ToolsForQCrOfRNA 2026-10-05 :safe: |  |  |\n"
)


def test_tidy_lists_changes_without_writing_until_asked():
    table = WeeklyTable(TABLE)
    changes = table.tidy_legend(OCT5)
    assert [(c[1], c[3], c[4], c[5]) for c in changes] == [
        ("A", "1003molGraphicsR01", None, "Need a new NIH institute"),
        ("B", "1006AIrxOpt", "2026-12-15", "NSF"),
    ]
    assert not table.dirty
    table.tidy_legend(OCT5, apply=True)
    text = table.to_text()
    assert "| A: 1003molGraphicsR01 :safe:" in text
    assert "B: 1006AIrxOpt 2026-12-15 :safe:" in text
    assert "E: email @support" in text          # the default activity survives
    assert table.tidy_legend(OCT5) == []        # a second pass changes nothing


@pytest.fixture()
def model(qapp):
    from writing_habit.gui.legend_model import LegendModel
    return LegendModel(WeeklyTable(TABLE))


def test_project_and_deadline_are_separate_columns(model):
    from writing_habit.gui.legend_model import DEADLINE, HEADERS, PROJECT
    from writing_habit.gui.qt import Qt
    assert HEADERS[PROJECT] == "Project" and HEADERS[DEADLINE] == "Deadline"
    z = model.rowCount() - 1
    assert model.index(z, PROJECT).data(Qt.DisplayRole) == "1008ToolsForQCrOfRNA"
    assert model.index(z, DEADLINE).data(Qt.DisplayRole) == "2026-10-05"
    assert model.index(3, DEADLINE).data(Qt.DisplayRole) == ""


def test_editing_one_column_keeps_the_other(model):
    from writing_habit.gui.legend_model import DEADLINE, PROJECT
    from writing_habit.gui.qt import Qt
    z = model.rowCount() - 1
    assert model.setData(model.index(z, DEADLINE), "2026-11-30", Qt.EditRole)
    assert model.setData(model.index(z, PROJECT), "1008QCrTools", Qt.EditRole)
    assert model.entry(z)[1] == "1008QCrTools 2026-11-30"
    assert model.entry(z)[2] == "safe"
    assert model.setData(model.index(z, DEADLINE), "", Qt.EditRole)
    assert model.entry(z)[1] == "1008QCrTools"


@pytest.mark.parametrize("bad", ["Nov 30", "2026-13-01", "2026-11-31"])
def test_a_deadline_that_is_not_a_date_is_refused(model, bad):
    from writing_habit.gui.legend_model import DEADLINE
    from writing_habit.gui.qt import Qt
    z = model.rowCount() - 1
    assert not model.setData(model.index(z, DEADLINE), bad, Qt.EditRole)
    assert model.entry(z)[1] == "1008ToolsForQCrOfRNA 2026-10-05"


def test_the_editor_action_splits_the_open_table(qapp, tmp_path, monkeypatch):
    from writing_habit.gui import settings
    from writing_habit.gui.schedule_editor import ScheduleEditor
    store = {}
    monkeypatch.setattr(settings, "get", lambda k: store.get(k, settings.DEFAULTS[k]))
    monkeypatch.setattr(settings, "put", lambda k, v: store.__setitem__(k, v))
    path = tmp_path / "Oct5.org"
    path.write_text(TABLE, encoding="utf-8")
    editor = ScheduleEditor()
    editor.open(str(path))
    assert editor.tidy_legend(confirm=False, reference=OCT5) is None
    assert editor.tidy_legend(confirm=True, reference=OCT5) == 2
    assert editor.table.dirty
    assert path.read_text(encoding="utf-8") == TABLE     # nothing written until saved
