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


def init_db(con: sqlite3.Connection, schema_path: Path | None = None) -> None:
    """Create the schema and seed the three activities. Safe to run twice."""
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
