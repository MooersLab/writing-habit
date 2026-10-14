"""track sync: copy sessions from a mytime.db zTimeSpent table."""

from __future__ import annotations

import sqlite3

import pytest

from writing_habit import cli, db
from writing_habit.track import mytime_sync

WEEK = "2026-10-05"

LEGEND = """\
| Time <l>    | M  | Tu |
|-------------+----+----|
| 05:30-07:00 | gZ |    |
|-------------+----+----|
| F: 4072UsersMeeting2026 Sep 16, 0382CCinJN :safe: | | |
| H: 0104BaGquadShelxD November 15 :safe:          | | |
| Z: 1008ToolsForQCrOfRNA, submitted October 5 :safe: | | |
"""

ROWS = [
    # id, date, start, end, ProjectID, ProjectDirectory, Description, Activity
    (1, "2026-10-05", "05:30", "07:00", 1008, "1008ToolsForQCrOfRNA", "grant text", ""),
    (2, "2026-10-05", "08:00", "09:00", 104, "0104BaGquadShelxD", "figures", "E"),
    (3, "2026-10-06", "3:45", "05:00", 382, "0382CCinJN", "", "sw"),
    (4, "2026-10-06", "06:00", "06:30", 6005, "6005EveningCommute", "", "none"),
    (5, "2026-10-06", "", "", "", "", "", ""),
    (6, "2026-10-07", "21:00", "00:00", 104, "0104BaGquadShelxD", "late", "G"),
    (7, "2026-09-28", "05:00", "06:00", 1008, "1008ToolsForQCrOfRNA", "before", "g"),
]


def _mytime(path, rows):
    con = sqlite3.connect(path)
    con.execute(
        'CREATE TABLE zTimeSpent (id INTEGER PRIMARY KEY, DateDashed DATE, Start TIME,'
        ' "End" TIME, ProjectID INT, ProjectDirectory TEXT, Description TEXT,'
        " Activity TEXT DEFAULT none)"
    )
    con.executemany("INSERT INTO zTimeSpent VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


@pytest.fixture()
def env(tmp_path):
    table = tmp_path / "Oct5.org"
    table.write_text(LEGEND, encoding="utf-8")
    source = tmp_path / "mytime.db"
    _mytime(str(source), ROWS)
    con = db.connect(str(tmp_path / "habit.db"))
    db.init_db(con)
    # A planned week, as plan import would leave it, without needing writing-schedule.
    con.execute("INSERT INTO plan_week(week_start, schedule_code, table_path) VALUES (?,?,?)",
                (WEEK, "Oct5", str(table)))
    pid = db.get_or_create_project(con, "Z", "1008ToolsForQCrOfRNA", "safe")
    con.execute("INSERT INTO plan_block(day, start_time, end_time, project_id, category_id)"
                " VALUES ('2026-10-05', '05:30', '07:00', ?, ?)",
                (pid, db.get_category_id(con, "generative")))
    con.commit()
    yield con, str(source), str(table), tmp_path
    con.close()


def _sessions(con):
    return {
        r["source_ref"].rsplit(":", 1)[1]: r
        for r in con.execute(
            "SELECT s.*, p.code, c.name AS category FROM session s"
            " JOIN project p USING(project_id) LEFT JOIN category c USING(category_id)"
        )
    }


def test_legend_numbers_reads_every_project_in_a_description(env):
    _con, _src, table, _tmp = env
    numbers = mytime_sync.legend_numbers(table)
    assert numbers == {"4072": "F", "0382": "F", "0104": "H", "1008": "Z"}


def test_sync_maps_numbers_to_letters_and_activities(env):
    con, source, _table, _tmp = env
    report = mytime_sync.sync_mytime(con, source)
    rows = _sessions(con)
    assert set(rows) == {"1", "2", "3", "6"}           # 7 is before the first planned week
    assert rows["1"]["code"] == "Z"
    assert rows["1"]["category"] == "generative"       # no tag, so the planned block decides
    assert rows["2"]["code"] == "H" and rows["2"]["category"] == "editing"
    assert rows["3"]["code"] == "F" and rows["3"]["start_time"] == "03:45"
    assert rows["3"]["category"] == "support"
    assert rows["6"]["actual_min"] == 180              # wraps past midnight
    assert report.inserted == 4
    assert report.skipped_not_in_legend == 1
    assert report.left_out_minutes["6005EveningCommute"] == 30
    assert report.skipped_no_time == 1          # row 5 has no times


def test_rerun_is_idempotent_and_picks_up_edits(env):
    con, source, _table, _tmp = env
    mytime_sync.sync_mytime(con, source)
    again = mytime_sync.sync_mytime(con, source)
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 4)
    src = sqlite3.connect(source)
    src.execute('UPDATE zTimeSpent SET "End" = \'09:30\' WHERE id = 2')
    src.commit()
    src.close()
    third = mytime_sync.sync_mytime(con, source)
    assert third.updated == 1
    assert _sessions(con)["2"]["actual_min"] == 90
    assert con.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 4


def test_scope_all_keeps_unplanned_projects(env):
    con, source, _table, _tmp = env
    mytime_sync.sync_mytime(con, source, scope="all")
    assert _sessions(con)["4"]["code"] == "6005EveningCommute"


def test_dry_run_writes_nothing(env):
    con, source, _table, _tmp = env
    report = mytime_sync.sync_mytime(con, source, dry_run=True)
    assert report.inserted == 4
    assert con.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 1


def test_since_and_table_fallback(env):
    con, source, table, _tmp = env
    report = mytime_sync.sync_mytime(con, source, since="2026-09-28", until="2026-10-05",
                                     table=table)
    assert set(_sessions(con)) == {"1", "2", "7"}
    assert report.inserted == 3


def test_missing_source_is_a_clear_error(env):
    con, _source, _table, tmp = env
    with pytest.raises(FileNotFoundError):
        mytime_sync.sync_mytime(con, str(tmp / "nope.db"))


def test_cli_sync(env, capsys):
    con, source, _table, tmp = env
    con.close()
    code = cli.main(["track", "sync", source, "--db", str(tmp / "habit.db")])
    assert code == 0
    out = capsys.readouterr().out
    assert "inserted 4" in out and "6005EveningCommute" in out


def test_no_plan_and_no_table_is_reported_as_no_legend(tmp_path):
    source = tmp_path / "mytime.db"
    _mytime(str(source), ROWS)
    con = db.connect(str(tmp_path / "habit.db"))
    db.init_db(con)
    report = mytime_sync.sync_mytime(con, str(source), since="2026-10-05")
    assert report.inserted == 0
    assert report.skipped_not_in_legend == 0
    assert report.skipped_no_legend == 5
    text = report.render(str(source), "2026-10-05", None, False)
    assert "no legend to read" in text and "2026-10-05" in text


def test_table_is_read_for_a_week_with_no_plan(tmp_path):
    table = tmp_path / "Oct5.org"
    table.write_text(LEGEND, encoding="utf-8")
    source = tmp_path / "mytime.db"
    _mytime(str(source), ROWS)
    con = db.connect(str(tmp_path / "habit.db"))
    db.init_db(con)
    report = mytime_sync.sync_mytime(con, str(source), since="2026-10-05", table=str(table))
    assert report.inserted == 4
    assert report.weeks_without_plan == {"2026-10-05"}
