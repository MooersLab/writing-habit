"""Set and clear the event-context tags on a week (build step 3).

A context tag marks a week with the kind of period it was, for example a
national meeting, a teaching block, or a data-collection push. The second
dashboard groups adherence by tag, so a writer can see whether the plan slips in
weeks of a given kind. A week may carry several tags.
"""

from __future__ import annotations

from .compare.queries import _monday


def set_tag(con, week: str, tag: str, note: str | None = None) -> None:
    """Attach TAG, with an optional NOTE, to the week containing WEEK."""
    con.execute(
        "INSERT OR REPLACE INTO week_context(week_start, tag, note) VALUES (?, ?, ?)",
        (_monday(week), tag, note),
    )
    con.commit()


def clear_tag(con, week: str, tag: str | None = None) -> int:
    """Remove TAG from the week, or every tag on the week when TAG is None.

    Returns the number of rows removed.
    """
    monday = _monday(week)
    if tag:
        cur = con.execute(
            "DELETE FROM week_context WHERE week_start = ? AND tag = ?", (monday, tag)
        )
    else:
        cur = con.execute("DELETE FROM week_context WHERE week_start = ?", (monday,))
    con.commit()
    return cur.rowcount


def list_tags(con, week: str | None = None):
    """Return (week_start, tag, note) rows, optionally limited to one week."""
    if week:
        return con.execute(
            "SELECT week_start, tag, note FROM week_context WHERE week_start = ?"
            " ORDER BY tag",
            (_monday(week),),
        ).fetchall()
    return con.execute(
        "SELECT week_start, tag, note FROM week_context ORDER BY week_start, tag"
    ).fetchall()
