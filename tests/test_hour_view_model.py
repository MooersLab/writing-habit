"""The document side of the hour view: picker ranges, placing and clearing a
block, the blocks by day and hour, the two-hour break rule, and dropping the
unused rows. None of these tests needs Qt.
"""

from pathlib import Path

import pytest

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_schedule import parse_text                            # noqa: E402

from writing_habit.gui.weekly_table import (BLOCK, PICK_MAX,       # noqa: E402
                                            WeeklyTable, picker_ranges)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "my-week.org"

#: A sorted table of candidate rows with no section headers.
CANDIDATES = (
    "#+TITLE: candidates\n"
    "|        Time | M  | Tu | W |\n"
    "|-------------+----+----+---|\n"
    "| 04:00-05:00 |    |    |   |\n"
    "| 04:00-06:00 | gA |    |   |\n"
    "| 06:15-07:00 |    | eB |   |\n"
    "| 09:00-10:00 |    |    |   |\n"
    "| 13:00-14:00 |    |    |   |\n"
    "|-------------+----+----+---|\n"
    "| A: one 2026-11-01 :safe: |  |  |  |\n"
    "| B: two 2026-12-01 :risky: |  |  |  |\n"
    "\n"
    "Text after the table.\n"
)


@pytest.fixture()
def table():
    return WeeklyTable(CANDIDATES)


def _times(table):
    return [tuple(table.rows[i].parsed) for i in table.block_rows]


# -- picker ranges -------------------------------------------------------------
def test_the_picker_offers_four_starts_by_eight_lengths():
    grid = picker_ranges(9)
    assert len(grid) == 4 and all(len(row) == 8 for row in grid)
    assert [row[0][0] for row in grid] == ["09:00", "09:15", "09:30", "09:45"]
    assert [end for _s, end in grid[0]] == [
        "09:15", "09:30", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00"]
    assert grid[3][7] == ("09:45", "11:45")


def test_no_range_is_longer_than_two_hours():
    for hour in range(24):
        for row in picker_ranges(hour):
            for item in row:
                if item is not None:
                    start, end = item
                    minutes = (int(end[:2]) * 60 + int(end[3:])
                               - int(start[:2]) * 60 - int(start[3:]))
                    assert 15 <= minutes <= PICK_MAX
                    assert minutes % 15 == 0


def test_ranges_past_midnight_are_disabled():
    grid = picker_ranges(23)
    assert grid[0][1] == ("23:00", "23:30")
    assert grid[3][0] is None                   # 23:45-24:00
    assert all(item is None for item in grid[3])
    assert grid[0][3] is None                   # 23:00-24:00


# -- placing and clearing ------------------------------------------------------
def test_placing_on_an_existing_row_writes_its_cell_only(table):
    before = table.to_text().splitlines()
    row, inserted = table.place_block(2, "09:00", "10:00", "gA")
    assert inserted is False
    after = table.to_text().splitlines()
    assert len(after) == len(before)
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(changed) == 1
    assert "| gA" in after[changed[0]]
    assert table.rows[row].parsed == ("09:00", "10:00")


def test_a_new_range_inserts_one_row_in_start_order(table):
    before = table.to_text().splitlines()
    row, inserted = table.place_block(0, "09:15", "10:45", "eB")
    assert inserted is True
    assert table.rows[row].kind == BLOCK
    assert len(table.to_text().splitlines()) == len(before) + 1
    assert _times(table) == [("04:00", "05:00"), ("04:00", "06:00"),
                             ("06:15", "07:00"), ("09:00", "10:00"),
                             ("09:15", "10:45"), ("13:00", "14:00")]


def test_a_range_earlier_than_every_row_goes_first(table):
    table.place_block(1, "03:00", "04:00", "gA")
    assert _times(table)[0] == ("03:00", "04:00")


def test_a_range_later_than_every_row_goes_last(table):
    table.place_block(1, "21:00", "22:30", "sB")
    assert _times(table)[-1] == ("21:00", "22:30")


def test_the_scheduler_reads_a_placed_block(table):
    table.place_block(0, "09:15", "10:45", "eB")
    parsed = parse_text(table.to_text())
    assert any(e.start == "09:15" and e.end == "10:45" and e.letter == "B"
               and e.offset == 0 and e.section == "Rewriting"
               for e in parsed.events)


def test_the_text_after_the_table_is_kept(table):
    table.place_block(0, "09:15", "10:45", "eB")
    assert table.to_text().endswith("Text after the table.\n")


@pytest.mark.parametrize("start,end", [("09:00", "11:15"), ("10:00", "09:00"),
                                        ("23:00", "00:30")])
def test_a_range_outside_the_limits_is_refused(table, start, end):
    with pytest.raises(ValueError):
        table.place_block(0, start, end, "gA")


def test_a_missing_code_is_refused(table):
    with pytest.raises(ValueError):
        table.place_block(0, "09:00", "10:00", "")


def test_an_unknown_day_is_refused(table):
    with pytest.raises(ValueError):
        table.place_block(5, "09:00", "10:00", "gA")


def test_clearing_keeps_the_row(table):
    row = table.find_block_row("04:00", "06:00")
    lines = len(table.to_text().splitlines())
    assert table.clear_block(row, table.column_for(0)) is True
    assert len(table.to_text().splitlines()) == lines
    assert table.find_block_row("04:00", "06:00") == row
    assert not table.blocks() or all(b.row != row for b in table.blocks())


def test_a_table_with_sections_keeps_the_chosen_activity():
    table = WeeklyTable.from_file(str(EXAMPLE))
    offset = table.columns[0][1]
    row, inserted = table.place_block(offset, "21:15", "22:00", "eA")
    block = next(b for b in table.blocks() if b.row == row)
    assert block.category == "editing"
    assert block.activity_source == "cell"


# -- the blocks by hour --------------------------------------------------------
def test_blocks_are_indexed_by_the_hour_they_start(table):
    hours = table.hour_blocks()
    assert [b.letter for b in hours[(0, 4)]] == ["A"]
    assert [b.letter for b in hours[(1, 6)]] == ["B"]
    assert (0, 5) not in hours


def test_a_long_block_shades_the_hours_it_runs_into(table):
    spans = table.hour_spans()
    assert [b.letter for b in spans[(0, 5)]] == ["A"]
    assert (0, 6) not in spans             # 04:00-06:00 only touches 06:00
    assert (1, 7) not in spans             # 06:15-07:00 ends at 07:00


# -- the two-hour break rule ---------------------------------------------------
BREAKS = (
    "|        Time | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| 08:00-10:00 | gA | gA |\n"
    "| 10:00-11:00 | eB |    |\n"
    "| 10:15-11:00 |    | eB |\n"
    "| 13:00-14:00 | sA |    |\n"
    "| 14:05-15:00 | gB |    |\n"
    "|-------------+----+----|\n"
    "| A: one |  |  |\n"
    "| B: two |  |  |\n"
)


def test_back_to_back_blocks_over_two_hours_are_flagged():
    runs = WeeklyTable(BREAKS).break_runs()
    monday = [r for r in runs if r.offset == 0]
    assert [(r.start, r.end) for r in monday] == [("08:00", "11:00")]
    assert monday[0].minutes == 180
    assert [b.letter for b in monday[0].blocks] == ["A", "B"]


def test_a_fifteen_minute_gap_is_a_break():
    runs = WeeklyTable(BREAKS).break_runs()
    assert not any(r.offset == 1 for r in runs)


def test_a_short_gap_joins_but_two_hours_exactly_is_fine():
    runs = WeeklyTable(BREAKS).break_runs()
    # 13:00-14:00 and 14:05-15:00 join across a five-minute gap, and the run
    # is exactly two hours, so it passes.
    assert all(r.start != "13:00" for r in runs)


def test_overlapping_blocks_join_a_run():
    text = BREAKS.replace("| 13:00-14:00 | sA |    |",
                          "| 13:00-14:30 | sA |    |").replace(
        "| 14:05-15:00 | gB |    |", "| 14:00-15:30 | gB |    |")
    runs = WeeklyTable(text).break_runs()
    assert ("13:00", "15:30") in [(r.start, r.end) for r in runs]


def test_break_cells_name_the_cells_of_each_run():
    table = WeeklyTable(BREAKS)
    cells = table.break_cells()
    assert len(cells) == 2
    rows = {row for row, _column in cells}
    assert rows == {table.find_block_row("08:00", "10:00"),
                    table.find_block_row("10:00", "11:00")}


# -- dropping unused rows ------------------------------------------------------
def test_unused_rows_are_the_empty_ones(table):
    unused = [tuple(table.rows[i].parsed) for i in table.unused_block_rows()]
    assert unused == [("04:00", "05:00"), ("09:00", "10:00"), ("13:00", "14:00")]


def test_dropping_unused_rows_keeps_the_plan_and_the_name(table):
    code = table.code()
    blocks = [(b.offset, b.start, b.end, b.letter) for b in table.blocks()]
    assert table.drop_unused_block_rows() == 3
    assert table.code() == code
    assert [(b.offset, b.start, b.end, b.letter) for b in table.blocks()] == blocks
    assert table.dirty is True
    assert table.drop_unused_block_rows() == 0


def test_dropping_keeps_sections_and_legend():
    table = WeeklyTable.from_file(str(EXAMPLE))
    sections = [r.raw for r in table.rows if r.kind == "section"]
    legend = [r.raw for r in table.rows if r.kind == "legend"]
    table.drop_unused_block_rows()
    assert [r.raw for r in table.rows if r.kind == "section"] == sections
    assert [r.raw for r in table.rows if r.kind == "legend"] == legend
