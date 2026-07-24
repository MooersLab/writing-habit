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


# ---------------------------------------------------------------------------
# Cross-week series readers for the adherence tracker (build step 1).
# Each returns one row per week from a cross-week view, optionally limited to a
# [start, end] window given as any date inside the first and last week.
# ---------------------------------------------------------------------------

def _range_clause(params: list, start, end) -> str:
    clauses = []
    if start:
        clauses.append("week_start >= ?")
        params.append(_monday(start))
    if end:
        clauses.append("week_start <= ?")
        params.append(_monday(end))
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


def overall_series(con, start=None, end=None):
    """Overall adherence per week: summed actual over summed planned minutes."""
    params: list = []
    where = _range_clause(params, start, end)
    return con.execute(
        f"SELECT * FROM v_week_overall{where} ORDER BY week_start", params
    ).fetchall()


def project_mean_series(con, start=None, end=None):
    """Mean of the per-project adherence ratios per week."""
    params: list = []
    where = _range_clause(params, start, end)
    return con.execute(
        f"SELECT * FROM v_week_project_mean{where} ORDER BY week_start", params
    ).fetchall()


def category_mean_series(con, category: str, start=None, end=None):
    """Mean per-project adherence within one activity, per week."""
    params: list = [category]
    clauses = ["category = ?"]
    if start:
        clauses.append("week_start >= ?")
        params.append(_monday(start))
    if end:
        clauses.append("week_start <= ?")
        params.append(_monday(end))
    where = " WHERE " + " AND ".join(clauses)
    return con.execute(
        f"SELECT * FROM v_week_category_mean{where} ORDER BY week_start", params
    ).fetchall()


# ---------------------------------------------------------------------------
# Grouping readers for the second dashboard (build step 3).
# ---------------------------------------------------------------------------

def month_overall(con):
    """Overall adherence per calendar month."""
    return con.execute("SELECT * FROM v_month_overall ORDER BY month").fetchall()


def context_overall(con):
    """Overall adherence per event-context tag."""
    return con.execute("SELECT * FROM v_context_overall ORDER BY tag").fetchall()


def schedule_overall(con):
    """Overall adherence per schedule code."""
    return con.execute(
        "SELECT * FROM v_schedule_overall ORDER BY schedule_code"
    ).fetchall()
