"""Shifting a block in time, and pushing the later blocks it overlaps down.

The document model needs no Qt, so these tests run wherever the package runs.
"""

import pytest

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit.gui.weekly_table import WeeklyTable              # noqa: E402

WEEK = (
    "|        Time | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| 04:00-05:00 | gA |    |\n"
    "| 05:00-06:00 | eB |    |\n"
    "| 08:00-09:00 | gA | gB |\n"
    "|-------------+----+----|\n"
    "| A: one 2026-11-01 :safe: |  |  |\n"
    "| B: two 2026-12-01 :risky: |  |  |\n"
)

SECTIONED = (
    "|        Time | M  |\n"
    "|-------------+----|\n"
    "| Writing     |    |\n"
    "| 04:00-05:00 | A  |\n"
    "| Editing     |    |\n"
    "| 06:00-07:00 |    |\n"
    "|-------------+----|\n"
    "| A: one :safe: |  |\n"
)


def _monday(table):
    """Return the Monday blocks as ``[(start, end, cell)]``, by start."""
    return sorted((b.start, b.end, table.cell(b.row, b.column))
                  for b in table.blocks() if b.offset == 0)


def test_a_shift_moves_one_block_and_keeps_its_length():
    table = WeeklyTable(WEEK)
    row = table.find_block_row("08:00", "09:00")
    (new_row, column), moves = table.shift_block(row, 1, 15)
    assert table.rows[new_row].parsed == ("08:15", "09:15")
    assert table.cell(new_row, column) == "gA"
    assert len(moves) == 1
    # Tuesday's block in the old row stays where it was.
    assert table.cell(table.find_block_row("08:00", "09:00"), 2) == "gB"


def test_a_shift_later_pushes_the_overlapped_block_down():
    table = WeeklyTable(WEEK)
    row = table.find_block_row("04:00", "05:00")
    table.shift_block(row, 1, 60)
    assert _monday(table) == [("05:00", "06:00", "gA"),
                              ("06:00", "07:00", "eB"),
                              ("08:00", "09:00", "gA")]


def test_without_push_a_shift_leaves_a_clash():
    table = WeeklyTable(WEEK)
    row = table.find_block_row("04:00", "05:00")
    table.shift_block(row, 1, 30, push=False)
    assert _monday(table) == [("04:30", "05:30", "gA"),
                              ("05:00", "06:00", "eB"),
                              ("08:00", "09:00", "gA")]
    assert table.conflicting_cells()


def test_a_push_chain_stops_at_the_first_gap():
    table = WeeklyTable(WEEK)
    row = table.find_block_row("05:00", "06:00")
    table.shift_block(row, 1, 150)
    # 07:30 to 08:30 pushes the 08:00 block to 08:30-09:30; the 04:00 block,
    # which starts earlier, stays.
    assert _monday(table) == [("04:00", "05:00", "gA"),
                              ("07:30", "08:30", "eB"),
                              ("08:30", "09:30", "gA")]


def test_a_block_that_jumps_past_another_leaves_it_alone():
    table = WeeklyTable(WEEK)
    row = table.find_block_row("04:00", "05:00")
    table.shift_block(row, 1, 120)
    assert _monday(table) == [("05:00", "06:00", "eB"),
                              ("06:00", "07:00", "gA"),
                              ("08:00", "09:00", "gA")]


def test_a_shift_earlier_never_moves_an_earlier_block():
    table = WeeklyTable(WEEK)
    row = table.find_block_row("05:00", "06:00")
    table.shift_block(row, 1, -15)
    assert _monday(table) == [("04:00", "05:00", "gA"),
                              ("04:45", "05:45", "eB"),
                              ("08:00", "09:00", "gA")]


def test_placing_a_long_block_pushes_the_later_ones_down():
    """The case from the request: a two-hour block placed at 03:00 overlaps
    the block already at 04:00, which moves down rather than being deleted."""
    table = WeeklyTable(WEEK)
    table.place_block(0, "03:00", "05:00", "gB", push=True)
    assert _monday(table) == [("03:00", "05:00", "gB"),
                              ("05:00", "06:00", "gA"),
                              ("06:00", "07:00", "eB"),
                              ("08:00", "09:00", "gA")]


def test_placing_without_push_keeps_the_old_behaviour():
    table = WeeklyTable(WEEK)
    table.place_block(0, "03:00", "05:00", "gB")
    assert ("04:00", "05:00", "gA") in _monday(table)


@pytest.mark.parametrize("delta", [-300, 24 * 60])
def test_a_shift_that_leaves_the_day_is_refused(delta):
    table = WeeklyTable(WEEK)
    before = table.to_text()
    row = table.find_block_row("04:00", "05:00")
    with pytest.raises(ValueError):
        table.shift_block(row, 1, delta)
    assert table.to_text() == before


def test_a_push_past_midnight_is_refused_and_changes_nothing():
    late = WEEK.replace("08:00-09:00", "22:00-23:30")
    table = WeeklyTable(late)
    before = table.to_text()
    row = table.find_block_row("05:00", "06:00")
    with pytest.raises(ValueError, match="midnight"):
        table.shift_block(row, 1, 17 * 60)
    assert table.to_text() == before


def test_an_empty_cell_cannot_shift():
    table = WeeklyTable(WEEK)
    with pytest.raises(ValueError):
        table.shift_block(table.find_block_row("04:00", "05:00"), 2, 15)


def test_a_section_activity_is_written_into_the_moved_cell():
    """A block that took its activity from the Writing header keeps it under
    the Editing header, so a shift never changes what the block counts as."""
    table = WeeklyTable(SECTIONED)
    row = table.find_block_row("04:00", "05:00")
    (new_row, column), _moves = table.shift_block(row, 1, 120)
    assert table.cell(new_row, column) == "gA"
    block = table.block_at(new_row, column)
    assert block.category == "generative"


def test_a_shift_keeps_every_other_line():
    table = WeeklyTable(WEEK)
    row = table.find_block_row("08:00", "09:00")
    table.shift_block(row, 1, 15)
    text = table.to_text()
    assert "| A: one 2026-11-01 :safe: |" in text
    assert "| 05:00-06:00 | eB |    |" in text
