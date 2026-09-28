"""The grid gives its width to the seven days, evenly.

A day cell holds one letter, so sizing every column to its contents collapsed
the six left-hand columns to the width of their headers, and a stretching last
section handed all the width they gave up to Sunday. The Time column still
sizes to its text, because "04:00-05:30" has a natural width, and the day
columns share the rest.
"""
from __future__ import annotations

import pytest

from writing_habit.gui.qt import QtWidgets

TABLE = """#+TITLE: A week

| Time <l>    | M  | Tu | W  | Th | F  | Sa | Su |
|-------------+----+----+----+----+----+----+----|
| Generative: |    |    |    |    |    |    |    |
| 04:00-05:30 | G  | G  | G  | G  | G  |    | G  |
| 09:15-10:45 |    |    |    |    |    |    |    |
|-------------+----+----+----+----+----+----+----|
| G: the grant :safe: |  |  |  |  |  |  |  |
"""


@pytest.fixture
def editor(qtbot, monkeypatch, tmp_path):
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
    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    widget.resize(900, 500)
    widget.open(str(path))
    widget.show()
    qtbot.waitExposed(widget)
    widget.source_path = path
    return widget


def day_widths(editor):
    header = editor.view.horizontalHeader()
    return [header.sectionSize(c) for c in range(1, editor.model.columnCount())]


def test_the_seven_days_are_equal(editor):
    """Every day column gets the same width."""
    widths = day_widths(editor)
    assert len(widths) == 7
    assert len(set(widths)) <= 2, widths      # Qt may leave one pixel over
    assert max(widths) - min(widths) <= 1


def test_no_day_column_is_collapsed(editor):
    """None of them shrinks to the width of a single letter."""
    assert min(day_widths(editor)) > 30


def test_sunday_is_not_wider_than_the_rest(editor):
    """The last section no longer absorbs the leftover width."""
    widths = day_widths(editor)
    assert widths[-1] <= min(widths) + 1


def test_the_time_column_fits_its_text(editor):
    """Time sizes to its contents rather than sharing the stretch."""
    header = editor.view.horizontalHeader()
    assert header.sectionResizeMode(0) == QtWidgets.QHeaderView.ResizeToContents
    metrics = editor.view.fontMetrics()
    assert header.sectionSize(0) >= metrics.horizontalAdvance("04:00-05:30")


def test_the_days_stay_equal_after_a_reload(editor):
    """The complaint was about reloading, so the reload path is checked."""
    editor.reload()
    widths = day_widths(editor)
    assert max(widths) - min(widths) <= 1
    assert min(widths) > 30


def test_the_columns_fill_the_view(editor):
    """Time plus the seven days account for the whole viewport, with no gap."""
    header = editor.view.horizontalHeader()
    total = header.sectionSize(0) + sum(day_widths(editor))
    assert abs(total - editor.view.viewport().width()) <= 1


def test_the_days_stay_equal_after_a_resize(editor, qtbot):
    """Widening keeps them even and hands them the new width.

    The view is resized rather than the window, because the offscreen platform
    used for the headless run does not propagate a window size hint down to it.
    """
    before = day_widths(editor)
    editor.view.setFixedWidth(editor.view.width() + 600)
    qtbot.wait(10)
    after = day_widths(editor)
    assert max(after) - min(after) <= 1
    assert sum(after) > sum(before)


def test_the_legend_gives_its_width_to_the_description(editor):
    """Code and risk take what they need, and the description takes the rest."""
    from writing_habit.gui.legend_model import CODE, DESCRIPTION, RISK

    header = editor.legend_view.horizontalHeader()
    assert header.sectionResizeMode(CODE) == QtWidgets.QHeaderView.ResizeToContents
    assert header.sectionResizeMode(DESCRIPTION) == QtWidgets.QHeaderView.Stretch
    assert header.sectionResizeMode(RISK) == QtWidgets.QHeaderView.ResizeToContents
    assert header.sectionSize(DESCRIPTION) > header.sectionSize(RISK)


def test_a_scaffolded_table_is_laid_out_too(editor, monkeypatch):
    """The New from template path uses the same sizing as Open."""
    editor.scaffold(3)
    widths = day_widths(editor)
    assert max(widths) - min(widths) <= 1
    assert min(widths) > 30
