"""The single import site for Qt.

Nothing else in the package imports PyQt5 directly.  Two things follow from
that rule.  A move to PyQt6 or PySide6 edits this file and nothing else,
because the rest of the code imports the names from here.  A missing binding
raises one clear error that names the extra to install rather than a bare
``ModuleNotFoundError`` from an arbitrary module.
"""

from __future__ import annotations

BINDING = "PyQt5"

INSTALL_HINT = (
    'PyQt5 is not installed.  Install the graphical extra with:\n'
    '    pip install "writing-habit[gui]"\n'
    "PyQt5 is distributed under the GPL, while the library and the command "
    "line remain MIT."
)


class QtUnavailable(ImportError):
    """Raised when the Qt binding is missing, carrying the install hint."""


try:
    from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PyQt5.QtCore import QSettings, Qt, pyqtSignal  # noqa: F401
    from PyQt5.QtCore import QT_VERSION_STR, PYQT_VERSION_STR  # noqa: F401
except ImportError as exc:                      # pragma: no cover - env specific
    raise QtUnavailable(INSTALL_HINT) from exc


#: The result of the web-engine probe, cached because the import is only
#: allowed before a QApplication exists.
_WEB_ENGINE = "unprobed"


def web_engine_view():
    """Return the ``QWebEngineView`` class, or ``None`` when it is unavailable.

    The web engine ships as a separate package, ``PyQtWebEngine``, so a normal
    installation may not have it. The probe lives here because this module is
    the only import site for Qt, and the preview asks rather than imports.

    Qt refuses to import the web engine once a ``QApplication`` exists, so the
    answer is cached from the first call. :func:`prepare_for_web_engine` makes
    that first call at startup, while the import is still allowed.
    """
    global _WEB_ENGINE
    if _WEB_ENGINE == "unprobed":
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            _WEB_ENGINE = None
        else:
            _WEB_ENGINE = QWebEngineView
    return _WEB_ENGINE


def prepare_for_web_engine() -> bool:
    """Make the web engine usable, if it is installed.  Call before QApplication.

    Two things have to happen before the application object exists. The shared
    OpenGL context attribute has to be set, and the web engine module has to be
    imported. Qt prints a warning and then refuses the import when either is
    done late, which is why this is a startup step rather than a lazy one.
    Returns whether the engine is available.
    """
    QtCore.QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    return web_engine_view() is not None


def fixed_font():
    """Return the platform's fixed-width font.

    Qt has no font family called ``Monospace`` on macOS or Windows, so asking
    for one by that name, or through the CSS generic, makes Qt walk the whole
    font database hunting for an alias. That scan costs about 80 ms at startup
    and prints a warning. The font database answers the same question directly
    and names a family that exists: Menlo on macOS, Consolas on Windows, and
    whatever the desktop has configured on Linux.
    """
    font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
    # A stripped-down system can answer that question with a proportional
    # family, which would misalign the columns of a report. The hint tells Qt
    # to substitute a fixed-width face in that case, and it costs no scan.
    font.setStyleHint(QtGui.QFont.Monospace, QtGui.QFont.PreferMatch)
    font.setFixedPitch(True)
    return font


def versions() -> str:
    """Return a one-line description of the binding, for the About dialog."""
    return f"{BINDING} {PYQT_VERSION_STR} on Qt {QT_VERSION_STR}"
