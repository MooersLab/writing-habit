"""Database helpers: the single contract between the three modules."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with row access by name and foreign keys enforced."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


#: The views that leave risky prospecting out of the plan comparisons. A
#: database made before the ``session.prospecting`` column holds older
#: definitions of them, which are dropped and rebuilt when the column is added.
PROSPECTING_VIEWS = ("v_week_project", "v_week_category", "v_week_overall",
                     "v_week_project_category")


def _columns(con: sqlite3.Connection, table: str) -> set:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def has_prospecting(con: sqlite3.Connection) -> bool:
    """Say whether the session table carries the risky-prospecting flag."""
    return "prospecting" in _columns(con, "session")


def migrate(con: sqlite3.Connection) -> bool:
    """Bring an older database up to the current schema.  Say whether it changed.

    A session table made before risky prospecting was labeled gains the
    ``prospecting`` column, with every existing row marked as not prospecting,
    and the comparison views that read the column are rebuilt. A database with
    no session table yet is left for :func:`init_db` to create.
    """
    cols = _columns(con, "session")
    if not cols or "prospecting" in cols:
        return False
    con.execute("ALTER TABLE session ADD COLUMN prospecting INTEGER NOT NULL"
                " DEFAULT 0 CHECK (prospecting IN (0,1))")
    for view in PROSPECTING_VIEWS:
        con.execute(f"DROP VIEW IF EXISTS {view}")
    con.commit()
    return True


def init_db(con: sqlite3.Connection, schema_path: Path | None = None) -> None:
    """Create the schema and seed the three activities. Safe to run twice.

    An older database is migrated first, so the views the schema creates find
    the columns they read.
    """
    migrate(con)
    sql = (schema_path or SCHEMA_PATH).read_text(encoding="utf-8")
    con.executescript(sql)
    # executescript() ends the implicit transaction, so restore the pragma.
    con.execute("PRAGMA foreign_keys = ON")
    con.commit()


def get_category_id(con: sqlite3.Connection, name: str | None) -> int | None:
    """Return the category id for a name, or None when the name is empty."""
    if not name:
        return None
    row = con.execute(
        "SELECT category_id FROM category WHERE name = ?", (name,)
    ).fetchone()
    return row["category_id"] if row else None


def get_or_create_project(
    con: sqlite3.Connection,
    code: str,
    description: str | None = None,
    risk_class: str | None = None,
) -> int:
    """Return the project id for a legend code, creating the row if needed.

    A later call that supplies a description or a risk class backfills those
    fields when they were previously empty, so the schedule legend can enrich
    projects that a tracker created first.
    """
    row = con.execute(
        "SELECT project_id, description, risk_class FROM project WHERE code = ?",
        (code,),
    ).fetchone()
    if row is not None:
        pid = row["project_id"]
        if description and not row["description"]:
            con.execute(
                "UPDATE project SET description = ? WHERE project_id = ?",
                (description, pid),
            )
        if risk_class and not row["risk_class"]:
            con.execute(
                "UPDATE project SET risk_class = ? WHERE project_id = ?",
                (risk_class, pid),
            )
        return pid
    cur = con.execute(
        "INSERT INTO project(code, description, risk_class) VALUES (?, ?, ?)",
        (code, description, risk_class),
    )
    return int(cur.lastrowid)


def log_import(
    con: sqlite3.Connection,
    source_type: str,
    source_name: str,
    rows_read: int,
    rows_inserted: int,
    tool_version: str | None = None,
    note: str | None = None,
) -> None:
    """Record the provenance of one import."""
    con.execute(
        "INSERT INTO import_log(source_type, source_name, rows_read, rows_inserted,"
        " tool_version, note) VALUES (?, ?, ?, ?, ?, ?)",
        (source_type, source_name, rows_read, rows_inserted, tool_version, note),
    )
    con.commit()


def minutes_between(start: str, end: str) -> int:
    """Minutes between two HH:MM times on the same day."""
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    return (eh * 60 + em) - (sh * 60 + sm)
