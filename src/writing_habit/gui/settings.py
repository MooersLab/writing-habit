"""Persistent preferences for the interface.

The interface remembers the paths a weekly loop reuses, so running plan import,
then compare, then dashboard for one week needs no retyping.  The values live in
``QSettings`` under the organization ``MooersLab`` and the application
``writing-habit``, which puts them in the usual per-user location on each
platform.

The database path is remembered here and seeds the ``--db`` widget of every
command form.  Each form keeps its own widget, matching the command line, where
``--db`` is required on every subcommand that touches the database.
"""

from __future__ import annotations

from .qt import QSettings

ORGANIZATION = "MooersLab"
APPLICATION = "writing-habit"

#: Setting keys and their defaults.
DEFAULTS = {
    "db": "",              # the SQLite database
    "table_dir": "",       # where weekly tables are kept
    "table": "",           # the weekly table last opened, reopened at startup
    "out_dir": "",         # where generated files are written
    "timezone": "America/Chicago",
    "week": "",            # the last week worked on, as an ISO date
}


def settings() -> QSettings:
    """Return the shared settings object."""
    return QSettings(ORGANIZATION, APPLICATION)


def get(key: str) -> str:
    """Return the stored value for ``key``, or its default."""
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting {key!r}")
    value = settings().value(key, DEFAULTS[key])
    return "" if value is None else str(value)


def put(key: str, value: str) -> None:
    """Store ``value`` under ``key``."""
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting {key!r}")
    settings().setValue(key, value)


# The window layout is stored as a byte string rather than text, so it does not
# go through :func:`get` and :func:`put`, which coerce every value to ``str``.

def save_window(window) -> None:
    """Remember the window's size, position, and dock layout."""
    store = settings()
    store.setValue("geometry", window.saveGeometry())
    store.setValue("window_state", window.saveState())


def restore_window(window) -> bool:
    """Put the window back where it was.  Return whether anything was stored."""
    store = settings()
    geometry = store.value("geometry")
    if not geometry:
        return False
    if not window.restoreGeometry(geometry):
        return False
    state = store.value("window_state")
    if state:
        window.restoreState(state)
    return True
