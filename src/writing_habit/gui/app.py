"""The ``writing-habit-gui`` entry point.

The import of Qt happens inside :func:`main`, so a checkout without the
graphical extra prints one clear line rather than a traceback.
"""

from __future__ import annotations

import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    """Start the interface and return its exit code."""
    try:
        from .qt import QtWidgets, prepare_for_web_engine
        from .mainwindow import MainWindow
    except ImportError as exc:            # the binding is missing
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Before the application object exists, because Qt refuses the web-engine
    # import afterwards.  The preview falls back to rich text without it.
    prepare_for_web_engine()

    argv = list(sys.argv if argv is None else argv)
    app = QtWidgets.QApplication(argv)
    app.setApplicationName("writing-habit")
    app.setOrganizationName("MooersLab")

    window = MainWindow()
    _install_excepthook(window)
    window.show()
    return app.exec_()


def _install_excepthook(window) -> None:
    """Report an unhandled exception in a dialog rather than on the console.

    A traceback that reaches the console of a windowed program is invisible, so
    the hook shows it and keeps the window alive.  The console copy is kept
    because a developer running from a terminal wants both.
    """
    from .qt import QtWidgets

    previous = sys.excepthook

    def hook(kind, value, traceback):
        previous(kind, value, traceback)
        QtWidgets.QMessageBox.critical(
            window, "Unexpected error", f"{kind.__name__}: {value}"
        )

    sys.excepthook = hook


if __name__ == "__main__":            # pragma: no cover
    raise SystemExit(main())
