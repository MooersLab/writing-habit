"""The optional PyQt5 front end for writing-habit.

The package is imported only by the ``writing-habit-gui`` entry point and by
its own tests, so the library and the command line never pull in Qt.  Install
it with::

    pip install "writing-habit[gui]"

PyQt5 is distributed under the GPL, so this extra carries GPL terms while the
library and the command line remain MIT.

Every Qt name enters through :mod:`writing_habit.gui.qt`, which keeps a later
move to PyQt6 or PySide6 a one-file change.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv=None) -> int:
    """Run the interface.  Imported lazily so ``--help`` needs no Qt."""
    from .app import main as _main
    return _main(argv)
