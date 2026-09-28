"""The main window: a tab per stage of the weekly loop.

The tab order follows the loop itself, from editing the weekly table through
generating the schedule to comparing the week that was planned with the week
that happened. A tab holds generated forms, one per subcommand, and a tab whose
feature a later build step covers holds a placeholder that names the step.

Two programs feed the tabs. ``writing-habit`` is this package, and
``writing-schedule`` is the optional companion that owns the weekly table. When
the companion is absent its tabs explain how to install it rather than
disappearing, because a missing optional dependency is a fact worth stating.
"""

from __future__ import annotations

from typing import List, Tuple

from .. import __version__
from . import argspec, links, runner, settings
from .command_panel import CommandPanel
from .report_view import PreviewDock
import os

from .qt import Qt, QtCore, QtGui, QtWidgets, fixed_font, versions

HABIT = "writing-habit"
SCHEDULE = "writing-schedule"

#: (tab title, purpose, ((program, subcommand), ...), the step that fills it).
TABS: List[Tuple[str, str, Tuple[Tuple[str, str], ...], int]] = [
    ("Schedule", "Read the weekly block table, check it for clashes, and scaffold a new one.",
     ((SCHEDULE, "template"), (SCHEDULE, "check")), 4),
    ("Generate", "Write the dated schedule .org and the .ics for a week or a day.",
     ((SCHEDULE, "generate"), (SCHEDULE, "export"), (SCHEDULE, "weeks")), 3),
    ("Sheets", "Draw the printable time-block sheets.",
     ((SCHEDULE, "sheets"),), 3),
    ("Plan", "Create the database and load a weekly table into it.",
     ((HABIT, "initdb"), (HABIT, "plan import")), 2),
    ("Track", "Import actual sessions, or add one by hand.",
     ((HABIT, "track import"), (HABIT, "track add")), 2),
    ("Compare", "Report planned against actual for one week.",
     ((HABIT, "compare"), (HABIT, "dashboard")), 2),
    ("History", "The cross-week adherence series.",
     ((HABIT, "history"),), 2),
    ("Context", "Tag a week as teaching, meeting, or data collection.",
     ((HABIT, "context set"), (HABIT, "context clear"), (HABIT, "context list")), 2),
    ("Seasons", "The grouped-adherence dashboard, and the schedule-code reader.",
     ((HABIT, "seasons"), (HABIT, "name")), 2),
]

#: Tabs that gain more than generated forms in a later step.
PENDING = {}

MISSING_SCHEDULE = (
    "<h3>{title}</h3>"
    "<p>{purpose}</p>"
    "<p>These commands come from the <b>writing-schedule</b> package, which is "
    "not installed. Add it with:</p>"
    "<p><tt>pip install \"writing-habit[gui]\"</tt></p>"
    "<p>or, from a checkout, <tt>pip install -e path/to/writing-schedule-py/"
    "writing_schedule</tt></p>"
)

ABOUT = (
    "<h3>writing-habit {version}</h3>"
    "<p>A point-and-click front end for the writing-habit tracker and the "
    "writing-schedule generator.</p>"
    "<p>{binding}</p>"
    "<p>The library and the command line are under the MIT license. This "
    "graphical extra uses PyQt5, which is distributed under the GPL.</p>"
)


def _message(html: str) -> QtWidgets.QWidget:
    """Return a centered block of text, used where a tab has no form to show."""
    page = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(page)
    layout.setAlignment(Qt.AlignCenter)
    label = QtWidgets.QLabel(html)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignCenter)
    layout.addWidget(label)
    return page


class MainWindow(QtWidgets.QMainWindow):
    """The window that holds the tab stack, the log dock, and the status bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"writing-habit {__version__}")
        self.resize(1040, 800)

        self.specs = {HABIT: {}, SCHEDULE: {}}
        from .. import cli
        self.specs[HABIT] = argspec.commands(cli.build_parser())
        if runner.available(SCHEDULE):
            from writing_schedule import cli as ws_cli
            self.specs[SCHEDULE] = argspec.commands(ws_cli.build_parser())

        self.panels = {}
        self.tabs = QtWidgets.QTabWidget(self)
        for title, purpose, commands, step in TABS:
            self.tabs.addTab(self._page(title, purpose, commands, step), title)
        self.setCentralWidget(self.tabs)

        self.log = QtWidgets.QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setFont(fixed_font())
        self.log.setPlaceholderText(
            "Every command that runs prints here, together with the equivalent "
            "shell command."
        )
        dock = QtWidgets.QDockWidget("Session log", self)
        dock.setObjectName("session-log")
        dock.setWidget(self.log)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.log_dock = dock

        self.preview = PreviewDock(self)
        preview_dock = QtWidgets.QDockWidget("Preview", self)
        preview_dock.setObjectName("preview")
        preview_dock.setWidget(self.preview)
        self.addDockWidget(Qt.RightDockWidgetArea, preview_dock)
        preview_dock.hide()                      # until a command writes something
        self.preview_dock = preview_dock

        self._build_menus()
        self.statusBar().showMessage(self._status_text())
        self.docs_button = QtWidgets.QPushButton("Documentation")
        self.docs_button.setToolTip(
            f"Open the guide to this interface in your web browser\n{links.DOCS_URL}")
        self.docs_button.clicked.connect(lambda: self.open_web_page(links.DOCS_URL))
        self.readme_button = QtWidgets.QPushButton("README")
        self.readme_button.setToolTip(
            f"Open the README on GitHub in your web browser\n{links.README_URL}")
        self.readme_button.clicked.connect(lambda: self.open_web_page(links.README_URL))
        for button in (self.docs_button, self.readme_button):
            self.statusBar().addPermanentWidget(button)
        self.quit_button = QtWidgets.QPushButton("Quit")
        self.quit_button.setToolTip(
            "Leave writing-habit. Unsaved work is offered for saving first.")
        self.quit_button.clicked.connect(self.close)
        self.statusBar().addPermanentWidget(self.quit_button)

        settings.restore_window(self)

        # The grid starts on the table the writer had open, so the Schedule tab
        # shows what the command forms will read rather than an empty grid.
        editor = getattr(self, "editor", None)
        if editor is not None:
            editor.open_most_recent()

    # -- construction ------------------------------------------------------
    def _page(self, title, purpose, commands, step) -> QtWidgets.QWidget:
        """Return a tab holding the forms it can build, and a note where it cannot."""
        available = [(prog, name) for prog, name in commands
                     if name in self.specs.get(prog, {})]
        if not available:
            if any(prog == SCHEDULE for prog, _name in commands):
                return _message(MISSING_SCHEDULE.format(title=title, purpose=purpose))
            return _message(
                f"<h3>{title}</h3><p>{purpose}</p>"
                f"<p><i>Build step {step} fills this tab.</i></p>")

        pages = []
        if title == "Schedule":
            pages.append(("weekly table", self._schedule_editor()))
        pending = PENDING.get(title)
        if pending:
            step_number, description = pending
            pages.append((
                "not built yet",
                _message(f"<p>{description}</p>"
                         f"<p><i>Build step {step_number} adds it here.</i></p>"),
            ))
        pages += [(f"{prog} {name}", self._panel(prog, name))
                  for prog, name in available]

        if len(pages) == 1:
            return pages[0][1]
        box = QtWidgets.QToolBox()
        for label, widget in pages:
            box.addItem(widget, label)
        return box

    def _schedule_editor(self):
        """Build the weekly-table view and connect it to the session log."""
        from .schedule_editor import ScheduleEditor

        editor = ScheduleEditor(self)
        editor.logged.connect(self.append_log)
        editor.opened.connect(self.use_table)
        editor.saved.connect(self.use_table)
        self.editor = editor
        return editor

    def _panel(self, prog: str, name: str) -> CommandPanel:
        panel = CommandPanel(self.specs[prog][name], prog=prog, parent=self)
        panel.logged.connect(self.append_log)
        panel.finished.connect(lambda *_a: self.refresh_status())
        panel.produced.connect(self.show_output)
        panel.guard = self.confirm_disk_is_current
        self.panels[f"{prog} {name}"] = panel
        self.panels.setdefault(name, panel)      # short key for the tracker
        return panel

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        quit_action = file_menu.addAction("&Quit")
        # Command-Q on macOS, Control-Q on X11. Windows has no standard
        # sequence for this, so the familiar one is supplied there.
        keys = QtGui.QKeySequence(QtGui.QKeySequence.Quit)
        if keys.isEmpty():
            keys = QtGui.QKeySequence("Ctrl+Q")
        quit_action.setShortcut(keys)
        quit_action.setMenuRole(QtWidgets.QAction.QuitRole)
        quit_action.triggered.connect(self.close)
        self.quit_action = quit_action

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.log_dock.toggleViewAction())
        view_menu.addAction(self.preview_dock.toggleViewAction())
        clear = view_menu.addAction("&Clear session log")
        clear.triggered.connect(self.log.clear)

        help_menu = self.menuBar().addMenu("&Help")
        docs_action = help_menu.addAction("&Documentation")
        docs_action.triggered.connect(lambda: self.open_web_page(links.DOCS_URL))
        readme_action = help_menu.addAction("&README on GitHub")
        readme_action.triggered.connect(lambda: self.open_web_page(links.README_URL))
        help_menu.addSeparator()
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self.show_about)

    # -- helpers -----------------------------------------------------------
    #: Hands a URL to the desktop.  A test replaces it so no browser opens.
    launch_url = staticmethod(
        lambda url: QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)))

    def open_web_page(self, url: str) -> bool:
        """Open ``url`` in the default web browser.  Return whether it opened.

        The desktop decides which browser, exactly as a click on a link in any
        other program would. A failure is logged with the address, so the
        writer can paste it into a browser by hand.
        """
        opened = bool(self.launch_url(url))
        if opened:
            self.append_log(f"Opened {url} in the web browser")
        else:
            self.append_log(f"Could not open a web browser. The page is {url}")
            self.statusBar().showMessage(f"Could not open {url}", 8000)
        return opened

    def _status_text(self) -> str:
        db = settings.get("db")
        head = f"Database: {db}" if db else "No database chosen yet"
        if not self.specs[SCHEDULE]:
            head += "   |   writing-schedule not installed"
        return head

    def refresh_status(self) -> None:
        """Name the database the last command used, so a wrong one is visible."""
        self.statusBar().showMessage(self._status_text())

    def show_output(self, paths) -> None:
        """Show what a command wrote, and raise the dock the first time."""
        if not paths:
            return
        self.preview.show_files(list(paths))
        self.preview_dock.show()
        self.preview_dock.raise_()
        # The command already printed what it wrote, so the log stays quiet.

    def append_log(self, text: str) -> None:
        """Add one line to the session log."""
        self.log.appendPlainText(text.rstrip("\n"))

    def use_table(self, path: str) -> int:
        """Fill the table argument of every form that has one.  Return how many.

        Opening a table in the grid, or saving it under a new name, is the act
        that decides which week the commands work on, so the forms follow it.
        """
        filled, seen = 0, set()
        for panel in self.panels.values():
            if id(panel) in seen:
                continue
            seen.add(id(panel))
            if panel.set_table(path):
                filled += 1
        return filled

    # -- running -----------------------------------------------------------
    def confirm_disk_is_current(self, argv) -> bool:
        """Stop a run that would read a file the grid has not written yet.

        A command reads the file on disk, while the grid holds an edit until it
        is saved, so running before saving quietly uses the old version. The
        schedule then comes out with none of the blocks the writer can see on
        the screen, and nothing says why.
        """
        editor = getattr(self, "editor", None)
        table = getattr(editor, "table", None)
        if table is None or not table.dirty or not table.path:
            return True
        target = os.path.realpath(str(table.path))
        if not any(os.path.realpath(str(a)) == target for a in argv):
            return True                 # the command does not read that file

        name = os.path.basename(target)
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("Unsaved changes to the table")
        box.setText(f"{name} has edits in the grid that are not on disk.")
        box.setInformativeText(
            "The command reads the file, so it would use the version without "
            "those edits.")
        save = box.addButton("Save and run", QtWidgets.QMessageBox.AcceptRole)
        anyway = box.addButton("Run on the saved version",
                               QtWidgets.QMessageBox.DestructiveRole)
        box.addButton(QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(save)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is save:
            return editor.save() is not None
        return clicked is anyway

    # -- leaving -----------------------------------------------------------
    def running_commands(self):
        """Return the names of the commands still running, without repeats."""
        seen, names = set(), []
        for name, panel in self.panels.items():
            if getattr(panel, "worker", None) is None or id(panel) in seen:
                continue
            seen.add(id(panel))
            names.append(name)
        return names

    def unsaved_table(self) -> bool:
        """Whether the weekly table holds edits that are not on disk."""
        editor = getattr(self, "editor", None)
        table = getattr(editor, "table", None)
        return bool(table is not None and table.dirty)

    def confirm_exit(self) -> bool:
        """Ask about work in progress.  Return whether leaving is agreed."""
        running = self.running_commands()
        if running:
            box = QtWidgets.QMessageBox(self)
            box.setIcon(QtWidgets.QMessageBox.Warning)
            box.setWindowTitle("A command is still running")
            box.setText(f"{running[0]} has not finished.")
            box.setInformativeText(
                "Leaving now stops it part way, which can leave the database "
                "or a report half written.")
            waiting = box.addButton("Keep waiting",
                                    QtWidgets.QMessageBox.RejectRole)
            leaving = box.addButton("Quit anyway",
                                    QtWidgets.QMessageBox.DestructiveRole)
            box.setDefaultButton(waiting)
            box.exec_()
            if box.clickedButton() is not leaving:
                return False

        if self.unsaved_table():
            answer = QtWidgets.QMessageBox.question(
                self, "Unsaved weekly table",
                "The weekly table has changes that are not written to disk.",
                QtWidgets.QMessageBox.Save
                | QtWidgets.QMessageBox.Discard
                | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Save)
            if answer == QtWidgets.QMessageBox.Cancel:
                return False
            if answer == QtWidgets.QMessageBox.Save:
                if self.editor.save() is None:   # the file dialog was dismissed
                    return False
        return True

    def closeEvent(self, event) -> None:
        """One check for every way out: the button, the menu, and the corner."""
        if not self.confirm_exit():
            event.ignore()
            return
        settings.save_window(self)
        event.accept()

    def show_about(self) -> None:
        QtWidgets.QMessageBox.about(
            self,
            "About writing-habit",
            ABOUT.format(version=__version__, binding=versions()),
        )
