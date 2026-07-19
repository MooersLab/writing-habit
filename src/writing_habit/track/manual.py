"""Add one session by hand, for a quick end-of-day entry."""

from __future__ import annotations

from ..db import get_category_id, get_or_create_project, log_import, minutes_between


def add_session(
    con,
    day: str,
    project_code: str,
    minutes: int | None = None,
    category: str | None = None,
    start: str | None = None,
    end: str | None = None,
    note: str | None = None,
) -> int:
    """Insert a single session and return its new id."""
    if minutes is None:
        if start and end:
            minutes = minutes_between(start, end)
        else:
            raise ValueError("give minutes, or both start and end")
    cat_id = get_category_id(con, category)
    if category and cat_id is None:
        raise ValueError(f"unknown category {category!r}")
    pid = get_or_create_project(con, project_code)
    cur = con.execute(
        "INSERT INTO session(day, start_time, end_time, actual_min,"
        " project_id, category_id, source, note)"
        " VALUES (?, ?, ?, ?, ?, ?, 'manual', ?)",
        (day, start, end, minutes, pid, cat_id, note),
    )
    con.commit()
    log_import(con, "sqlite", "manual add", 1, 1, note="track add")
    return int(cur.lastrowid)
