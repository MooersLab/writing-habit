"""The Tutorials tab: one read-only page per task, each in its own subtab.

A page is plain HTML rendered by ``QTextBrowser``, which needs no web engine.
Three kinds of link appear on the pages. ``tab:Track`` raises a tab of the main
window, so a reader can go straight to the form a step describes.
``tutorial:track`` raises another tutorial. Any other address opens in the web
browser of the desktop, as a link in any other program would.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from . import tutorials
from .qt import QtCore, QtGui, QtWidgets, fixed_font, pyqtSignal


class TutorialsPage(QtWidgets.QTabWidget):
    """A tab widget holding one browser per tutorial page."""

    #: Emitted with a main-window tab title when a ``tab:`` link is followed.
    tab_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDocumentMode(True)
        self.browsers: Dict[str, QtWidgets.QTextBrowser] = {}
        #: Opens an outside address. A test replaces it so no browser starts.
        self.open_url: Callable[[str], bool] = (
            lambda url: QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)))
        # The code font is named by family, never by a generic name, which
        # makes Qt search every installed font on macOS.
        style = STYLE.replace("MONO", fixed_font().family())
        for title, name in tutorials.PAGES:
            browser = QtWidgets.QTextBrowser(self)
            browser.setOpenLinks(False)
            browser.setSearchPaths([str(tutorials.HERE), str(tutorials.IMAGES)])
            browser.document().setDefaultStyleSheet(style)
            browser.setHtml(tutorials.page_path(name).read_text(encoding="utf-8"))
            browser.anchorClicked.connect(self.follow)
            self.browsers[tutorials.page_key(name)] = browser
            self.addTab(browser, title)

    def keys(self):
        return list(self.browsers)

    def show_tutorial(self, key: str) -> bool:
        """Raise the tutorial ``key``, for example ``track``.  Say whether it exists."""
        browser = self.browsers.get(key)
        if browser is None:
            return False
        self.setCurrentWidget(browser)
        browser.verticalScrollBar().setValue(0)
        return True

    def follow(self, url: QtCore.QUrl) -> Optional[str]:
        """Act on a clicked link.  Return what it did, for the tests."""
        text = url.toString()
        if text.startswith("tab:"):
            self.tab_requested.emit(text[4:])
            return "tab"
        if text.startswith("tutorial:"):
            self.show_tutorial(text[len("tutorial:"):])
            return "tutorial"
        if text.startswith("#"):
            self.currentWidget().scrollToAnchor(text[1:])
            return "anchor"
        self.open_url(text)
        return "web"


#: The rich-text widget understands a subset of CSS, which is enough here.
STYLE = """
body { font-size: 13px; }
h1 { font-size: 20px; margin-bottom: 4px; }
h2 { font-size: 16px; margin-top: 18px; }
h3 { font-size: 14px; margin-top: 12px; }
pre { background-color: #f2f2f0; padding: 6px; font-family: 'MONO'; }
code { font-family: 'MONO'; }
td, th { padding: 3px 8px; }
th { background-color: #e8e8e4; }
.note { background-color: #fff6d8; padding: 6px; }
.caption { color: #555555; font-size: 12px; }
"""
