"""The block timer button: time left, the review prompt, and the next block."""

import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

MONDAY = dt.date(2026, 10, 12)

WEEK = (
    "|        Time | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| 05:00-06:30 | gA |    |\n"
    "| 07:00-08:00 | eB |    |\n"
    "|-------------+----+----|\n"
    "| A: one 2026-11-01 :safe: |  |  |\n"
    "| B: two 2026-12-01 :safe: |  |  |\n"
)


def _state(hour, minute, second=0, day=0, monday=MONDAY):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    from writing_habit.gui.block_timer import timer_state
    from writing_habit.gui.weekly_table import WeeklyTable
    now = dt.datetime.combine(MONDAY + dt.timedelta(days=day), dt.time(hour, minute, second))
    return timer_state(WeeklyTable(WEEK).blocks(), monday, now)


def test_inside_a_block_it_counts_down():
    state = _state(5, 48)
    assert state.kind == "live"
    assert state.text == "A 05:00-06:30, 42 min left"
    assert _state(5, 0).text.endswith("1 h 30 min left")


def test_a_part_minute_rounds_up():
    assert _state(5, 48, 30).minutes == 42


def test_the_last_minutes_turn_warm():
    assert _state(6, 26).kind == "ending"


def test_after_a_block_it_offers_the_review():
    state = _state(6, 40)
    assert state.kind == "review"
    assert state.text == "A block ended. Review it"
    assert state.block.letter == "A"


def test_between_blocks_it_names_the_next_one():
    state = _state(4, 30)
    assert (state.kind, state.text) == ("next", "Next block A at 05:00, in 30 min")
    assert _state(6, 50).text == "Next block B at 07:00, in 10 min"


def test_after_the_last_block_and_on_other_days():
    assert _state(20, 0).text == "No more blocks today"
    assert _state(5, 30, day=1).text == "No more blocks today"
    assert _state(5, 30, day=9).kind == "idle"
    assert _state(5, 30, monday=None).kind == "idle"


@pytest.fixture()
def editor(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    store = {}
    monkeypatch.setattr("writing_habit.gui.settings.get", lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    widget.today = lambda: dt.date(2026, 10, 14)
    qtbot.addWidget(widget)
    path = tmp_path / "Oct12.org"
    path.write_text(WEEK, encoding="utf-8")
    widget.open(str(path))
    widget.set_hour_view(True)
    return widget


def test_the_button_selects_the_live_block(editor):
    timer = editor.block_timer
    timer.now = lambda: dt.datetime(2026, 10, 12, 6, 0)
    timer.update_state()
    assert timer.text() == "A 05:00-06:30, 30 min left"
    assert timer.isEnabled()
    timer.click()
    index = editor.hour_view.currentIndex()
    assert (index.row(), index.column()) == (5, 1)


def test_the_button_opens_the_review_after_a_block(editor):
    timer = editor.block_timer
    timer.now = lambda: dt.datetime(2026, 10, 12, 6, 35)
    timer.update_state()
    opened = []
    editor.run_review = lambda dialog: opened.append(dialog)
    timer.click()
    assert opened and opened[0].panel.block().letter == "A"


def test_the_button_follows_an_edit(editor):
    timer = editor.block_timer
    timer.now = lambda: dt.datetime(2026, 10, 12, 6, 0)
    editor.hour_view.setCurrentIndex(editor.hour_model.index(5, 1))
    editor.shift_selected(60)              # A now runs 06:00-07:30
    assert timer.text() == "A 06:00-07:30, 1 h 30 min left"
