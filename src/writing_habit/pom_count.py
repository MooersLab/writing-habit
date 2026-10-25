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

The database is the time tracker's own, so this module never changes another
table. It writes only to a table that has exactly the three columns above,
refuses the time tracker's ``zTimeSpent`` table by name, and never alters,
renames, or drops a table or a column.
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
#: The columns of a Pomodoro count table, the only shape this module writes to.
COLUMNS = ("date", "pom_count", "recorded_at")
#: Tables of the time tracker that a Pomodoro count must never be written to.
PROTECTED = {"ztimespent"}


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
    if table.lower() in PROTECTED:
        raise ValueError(f"{table} is the time tracker's own table. Choose a "
                         f"table of its own for the Pomodoro counts, such as "
                         f"{DEFAULT_TABLE}.")
    return table


def check_shape(con, table: str) -> None:
    """Raise ``ValueError`` when ``table`` exists with columns other than ours.

    SQLite matches table names without regard to case, so ``zzpomcount`` and
    ``zzPomCount`` are one table, and the check reads the table that SQLite
    would write to.
    """
    columns = [r[1] for r in con.execute(f'PRAGMA table_xinfo("{table}")')]
    if columns and tuple(c.lower() for c in columns) != COLUMNS:
        raise ValueError(f"{table} already exists with the columns "
                         f"{', '.join(columns)}, so it is not a Pomodoro count "
                         f"table. Choose another name, such as {DEFAULT_TABLE}.")


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
        check_shape(con, table)
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
