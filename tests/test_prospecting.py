"""Risky prospecting: tracked work on a project that is on no list.

track sync keeps such work under the project's directory name and flags it,
the comparison views leave it out of planned versus actual, and the weekly
dashboard and text report give it a section of its own.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from writing_habit import cli, db
from writing_habit.compare import queries, report
from writing_habit.dashboard import dashboard_html
from writing_habit.track import mytime_sync

ROOT = Path(__file__).resolve().parents[1]
WEEK = "2026-10-05"

LEGEND = """\
| Time <l>    | M  | Tu |
|-------------+----+----|
| 05:30-07:00 | gZ |    |
|-------------+----+----|
| Z: 1008ToolsForQCrOfRNA, submitted October 5 :safe: | | |
| X: 0436mpQCr December 1 :risky: | | |
"""

SEMESTER = """
#+NAME: current-semester-projects
| - 0103DACEabinitio 2026-12-15 :safe: |
"""

ROWS = [
    # id, date, start, end, ProjectID, ProjectDirectory, Description, Activity
    (1, "2026-10-05", "05:30", "07:00", 1008, "1008ToolsForQCrOfRNA", "grant", ""),
    (2, "2026-10-05", "08:00", "09:00", 1424, "1424AIseededPhasing", "idea", "G"),
    (3, "2026-10-06", "08:00", "08:30", 1424, "1424AIseededPhasing", "", ""),
    (4, "2026-10-06", "06:00", "06:30", 6005, "6005EveningCommute", "", ""),
    (5, "2026-10-07", "09:00", "10:00", 103, "0103DACEabinitio", "", ""),
    (6, "2026-10-07", "10:00", "10:20", 2026, "2026words", "journal", ""),
    (7, "2026-10-08", "05:30", "06:30", 436, "0436mpQCr", "", "G"),
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
    table.write_text(LEGEND + SEMESTER, encoding="utf-8")
    source = tmp_path / "mytime.db"
    _mytime(str(source), ROWS)
    con = db.connect(str(tmp_path / "habit.db"))
    db.init_db(con)
    con.execute("INSERT INTO plan_week(week_start, schedule_code, table_path) VALUES (?,?,?)",
                (WEEK, "Oct5", str(table)))
    gen = db.get_category_id(con, "generative")
    z = db.get_or_create_project(con, "Z", "1008ToolsForQCrOfRNA", "safe")
    x = db.get_or_create_project(con, "X", "0436mpQCr", "speculative")
    con.execute("INSERT INTO plan_block(day, start_time, end_time, project_id, category_id)"
                " VALUES ('2026-10-05', '05:30', '07:00', ?, ?)", (z, gen))
    con.execute("INSERT INTO plan_block(day, start_time, end_time, project_id, category_id)"
                " VALUES ('2026-10-08', '05:30', '06:30', ?, ?)", (x, gen))
    con.commit()
    yield con, str(source), table, tmp_path
    con.close()


def _sessions(con):
    return {
        r["source_ref"].rsplit(":", 1)[1]: r
        for r in con.execute(
            "SELECT s.*, p.code FROM session s JOIN project p USING(project_id)")
    }


def test_parse_ranges():
    assert mytime_sync.parse_ranges("0000-1999, 2100-5999") == [(0, 1999), (2100, 5999)]
    assert mytime_sync.parse_ranges("3275") == [(3275, 3275)]
    assert mytime_sync.parse_ranges("") == []
    assert mytime_sync.in_ranges("1424", [(0, 1999)])
    assert not mytime_sync.in_ranges("6005", [(0, 1999)])
    with pytest.raises(ValueError):
        mytime_sync.parse_ranges("abc")


def test_unlisted_writing_project_is_risky_prospecting(env):
    con, source, _table, _tmp = env
    result = mytime_sync.sync_mytime(con, source)
    rows = _sessions(con)
    assert rows["2"]["prospecting"] == 1 and rows["3"]["prospecting"] == 1
    assert rows["2"]["code"] == "1424AIseededPhasing"
    assert rows["1"]["prospecting"] == 0           # in the legend
    assert rows["5"]["prospecting"] == 0           # on the semester list
    assert "4" not in rows                         # commuting is not writing
    assert "6" not in rows                         # the yearly journal is outside the ranges
    assert result.prospecting == 2
    assert result.prospecting_minutes["1424AIseededPhasing"] == 90
    assert result.semester_unplanned == 1
    assert "risky prospecting" in result.render(source, WEEK, None, False)


def test_views_leave_prospecting_out_of_the_plan_comparison(env):
    con, source, _table, _tmp = env
    mytime_sync.sync_mytime(con, source)
    codes = {r["code"] for r in queries.week_project(con, WEEK)}
    assert "1424AIseededPhasing" not in codes
    overall = queries.overall_series(con)[0]
    assert overall["actual_min"] == 90 + 60 + 60   # Z, X, and the semester project
    rows = queries.week_prospecting(con, WEEK)
    assert [(r["code"], r["sessions"], r["actual_min"], r["weeks_so_far"]) for r in rows] == [
        ("1424AIseededPhasing", 2, 90, 1)]
    # The streak still counts a day of prospecting as a day of writing.
    days = {r["day"] for r in queries.day_actual(con, WEEK)}
    assert "2026-10-06" in days


def test_label_clears_once_the_project_is_listed(env):
    con, source, table, _tmp = env
    mytime_sync.sync_mytime(con, source)
    table.write_text(LEGEND + SEMESTER.rstrip("\n")
                     + "\n| - 1424AIseededPhasing 2027-03-01 :risky: |\n", encoding="utf-8")
    again = mytime_sync.sync_mytime(con, source)
    assert again.updated == 2 and again.prospecting == 0
    assert _sessions(con)["2"]["prospecting"] == 0
    assert queries.week_prospecting(con, WEEK) == []


def test_ranges_off_and_legend_scope_leave_it_out(env):
    con, source, _table, _tmp = env
    off = mytime_sync.sync_mytime(con, source, prospect_ranges="")
    assert off.prospecting == 0 and "2" not in _sessions(con)
    strict = mytime_sync.sync_mytime(con, source, scope="legend")
    assert strict.prospecting == 0 and "2" not in _sessions(con)


def test_scope_all_still_labels_unlisted_writing(env):
    con, source, _table, _tmp = env
    mytime_sync.sync_mytime(con, source, scope="all")
    rows = _sessions(con)
    assert rows["2"]["prospecting"] == 1
    assert rows["4"]["prospecting"] == 0           # kept as unplanned, not risky


def test_cli_prospect_range(env, capsys):
    con, source, _table, tmp = env
    con.close()
    dbpath = str(tmp / "habit.db")
    assert cli.main(["track", "sync", source, "--db", dbpath,
                     "--prospect-range", "none"]) == 0
    assert "risky prospecting" not in capsys.readouterr().out
    assert cli.main(["track", "sync", source, "--db", dbpath]) == 0
    assert "risky prospecting" in capsys.readouterr().out


def test_dashboard_and_report_show_risky_prospecting(env):
    con, source, _table, _tmp = env
    mytime_sync.sync_mytime(con, source)
    html = dashboard_html(con, WEEK, today="2026-10-12")
    assert "<h2>Risky prospecting</h2>" in html
    assert '<span class="risky">90 minutes</span>, 30% of the week' in html
    assert "<td>1424AIseededPhasing</td>" in html
    assert "<td>risky prospecting</td>" in html
    # (speculative X 60 + prospecting 90) / (safe Z 90 + X 60 + 90) = 62.5%,
    # rounded half up. The untagged semester project is not in the barbell.
    assert "the risky share of actual time is 63%." in html
    assert "1424AIseededPhasing" not in html.split("<h2>Activity balance</h2>")[0]
    text = report.render_week(con, WEEK)
    assert "Risky prospecting (tracked, on no list)" in text
    assert "90 min, 30% of tracked writing" in text


def test_stale_prospecting_is_marked(env):
    con, source, _table, _tmp = env
    src = sqlite3.connect(source)
    for i, day in enumerate(("2026-10-12", "2026-10-19"), start=20):
        src.execute("INSERT INTO zTimeSpent VALUES (?,?,?,?,?,?,?,?)",
                    (i, day, "08:00", "09:00", 1424, "1424AIseededPhasing", "", ""))
    src.commit()
    src.close()
    mytime_sync.sync_mytime(con, source, table=str(_table))
    rows = queries.week_prospecting(con, "2026-10-19")
    assert rows[0]["weeks_so_far"] == 3
    assert '<tr class="stale"><td>1424AIseededPhasing' in dashboard_html(con, "2026-10-19")


def test_old_database_is_migrated(tmp_path):
    old_schema = subprocess.run(
        ["git", "show", "HEAD~0:src/writing_habit/schema.sql"], cwd=ROOT,
        capture_output=True, text=True)
    if old_schema.returncode or "prospecting" in old_schema.stdout:
        pytest.skip("the committed schema already carries the prospecting column")
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(old_schema.stdout)
    pid = con.execute("INSERT INTO project(code) VALUES ('A')").lastrowid
    con.execute("INSERT INTO session(day, actual_min, project_id, source)"
                " VALUES ('2026-10-05', 30, ?, 'manual')", (pid,))
    con.commit()
    con.close()
    con = db.connect(str(path))
    assert not db.has_prospecting(con)
    assert queries.week_prospecting(con, WEEK) == []   # readers cope before migration
    db.init_db(con)
    assert db.has_prospecting(con)
    assert con.execute("SELECT prospecting FROM session").fetchone()[0] == 0
    assert queries.overall_series(con)[0]["actual_min"] == 30
    assert queries.week_prospecting(con, WEEK) == []
    assert db.migrate(con) is False
    con.close()


def test_cross_port_fixture_is_not_touched():
    """The shared fixture predates the label, and the dashboard reads it as is."""
    con = db.connect(str(ROOT / "tests" / "fixtures" / "cross-port.db"))
    try:
        assert queries.week_prospecting(con, "2026-01-19") == []
    finally:
        con.close()
