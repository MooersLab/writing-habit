"""The progress table, the hours spent from mytime.db, and next week's plan."""

import sqlite3

import pytest

from writing_habit import energy, progress
from writing_habit.progress import Row

TABLE = [
    "#+NAME: current-semester-projects",
    "| A: 1094RNAstrucDetResearchProgram :safe: |",
    "",
    "#+NAME: progress",
    "| Project ID | Project name | Est. hours | Hours spent | Weight |",
    "|------------+--------------+------------+-------------+--------|",
    "| 0201       | dusp1        |         40 |          10 |      3 |",
    "| 1006       | AIrxOpt      |        100 |         2.5 |      5 |",
    "| 0655       | VirtIssue25  |            |             |        |",
]


def test_read_returns_the_rows():
    rows = progress.read(TABLE)
    assert [r.number for r in rows] == ["0201", "1006", "0655"]
    assert rows[0] == Row("0201", "dusp1", 40, 10, 3)
    assert rows[1].remaining == 97.5
    assert rows[2].estimate is None and rows[2].remaining is None
    assert rows[2].label == "0655 VirtIssue25"


def test_read_without_a_table_is_none():
    assert progress.read(TABLE[:2]) is None


def test_read_takes_the_number_from_the_name_cell():
    rows = progress.read(["#+NAME: Progress", "| | 0142RETKinase | 8 | | 1 |"])
    assert rows == [Row("0142", "RETKinase", 8, 0, 1)]


def test_write_replaces_only_the_table():
    lines = list(TABLE)
    rows = progress.read(lines)
    rows[2].estimate = 20
    assert progress.write(lines, rows)
    assert lines[:4] == TABLE[:4]
    assert progress.read(lines)[2].estimate == 20
    assert not progress.write(lines, progress.read(lines))
    widths = {len(line) for line in lines[4:]}
    assert len(widths) == 1                 # aligned


def test_write_adds_the_table_at_the_end():
    lines = TABLE[:2] + ["", ""]
    assert progress.write(lines, [Row("1094", "RNAstruc", 50)])
    assert lines[-5:-3] == ["", "#+NAME: progress"]
    assert progress.read(lines) == [Row("1094", "RNAstruc", 50)]


def test_seed_adds_numbered_projects_once():
    from writing_habit.project_lists import Entry
    entries = [Entry("A", "1094RNAstruc"), Entry(None, "email"),
               Entry("B", "0201dusp1 2026-10-15")]
    rows = progress.seed(entries, [Row("0201", "dusp1", 40)])
    assert [(r.number, r.name, r.estimate) for r in rows] == [
        ("0201", "dusp1", 40), ("1094", "RNAstruc", None)]


@pytest.fixture()
def mytime(tmp_path):
    path = tmp_path / "mytime.db"
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE zTimeSpent (id INTEGER PRIMARY KEY, DateDashed DATE,'
                ' Start TIME, "End" TIME, ProjectID INT, ProjectDirectory TEXT,'
                ' Description TEXT, Activity TEXT)')
    con.executemany("INSERT INTO zTimeSpent VALUES (NULL,?,?,?,?,?,'','')", [
        ("2026-10-05", "05:30", "07:00", 1006, "1006AIrxOpt"),
        ("2026-10-06", "5:00", "6:00", None, "1006AIrxOpt"),
        ("2026-10-06", "23:30", "00:15", 201, "0201dusp1"),
        ("2026-10-07", "", "", 201, "0201dusp1"),           # a blank placeholder
        ("2026-10-07", "08:00", "09:00", 9999, "9999other"),
    ])
    con.commit()
    con.close()
    return path


def test_hours_spent_sums_sessions_by_number(mytime):
    hours = progress.hours_spent(mytime, ["1006", "0201", "0655"])
    assert hours == {"1006": 2.5, "0201": 0.8, "0655": 0.0}
    assert progress.hours_spent(mytime, ["1006"], since="2026-10-06") == {"1006": 1.0}


def test_hours_spent_never_writes(mytime):
    before = mytime.read_bytes()
    progress.hours_spent(mytime, ["1006"])
    assert mytime.read_bytes() == before


def test_hours_spent_needs_the_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        progress.hours_spent(tmp_path / "missing.db", ["1006"])


def test_update_counts_the_changed_rows():
    rows = [Row("1006", "a", spent=1), Row("0201", "b", spent=0.8)]
    assert progress.update(rows, {"1006": 2.5, "0201": 0.8}) == 1
    assert rows[0].spent == 2.5


def test_share_follows_the_weights_and_the_time_left():
    rows = [Row("0001", "heavy", 100, 0, 3), Row("0002", "light", 100, 0, 1),
            Row("0003", "nearly done", 10, 9.5, 5), Row("0004", "no weight", 10, 0),
            Row("0005", "no estimate", None, 0, 4)]
    shares = dict((r.number, m) for r, m in progress.share(rows, 600))
    assert shares["0003"] == 30                    # only half an hour left
    assert shares["0001"] + shares["0002"] == 570
    assert abs(shares["0001"] - 0.75 * 570) <= 30
    assert "0004" not in shares and "0005" not in shares


def test_place_uses_the_best_hours_and_keeps_runs_short():
    profile = energy.default_profile()
    rows = [Row("0001", "heavy", 100, 0, 3), Row("0002", "light", 100, 0, 1)]
    shares = progress.share(rows, 600)
    blocks, unplaced = progress.place(shares, profile)
    assert unplaced == []
    assert sum(_span(b) for b in blocks) == 600
    assert all(_span(b) <= 90 for b in blocks)
    best = max(profile["generative"])
    heavy = [b for b in blocks if b.row.number == "0001"]
    assert heavy[0].level == best
    from writing_habit.rescue import _fits_runs
    for day in range(5):
        spans = [(_minute(b.start), _minute(b.end)) for b in blocks if b.offset == day]
        assert _fits_runs(spans)
        assert len(spans) <= 4


def _minute(clock):
    return int(clock[:2]) * 60 + int(clock[3:])


def _span(block):
    return _minute(block.end) - _minute(block.start)


def test_plan_facts_and_plain_name_the_numbers():
    rows = [Row("0201", "dusp1", 40, 10, 3), Row("0655", "VirtIssue25")]
    p = progress.plan(rows, 180, energy.default_profile())
    assert [r.number for r in p.left_out] == ["0655"]
    facts = progress.facts(p)
    assert "Minutes to plan next week: 180" in facts
    assert "planned 180 minutes" in facts
    assert "Left out: 0655 VirtIssue25, because it has no estimate" in facts
    text = progress.plain(p)
    assert text.startswith("Next week's 3 h 00 min go by weight to 0201 dusp1")
    assert "1 project without an estimate or a weight was left out" in text


def test_plain_with_nothing_to_share():
    p = progress.plan([Row("0655", "x")], 600, energy.default_profile())
    assert p.shares == []
    assert "nothing to share out" in progress.plain(p)
