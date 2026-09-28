"""Show what a command just wrote, inside the window.

Three kinds of output come out of these tools. The two dashboards are
self-contained HTML, the history and compare plots are PNG images, and the
scheduler writes org, TeX, and PDF files. This view renders the first two and
names the rest, and every one of them can be opened in the program the desktop
would use, because a preview is a convenience rather than a replacement.

The HTML path prefers ``QtWebEngineWidgets`` when it is installed, because the
dashboards use modern CSS that the rich-text widget of Qt renders only roughly.
The web engine ships as a separate package, so its absence is normal and the
view falls back to the rich-text widget with a line saying what that costs.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .qt import Qt, QtCore, QtGui, QtWidgets, fixed_font, web_engine_view

HTML_SUFFIXES = {".html", ".htm"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}
TEXT_SUFFIXES = {".org", ".txt", ".csv", ".tex", ".ics", ".md", ".json"}

#: How much text is worth showing inline.  A long file is opened instead.
TEXT_LIMIT = 200_000


def web_engine_available() -> bool:
    """Return whether the optional web engine is installed."""
    return web_engine_view() is not None


class ArtifactView(QtWidgets.QWidget):
    """Render one file that a command produced."""

    def __init__(self, parent=None, prefer_web_engine: bool = True):
        super().__init__(parent)
        self.path: Optional[Path] = None
        self.use_web_engine = prefer_web_engine and web_engine_available()

        outer = QtWidgets.QVBoxLayout(self)

        bar = QtWidgets.QHBoxLayout()
        self.name_label = QtWidgets.QLabel("Nothing written yet")
        self.open_button = QtWidgets.QPushButton("Open outside")
        self.open_button.setToolTip("Open the file in the program the desktop uses")
        self.open_button.clicked.connect(self.open_outside)
        self.open_button.setEnabled(False)
        bar.addWidget(self.name_label, 1)
        bar.addWidget(self.open_button)
        outer.addLayout(bar)

        self.stack = QtWidgets.QStackedWidget()
        self.note = QtWidgets.QLabel("")
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setWordWrap(True)

        self.text = QtWidgets.QTextBrowser()
        self.text.setOpenExternalLinks(True)

        self.image_label = QtWidgets.QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_area = QtWidgets.QScrollArea()
        self.image_area.setWidget(self.image_label)
        self.image_area.setWidgetResizable(True)

        self.stack.addWidget(self.note)          # 0
        self.stack.addWidget(self.text)          # 1
        self.stack.addWidget(self.image_area)    # 2
        self.web = None
        if self.use_web_engine:                  # pragma: no cover - optional
            self.web = web_engine_view()()
            self.stack.addWidget(self.web)       # 3
        outer.addWidget(self.stack, 1)

        self.footer = QtWidgets.QLabel("")
        self.footer.setWordWrap(True)
        outer.addWidget(self.footer)
        self.clear()

    # -- state -------------------------------------------------------------
    def clear(self) -> None:
        self.path = None
        self.name_label.setText("Nothing written yet")
        self.open_button.setEnabled(False)
        self.note.setText("A command that writes a file shows it here.")
        self.stack.setCurrentIndex(0)
        self.footer.setText("")

    def kind(self, path: Path) -> str:
        """Return how ``path`` is shown: html, image, text, or other."""
        suffix = path.suffix.lower()
        if suffix in HTML_SUFFIXES:
            return "html"
        if suffix in IMAGE_SUFFIXES:
            return "image"
        if suffix in TEXT_SUFFIXES:
            return "text"
        return "other"

    # -- showing -----------------------------------------------------------
    def show_file(self, path) -> bool:
        """Show the file at ``path``.  Return whether anything was rendered."""
        path = Path(path)
        self.path = path
        self.name_label.setText(str(path))
        self.open_button.setEnabled(path.exists())
        self.footer.setText("")

        if not path.exists():
            self.note.setText(f"{path} is not there any more.")
            self.stack.setCurrentIndex(0)
            return False

        kind = self.kind(path)
        if kind == "html":
            return self._show_html(path)
        if kind == "image":
            return self._show_image(path)
        if kind == "text":
            return self._show_text(path)
        self.note.setText(
            f"{path.name} cannot be shown here.\n"
            "Use Open outside to view it.")
        self.stack.setCurrentIndex(0)
        return False

    def _show_html(self, path: Path) -> bool:
        if self.web is not None:                 # pragma: no cover - optional
            self.web.setUrl(QtCore.QUrl.fromLocalFile(str(path.resolve())))
            self.stack.setCurrentWidget(self.web)
            return True
        # A report is column-aligned and a dashboard is not, so the one
        # text widget carries whichever font the file needs.
        self.text.setFont(QtWidgets.QApplication.font())
        self.text.setHtml(path.read_text(encoding="utf-8"))
        self.stack.setCurrentWidget(self.text)
        self.footer.setText(
            "Shown with the rich-text widget, which ignores much of the "
            "dashboard's styling. Open outside for the real page, or install "
            "PyQtWebEngine for a faithful preview here.")
        return True

    def _show_image(self, path: Path) -> bool:
        pixmap = QtGui.QPixmap(str(path))
        if pixmap.isNull():
            self.note.setText(f"{path.name} is not an image Qt can read.")
            self.stack.setCurrentIndex(0)
            return False
        self.image_label.setPixmap(pixmap)
        self.image_label.resize(pixmap.size())
        self.stack.setCurrentWidget(self.image_area)
        self.footer.setText(f"{pixmap.width()} by {pixmap.height()} pixels")
        return True

    def _show_text(self, path: Path) -> bool:
        size = path.stat().st_size
        if size > TEXT_LIMIT:
            self.note.setText(
                f"{path.name} is {size // 1024} kB, which is too long to show "
                "here. Use Open outside.")
            self.stack.setCurrentIndex(0)
            return False
        self.text.setFont(fixed_font())
        self.text.setPlainText(path.read_text(encoding="utf-8"))
        self.stack.setCurrentWidget(self.text)
        return True

    def open_outside(self) -> bool:
        """Hand the file to the desktop.  Return whether the call was made."""
        if self.path is None or not self.path.exists():
            return False
        return QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(self.path.resolve())))


class PreviewDock(QtWidgets.QWidget):
    """One tab per file a command produced, newest first."""

    def __init__(self, parent=None, limit: int = 6):
        super().__init__(parent)
        self.limit = limit
        layout = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.tabs.removeTab)
        layout.addWidget(self.tabs)
        self.empty = ArtifactView(self)
        self.tabs.addTab(self.empty, "Preview")

    def show_files(self, paths: List[str]) -> None:
        """Show each path, replacing a tab that already holds the same file."""
        for path in paths:
            self.show_one(path)

    def show_one(self, path) -> ArtifactView:
        name = Path(path).name
        for index in range(self.tabs.count()):
            view = self.tabs.widget(index)
            if view.path is not None and Path(view.path).name == name:
                view.show_file(path)
                self.tabs.setCurrentIndex(index)
                return view
        view = ArtifactView(self)
        view.show_file(path)
        if self.tabs.count() == 1 and self.tabs.widget(0).path is None:
            self.tabs.removeTab(0)               # drop the placeholder
        self.tabs.addTab(view, name)
        while self.tabs.count() > self.limit:
            self.tabs.removeTab(0)
        self.tabs.setCurrentWidget(view)
        return view
