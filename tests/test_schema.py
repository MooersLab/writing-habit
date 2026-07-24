"""Schema smoke tests: tables, views, generated columns, and foreign keys."""

import sqlite3
from pathlib import Path

import pytest

SCHEMA = Path(__file__).resolve().parents[1] / "src" / "writing_habit" / "schema.sql"


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA.read_text())
    c.execute("PRAGMA foreign_keys = ON")
    yield c
    c.close()


def test_tables_and_views_exist(con):
    names = {
        r["name"]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    for expected in [
        "category", "project", "plan_block", "session", "import_log",
        "plan_week", "week_context",
        "v_week_project", "v_week_category", "v_week_barbell", "v_day_actual",
        "v_week_overall", "v_week_project_mean", "v_week_project_category",
        "v_week_category_mean",
        "v_month_overall", "v_context_overall", "v_schedule_overall",
    ]:
        assert expected in names


def test_generated_columns(con):
    con.execute("INSERT INTO project(code, risk_class) VALUES ('A','safe')")
    pid = con.execute("SELECT project_id FROM project").fetchone()[0]
    con.execute(
        "INSERT INTO plan_block(day, start_time, end_time, project_id, category_id)"
        " VALUES ('2026-01-21','04:00','05:30',?,1)",
        (pid,),
    )
    row = con.execute("SELECT planned_min, week_start FROM plan_block").fetchone()
    assert row["planned_min"] == 90
    assert row["week_start"] == "2026-01-19"  # Monday of that week


def test_foreign_key_enforced(con):
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO session(day, actual_min, project_id, source)"
            " VALUES ('2026-01-19', 10, 999, 'manual')"
        )


def test_support_is_not_a_risk_class(con):
    # support is an activity category, not a risk class, so the CHECK rejects it
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO project(code, risk_class) VALUES ('S','support')")
    # safe and speculative remain valid risk classes
    con.execute("INSERT INTO project(code, risk_class) VALUES ('A','safe')")
    con.execute("INSERT INTO project(code, risk_class) VALUES ('W','speculative')")
