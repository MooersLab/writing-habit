"""Thin wrappers over the comparison views defined in schema.sql.

Each function returns a list of sqlite3.Row. The compare module never writes
its own aggregation SQL, so the schema stays the single source of truth.
"""

from __future__ import annotations

from datetime import date, timedelta


def _monday(week: str) -> str:
    d = date.fromisoformat(week)
    return (d - timedelta(days=d.weekday())).isoformat()


def week_project(con, week: str):
    """Planned versus actual minutes and adherence per project for the week."""
    return con.execute(
        "SELECT * FROM v_week_project WHERE week_start = ? ORDER BY code",
        (_monday(week),),
    ).fetchall()


def week_category(con, week: str):
    """Planned versus actual minutes per activity for the week."""
    return con.execute(
        "SELECT * FROM v_week_category WHERE week_start = ?",
        (_monday(week),),
    ).fetchall()


def week_barbell(con, week: str):
    """Planned versus actual minutes per risk class for the week."""
    return con.execute(
        "SELECT * FROM v_week_barbell WHERE week_start = ? ORDER BY risk_class",
        (_monday(week),),
    ).fetchall()


def day_actual(con, week: str):
    """Actual minutes and worked flag per day for the week."""
    return con.execute(
        "SELECT * FROM v_day_actual WHERE week_start = ? ORDER BY day",
        (_monday(week),),
    ).fetchall()


def current_streak(con) -> int:
    """Length of the run of consecutive worked days ending at the latest one."""
    rows = con.execute(
        "SELECT day FROM v_day_actual WHERE worked = 1 ORDER BY day"
    ).fetchall()
    days = [date.fromisoformat(r["day"]) for r in rows]
    if not days:
        return 0
    streak = 1
    for earlier, later in zip(days[-2::-1], days[::-1]):
        if (later - earlier).days == 1:
            streak += 1
        else:
            break
    return streak
