"""Record each day's Pomodoro total in a table of a SQLite database.

The Pomodoro timer counts the Pomodoros finished each day. At 11:59 PM it
writes that day's total to a table, by default ``zzPomCount`` in
``~/6003TimeTracking/cb/mytime.db``, beside the time tracker's own tables::

    CREATE TABLE zzPomCount (date TEXT PRIMARY KEY, pom_count INTEGER NOT NULL,
                             recorded_at TEXT NOT NULL)

The table holds one row per day. A day written twice, for example once at
11:59 PM and again after a Pomodoro that ended in the last minute, keeps one
row with the later total. The table is created when it is missing. Nothing
here imports Qt, so the command line and the tests can use it too.
"""

from __future__ import annotations

import datetime as _dt
import re
import sqlite3
from pathlib import Path
from typing import List, Tuple, Union

DEFAULT_DIR = "~/6003TimeTracking/cb"
DEFAULT_FILE = "mytime.db"
DEFAULT_TABLE = "zzPomCount"

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def database_path(folder: str = DEFAULT_DIR, file: str = DEFAULT_FILE) -> Path:
    """Return the database path from its folder and file name, with ``~`` expanded."""
    return Path(folder or DEFAULT_DIR).expanduser() / (file or DEFAULT_FILE)


def check_table(table: str) -> str:
    """Return ``table`` when it is a plain SQL name, or raise ``ValueError``.

    The name goes into the SQL text, because SQLite cannot take a table name
    as a parameter, so only letters, digits, and underscores are allowed.
    """
    if not _IDENTIFIER.match(table or ""):
        raise ValueError(f"not a plain table name: {table!r}")
    return table


def record(path: Union[str, Path], table: str, day: _dt.date, count: int,
           now: _dt.datetime = None) -> str:
    """Write ``count`` Pomodoros for ``day``. Return ``"added"`` or ``"updated"``.

    The folder must exist, so a mistyped path fails instead of making a new
    database somewhere unexpected. The table is created when it is missing.
    """
    table = check_table(table)
    path = Path(path).expanduser()
    if not path.parent.is_dir():
        raise FileNotFoundError(f"no folder {path.parent}")
    stamp = (now or _dt.datetime.now()).isoformat(timespec="seconds")
    con = sqlite3.connect(str(path))
    try:
        con.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ('
                    "date TEXT PRIMARY KEY, pom_count INTEGER NOT NULL, "
                    "recorded_at TEXT NOT NULL)")
        found = con.execute(f'SELECT 1 FROM "{table}" WHERE date = ?',
                            (day.isoformat(),)).fetchone()
        if found:
            con.execute(f'UPDATE "{table}" SET pom_count = ?, recorded_at = ? '
                        "WHERE date = ?", (count, stamp, day.isoformat()))
        else:
            con.execute(f'INSERT INTO "{table}" (date, pom_count, recorded_at) '
                        "VALUES (?, ?, ?)", (day.isoformat(), count, stamp))
        con.commit()
    finally:
        con.close()
    return "updated" if found else "added"


def rows(path: Union[str, Path], table: str) -> List[Tuple[str, int]]:
    """Return ``(date, pom_count)`` for every recorded day, oldest first."""
    table = check_table(table)
    con = sqlite3.connect(str(Path(path).expanduser()))
    try:
        return [tuple(r) for r in con.execute(
            f'SELECT date, pom_count FROM "{table}" ORDER BY date')]
    finally:
        con.close()
