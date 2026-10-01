"""The weekly-table view, with the four readings that make a plan reviewable.

The grid answers what the week looks like. Four panels beside it answer whether
the week holds together. The name panel gives the canonical file name for the
grid, or the reason the grid cannot be named. The clashes panel lists the
overlapping blocks and the grid tints the offending cells, which is the
graphical form of ``writing-schedule check``. The totals panel gives planned
minutes by day, by project, and by activity. The legend panel resolves every
project letter against the legend, so an unknown letter shows before the file
is used rather than after.

A cell edit and a legend edit rewrite one line of the file and leave every other
line alone, so a saved table differs from the one on disk only where the writer
changed it. Saving offers the canonical file name when the grid has one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import external_editor, settings
from .legend_model import (CODE, DESCRIPTION, LegendModel, RISK,
                           RISK_CHOICES, RiskDelegate)
from .qt import Qt, QtGui, QtWidgets, pyqtSignal
from .table_model import TIME_COLUMN, CodeDelegate, WeeklyTableModel
from .weekly_table import BLOCK, WeeklyTable


def _plain(read_only: bool = True) -> QtWidgets.QPlainTextEdit:
    widget = QtWidgets.QPlainTextEdit()
    widget.setReadOnly(read_only)
    return widget


class ScheduleEditor(QtWidgets.QWidget):
    """Open a weekly table, show it, and report what it says."""

    logged = pyqtSignal(str)
    opened = pyqtSignal(str)
    saved = pyqtSignal(str)
    edited = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table: Optional[WeeklyTable] = None
        self.model = WeeklyTableModel(parent=self)

        outer = QtWidgets.QVBoxLayout(self)

        bar = QtWidgets.QHBoxLayout()
        self.open_button = QtWidgets.QPushButton("Open table")
        self.open_button.clicked.connect(self.choose)
        self.new_button = QtWidgets.QPushButton("New from template")
        # clicked carries a checked flag, which would arrive as the project
        # count, so the slot is called with no argument at all.
        self.new_button.clicked.connect(lambda: self.scaffold())
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_button.clicked.connect(self.save)
        self.save_as_button = QtWidgets.QPushButton("Save as")
        self.save_as_button.clicked.connect(self.save_as)
        self.rename_button = QtWidgets.QPushButton("Rename to canonical")
        self.rename_button.setToolTip(
            "Move the file to the name its grid gives it, so the tracker files "
            "the week under the right schedule shape")
        self.rename_button.clicked.connect(self.rename_to_canonical)
        self.reload_button = QtWidgets.QPushButton("Reload")
        self.reload_button.clicked.connect(self.reload)
        self.external_button = QtWidgets.QPushButton("Open in editor")
        self.external_button.setToolTip(
            "Open the table file in the editor named by WHGEDITOR in ~/.bashrc, "
            "or in the system's default text editor. Press Reload after saving "
            "there.")
        self.external_button.clicked.connect(lambda: self.open_externally())
        self.insert_above_button = QtWidgets.QPushButton("Insert above")
        self.insert_above_button.setToolTip(
            "Add an empty time block above the selected row")
        self.insert_above_button.clicked.connect(lambda: self.insert_row(above=True))
        self.insert_below_button = QtWidgets.QPushButton("Insert below")
        self.insert_below_button.setToolTip(
            "Add an empty time block below the selected row")
        self.insert_below_button.clicked.connect(lambda: self.insert_row(above=False))
        self.move_up_button = QtWidgets.QPushButton("Move up")
        self.move_up_button.setToolTip(
            "Shift the selected time block one row up (Alt+Up). Past a section "
            "header it joins the section above.")
        self.move_up_button.clicked.connect(lambda: self.move_row(up=True))
        self.move_down_button = QtWidgets.QPushButton("Move down")
        self.move_down_button.setToolTip(
            "Shift the selected time block one row down (Alt+Down). Past a "
            "section header it joins the section below.")
        self.move_down_button.clicked.connect(lambda: self.move_row(up=False))
        self.path_label = QtWidgets.QLabel("No table open")
        # A long path would otherwise set the window's minimum width.
        self.path_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                                      QtWidgets.QSizePolicy.Preferred)
        for button in (self.open_button, self.new_button, self.save_button,
                       self.save_as_button, self.rename_button, self.reload_button,
                       self.external_button, self.insert_above_button,
                       self.insert_below_button, self.move_up_button,
                       self.move_down_button):
            bar.addWidget(button)
        bar.addWidget(self.path_label, 1)
        outer.addLayout(bar)
        for button in (self.save_button, self.save_as_button,
                       self.rename_button, self.reload_button,
                       self.external_button, self.insert_above_button,
                       self.insert_below_button, self.move_up_button,
                       self.move_down_button):
            button.setEnabled(False)

        #: Starts the external editor.  A test replaces it to run nothing.
        self.launch_editor = external_editor.open_in_editor

        splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.view = QtWidgets.QTableView()
        self.view.setModel(self.model)
        self.view.setAlternatingRowColors(True)
        self.view.horizontalHeader().setStretchLastSection(False)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self.view.setItemDelegate(CodeDelegate(self.view))
        self.model.edited.connect(self.on_grid_edit)
        self.view.selectionModel().currentChanged.connect(
            lambda *_args: self._on_current_changed())
        splitter.addWidget(self.view)
        # Alt+Up and Alt+Down move the selected block, as M-up and M-down move
        # a row of an org table in Emacs. The shortcuts belong to the grid, so
        # they do nothing while the legend or a form has the focus.
        for keys, up in (("Alt+Up", True), ("Alt+Down", False)):
            shortcut = QtWidgets.QShortcut(QtGui.QKeySequence(keys), self.view)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda up=up: self.move_row(up=up))

        self.panels = QtWidgets.QTabWidget()
        self.name_panel = _plain()
        self.clash_panel = _plain()
        self.totals_panel = _plain()
        self.legend_panel = _plain()
        self.panels.addTab(self.name_panel, "Name")
        self.panels.addTab(self.clash_panel, "Clashes")
        self.panels.addTab(self.totals_panel, "Totals")
        self.panels.addTab(self.legend_panel, "Legend")
        splitter.addWidget(self.panels)
        splitter.setSizes([620, 380])

        self.legend_model = LegendModel(parent=self)
        self.legend_model.edited.connect(self.on_edit)
        self.legend_view = QtWidgets.QTableView()
        self.legend_view.setModel(self.legend_model)
        self.legend_view.setItemDelegateForColumn(RISK, RiskDelegate(self.legend_view))
        self.legend_view.horizontalHeader().setStretchLastSection(False)
        self._fit_legend_columns()

        rows = QtWidgets.QSplitter(Qt.Vertical)
        rows.addWidget(splitter)
        legend_box = QtWidgets.QGroupBox("Legend")
        legend_layout = QtWidgets.QVBoxLayout(legend_box)
        legend_bar = QtWidgets.QHBoxLayout()
        self.project_above_button = QtWidgets.QPushButton("Insert project above")
        self.project_above_button.setToolTip(
            "Add a project to the legend above the selected project")
        self.project_above_button.clicked.connect(
            lambda: self.insert_project(above=True))
        self.project_below_button = QtWidgets.QPushButton("Insert project below")
        self.project_below_button.setToolTip(
            "Add a project to the legend below the selected project, or at "
            "the end when none is selected")
        self.project_below_button.clicked.connect(
            lambda: self.insert_project(above=False))
        for button in (self.project_above_button, self.project_below_button):
            button.setEnabled(False)
            legend_bar.addWidget(button)
        legend_bar.addStretch(1)
        legend_layout.addLayout(legend_bar)
        legend_layout.addWidget(self.legend_view)
        rows.addWidget(legend_box)
        rows.setSizes([520, 220])
        outer.addWidget(rows, 1)

        self.note = QtWidgets.QLabel(
            "<i>A cell takes a legend code. An edit rewrites one line of the "
            "file; the rest is left alone. Select a time to tint in yellow the "
            "rows that do not overlap it. Alt+Up and Alt+Down move the "
            "selected block.</i>")
        self.note.setWordWrap(True)
        outer.addWidget(self.note)

    # -- layout ------------------------------------------------------------
    def _fit_columns(self) -> None:
        """Size the Time column to its text and share the rest among the days.

        Sizing every column to its contents collapses the seven day columns,
        because a cell holds one letter, and a stretching last section then
        swallows the width they gave up, which is why Sunday ended up wider
        than the other six put together. Stretching the day columns instead
        gives each an equal share of whatever the window offers, and keeps them
        equal when the window is resized.
        """
        header = self.view.horizontalHeader()
        header.setStretchLastSection(False)
        columns = self.model.columnCount()
        if not columns:
            return
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        for column in range(1, columns):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.Stretch)

    def _fit_legend_columns(self) -> None:
        """Give the legend's width to the description, which is the long field."""
        header = self.legend_view.horizontalHeader()
        header.setStretchLastSection(False)
        modes = {CODE: QtWidgets.QHeaderView.ResizeToContents,
                 DESCRIPTION: QtWidgets.QHeaderView.Stretch,
                 RISK: QtWidgets.QHeaderView.ResizeToContents}
        for column, mode in modes.items():
            if column < self.legend_model.columnCount():
                header.setSectionResizeMode(column, mode)

    # -- opening -----------------------------------------------------------
    def choose(self) -> None:
        start = settings.get("table_dir") or str(Path.home())
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open a weekly table", start, "Org files (*.org);;All files (*)")
        if path:
            self.open(path)

    def open(self, path: str) -> None:
        """Load the table at ``path`` and refresh every panel."""
        try:
            table = WeeklyTable.from_file(path)
        except OSError as exc:
            self.logged.emit(f"Could not open {path}: {exc}")
            return
        self.table = table
        self.model.set_table(table)
        self.legend_model.set_table(table)
        settings.put("table_dir", str(Path(path).parent))
        settings.put("table", str(Path(path)))
        self._fit_columns()
        for button in (self.save_button, self.save_as_button, self.reload_button,
                       self.project_above_button, self.project_below_button):
            button.setEnabled(True)
        self._update_insert_buttons()
        self.refresh()
        self.logged.emit(f"Opened {path}")
        self.opened.emit(path)

    def most_recent(self) -> Optional[str]:
        """Return the table to show at startup, or ``None`` when there is none.

        The table last opened is the one wanted, because a writer works a week
        at a time. When that file has been moved or deleted, the newest org
        file in the folder of tables stands in for it, which is also the answer
        the first time the window is ever opened after a table is saved.
        """
        remembered = settings.get("table")
        if remembered and Path(remembered).is_file():
            return remembered
        folder = settings.get("table_dir")
        if not folder or not Path(folder).is_dir():
            return None
        try:
            tables = [p for p in Path(folder).glob("*.org") if p.is_file()]
        except OSError:
            return None
        if not tables:
            return None
        newest = max(tables, key=lambda p: p.stat().st_mtime)
        return str(newest)

    def open_most_recent(self) -> Optional[str]:
        """Open the table from :meth:`most_recent`.  Return what was opened.

        A failure here is not worth a dialog at startup, because the writer did
        not ask for this file. The log carries the reason and the window opens
        with an empty grid, exactly as it did before.
        """
        path = self.most_recent()
        if path is None:
            return None
        try:
            self.open(path)
        except Exception as exc:                 # pragma: no cover - defensive
            self.logged.emit(f"Could not reopen {path}: {exc}")
            return None
        return path if self.table is not None else None

    def reload(self) -> None:
        if self.table is not None and self.table.path:
            self.open(self.table.path)

    # -- inserting rows ----------------------------------------------------
    def selected_document_row(self) -> Optional[int]:
        """Return the document row under the grid's current cell, or ``None``."""
        index = self.view.currentIndex()
        if self.table is None or not index.isValid():
            return None
        if not 0 <= index.row() < self.model.rowCount():
            return None
        return self.model.document_row(index.row())

    def _on_current_changed(self) -> None:
        self._update_insert_buttons()
        self._update_time_tint()

    def _update_time_tint(self) -> None:
        """Tint the blocks clear of the selected time, or clear the tint."""
        index = self.view.currentIndex()
        if index.isValid() and index.column() == TIME_COLUMN:
            self.model.set_time_anchor(index.row())
        else:
            self.model.set_time_anchor(None)

    def _update_insert_buttons(self) -> None:
        near = self.selected_document_row()
        ready = near is not None
        self.insert_above_button.setEnabled(ready)
        self.insert_below_button.setEnabled(ready)
        self.move_up_button.setEnabled(ready and self.table.can_move(near, True))
        self.move_down_button.setEnabled(ready and self.table.can_move(near, False))

    def insert_row(self, above: bool, times: Optional[str] = None) -> Optional[int]:
        """Add an empty time block beside the selected row.

        The writer confirms the time range in a small dialog, which starts
        from a block of the same length as its neighbour placed flush against
        it. ``times`` skips the dialog. Return the document index of the new
        row, or ``None`` when nothing was inserted.
        """
        near = self.selected_document_row()
        if near is None:
            self.logged.emit("Select a row of the grid before inserting a row")
            return None
        if times is None:
            start, end = self.table.suggest_times(near, above)
            where = "above" if above else "below"
            times, accepted = QtWidgets.QInputDialog.getText(
                self, "Insert a time block",
                f"Time range of the new row {where} the selection (HH:MM-HH:MM)",
                QtWidgets.QLineEdit.Normal, f"{start}-{end}")
            if not accepted:
                return None
        start, _sep, end = (times or "").strip().partition("-")
        try:
            at = self.table.insert_block(near, above, start.strip(), end.strip())
        except ValueError as exc:
            self.logged.emit(f"Cannot insert a row: {exc}")
            QtWidgets.QMessageBox.information(self, "Insert a row", str(exc))
            return None

        column = max(self.view.currentIndex().column(), 1)
        self.model.set_table(self.table)
        self.legend_model.set_table(self.table)     # its row indexes moved
        self._fit_columns()
        self._fit_legend_columns()
        grid_row = self.model._rows.index(at)
        self.view.setCurrentIndex(self.model.index(grid_row, column))
        self._update_insert_buttons()
        start, end = self.table.rows[at].parsed
        self.logged.emit(f"Inserted an empty {start}-{end} block in "
                         f"{self.table.rows[at].section}")
        self.on_edit()
        return at

    # -- moving rows -------------------------------------------------------
    def move_row(self, up: bool) -> Optional[int]:
        """Shift the selected time block one row up or down.

        The selection follows the row, so pressing the button again keeps
        moving the same block. Return the block's new document index, or
        ``None`` when nothing moved.
        """
        near = self.selected_document_row()
        if near is None:
            self.logged.emit("Select a time block of the grid before moving a row")
            return None
        if not self.table.can_move(near, up):
            kind = self.table.rows[near].kind
            if kind == BLOCK:
                self.logged.emit("The row is already at the "
                                 + ("top" if up else "bottom") + " of the grid")
            else:
                self.logged.emit("Only a time block moves. A section header "
                                 "stays where the file puts it.")
            return None
        before = self.table.rows[near].section
        at = self.table.move_block(near, up)

        column = self.view.currentIndex().column()
        self.model.set_table(self.table)
        self.legend_model.set_table(self.table)
        self._fit_columns()
        self._fit_legend_columns()
        grid_row = self.model._rows.index(at)
        self.view.setCurrentIndex(self.model.index(grid_row, max(column, 0)))
        self._on_current_changed()
        start, end = self.table.rows[at].parsed
        after = self.table.rows[at].section
        where = (f" into {after}" if after != before else "")
        self.logged.emit(f"Moved the {start}-{end} block "
                         + ("up" if up else "down") + where)
        self.on_edit()
        return at

    # -- inserting projects ------------------------------------------------
    def selected_legend_row(self) -> Optional[int]:
        """Return the document row of the selected legend entry, or ``None``."""
        index = self.legend_view.currentIndex()
        if self.table is None or not index.isValid():
            return None
        if not 0 <= index.row() < self.legend_model.rowCount():
            return None
        return self.legend_model.document_row(index.row())

    def _ask_project(self, code: str):
        """Ask for a code, description, and risk tag.  Return them, or ``None``."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Insert a project")
        form = QtWidgets.QFormLayout(dialog)
        code_edit = QtWidgets.QLineEdit(code)
        code_edit.setMaxLength(4)
        description_edit = QtWidgets.QLineEdit()
        description_edit.setPlaceholderText("e.g. 0201dusp1, Sept 25")
        risk_box = QtWidgets.QComboBox()
        risk_box.addItems([label for label, _class in RISK_CHOICES])
        form.addRow("Code", code_edit)
        form.addRow("Description", description_edit)
        form.addRow("Risk tag", risk_box)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        description_edit.setFocus()
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return None
        risk = dict(RISK_CHOICES).get(risk_box.currentText())
        return code_edit.text(), description_edit.text(), risk

    def insert_project(self, above: bool, code: Optional[str] = None,
                       description: str = "",
                       risk: Optional[str] = None) -> Optional[int]:
        """Add a legend entry beside the selected one.  Return its document row.

        With no entry selected, a project inserted below goes to the end of the
        legend and one inserted above goes to the start. ``code`` skips the
        dialog, which otherwise offers the first letter not yet in use.
        """
        if self.table is None:
            return None
        near = self.selected_legend_row()
        if near is None:
            rows = self.table.legend_rows()
            near = rows[0] if (above and rows) else None
        if code is None:
            answer = self._ask_project(self.table.next_free_code())
            if answer is None:
                return None
            code, description, risk = answer
        try:
            at = self.table.insert_legend(near, above, code, description, risk)
        except ValueError as exc:
            self.logged.emit(f"Cannot insert a project: {exc}")
            QtWidgets.QMessageBox.information(self, "Insert a project", str(exc))
            return None

        if at <= max(self.model._rows, default=-1):
            self.model.set_table(self.table)    # a grid row moved down
        self.legend_model.set_table(self.table)
        self._fit_legend_columns()
        legend_row = self.legend_model._rows.index(at)
        self.legend_view.setCurrentIndex(
            self.legend_model.index(legend_row, DESCRIPTION))
        self.logged.emit(f"Inserted project {self.table.rows[at].parsed[0]} "
                         "in the legend")
        self.on_edit()
        return at

    # -- the external editor -----------------------------------------------
    def _ask_save_before_editing(self) -> str:
        """Return ``save``, ``saved``, or ``cancel`` for a table with unsaved edits."""
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("Unsaved edits")
        box.setText("The grid holds edits that are not in the file yet. "
                    "The editor will read the file.")
        save = box.addButton("Save and open", QtWidgets.QMessageBox.AcceptRole)
        stale = box.addButton("Open the saved version",
                              QtWidgets.QMessageBox.DestructiveRole)
        box.addButton(QtWidgets.QMessageBox.Cancel)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is save:
            return "save"
        if clicked is stale:
            return "saved"
        return "cancel"

    def open_externally(self) -> Optional[list]:
        """Open the table file in the writer's editor.  Return the command run."""
        if self.table is None or not self.table.path:
            self.logged.emit("Save the table to a file before opening it in an editor")
            return None
        if self.table.dirty:
            choice = self._ask_save_before_editing()
            if choice == "cancel":
                return None
            if choice == "save" and self.save() is None:
                return None
        try:
            argv, source = self.launch_editor(self.table.path)
        except OSError as exc:
            self.logged.emit(f"Could not start the editor: {exc}")
            QtWidgets.QMessageBox.warning(
                self, "Open in editor",
                f"Could not start the editor.\n\n{exc}\n\nSet WHGEDITOR in "
                f"~/.bashrc to a full path, such as\n"
                f'export WHGEDITOR="/opt/homebrew/bin/emacsclient -n"')
            return None
        self.logged.emit(f"Opened {self.table.path} with {' '.join(argv)} "
                         f"(editor from {source}). Press Reload after saving there.")
        return argv

    def on_edit(self) -> None:
        """Refresh the readings after an edit reaches the document."""
        self.refresh()
        self.edited.emit()

    def on_grid_edit(self) -> None:
        """A cell changed, so the legend may owe the grid a row.

        Only a grid edit syncs. A legend edit does not, because renaming a code
        there would otherwise remove the row being renamed and add back the one
        it replaced, and the writer would watch their edit bounce.
        """
        if self.table is not None and self.table.sync_legend():
            self.legend_model.set_table(self.table)
            self._fit_legend_columns()
        self.on_edit()

    def save(self) -> Optional[str]:
        """Write the table back to the file it came from."""
        if self.table is None:
            return None
        if not self.table.path:
            return self.save_as()
        path = self.table.save()
        self.refresh()
        self.logged.emit(f"Saved {path}")
        self.saved.emit(path)
        return path

    def suggested_name(self) -> str:
        """Return the canonical file name for the grid, or the current name."""
        code, _problem = self.table.code_or_problem() if self.table else (None, None)
        if code:
            return f"{code}.org"
        return Path(self.table.path).name if self.table and self.table.path else "week.org"

    def save_as(self) -> Optional[str]:
        """Write the table to a new file, offering its canonical name."""
        if self.table is None:
            return None
        folder = Path(self.table.path).parent if self.table.path else Path(
            settings.get("table_dir") or Path.home())
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save the weekly table", str(folder / self.suggested_name()),
            "Org files (*.org);;All files (*)")
        if not path:
            return None
        written = self.table.save(path)
        self.refresh()
        self.logged.emit(f"Saved {written}")
        self.saved.emit(written)
        return written

    def rename_to_canonical(self) -> Optional[str]:
        """Move the open file to the canonical name of its grid."""
        if self.table is None:
            return None
        try:
            path = self.table.rename_to_canonical()
        except ValueError as exc:
            self.logged.emit(f"Cannot rename: {exc}")
            QtWidgets.QMessageBox.information(self, "Rename", str(exc))
            return None
        self.refresh()
        self.logged.emit(f"Renamed to {path}")
        self.saved.emit(path)
        return path

    def scaffold(self, projects: Optional[int] = None) -> None:
        """Start a blank table for N projects, using the scheduler's own scaffold."""
        from writing_schedule.template import template_string

        if projects is None:
            projects, accepted = QtWidgets.QInputDialog.getInt(
                self, "New weekly table", "Number of projects", 3, 1, 26)
            if not accepted:
                return
        self.table = WeeklyTable(template_string(int(projects)))
        self.model.set_table(self.table)
        self.legend_model.set_table(self.table)
        self.table.dirty = True
        for button in (self.save_button, self.save_as_button,
                       self.project_above_button, self.project_below_button):
            button.setEnabled(True)
        self.reload_button.setEnabled(False)
        self._update_insert_buttons()
        self._fit_columns()
        self.refresh()
        self.logged.emit(f"Scaffolded a blank table for {projects} project(s)")

    # -- readings ----------------------------------------------------------
    def refresh(self) -> None:
        """Recompute the four panels from the current table."""
        if self.table is None:
            return
        name = self.table.path or "(unsaved table)"
        self.path_label.setText(name + ("  *" if self.table.dirty else ""))
        self.path_label.setToolTip(name)
        self.save_button.setEnabled(self.table.dirty)
        self.external_button.setEnabled(bool(self.table.path))
        self.rename_button.setEnabled(
            bool(self.table.path) and not self.table.dirty
            and not self.table.name_matches_code())
        self.model.refresh()
        self.name_panel.setPlainText(self._name_text())
        self.clash_panel.setPlainText(self._clash_text())
        self.totals_panel.setPlainText(self._totals_text())
        self.legend_panel.setPlainText(self._legend_text())
        clashes = len(self.table.overlaps())
        self.panels.setTabText(1, "Clashes" if not clashes else f"Clashes ({clashes})")

    def _name_text(self) -> str:
        code, problem = self.table.code_or_problem()
        if code is None:
            return "This week has no canonical file name.\n\n" + problem
        lines = [f"Canonical file name:  {code}.org", ""]
        if self.table.path:
            stem = Path(self.table.path).stem
            if stem != code:
                lines.append(f"The file is named {stem}.org, which is not the "
                             f"canonical form of this grid.")
                lines.append("")
        from .. import name as namemod
        decoded = namemod.decode(code)
        lines.append(namemod.format_week(decoded))
        total, activities, projects = namemod.summary(decoded)
        lines.append("")
        lines.append(f"{total} blocks over {len(decoded)} days")
        lines.append("by activity: " + ", ".join(
            f"{count} {activity}" for activity, count in sorted(activities.items())))
        lines.append("by project:  " + ", ".join(
            f"{project} ({count})" for project, count in sorted(projects.items())))
        return "\n".join(lines)

    def _clash_text(self) -> str:
        from writing_schedule.overlap import overlap_lines
        conflicts = self.table.overlaps()
        if not conflicts:
            return "No overlapping time blocks."
        head = [f"{len(conflicts)} overlapping pair(s). The cells are tinted.", ""]
        return "\n".join(head + list(overlap_lines(conflicts)))

    def _totals_text(self) -> str:
        totals = self.table.totals()
        lines = ["Planned minutes", ""]
        for title, key in (("By day", "day"), ("By project", "project"),
                           ("By activity", "category")):
            lines.append(title)
            for label, minutes in totals[key].items():
                hours = minutes / 60
                lines.append(f"  {label:<12} {minutes:>5} min  ({hours:.1f} h)")
            lines.append("")
        grand = sum(totals["day"].values())
        lines.append(f"Week total   {grand} min  ({grand / 60:.1f} h)")
        unknown = self.table.unknown_sections()
        if unknown:
            lines += ["", "Sections with no activity category, counted as "
                          "generative by the plan importer:"]
            lines += [f"  {name}" for name in unknown]
        return "\n".join(lines)

    def _legend_text(self) -> str:
        rows, problems = self.table.legend_check()
        lines = ["Project letters resolved against the legend", ""]
        for letter, code, description, risk, status in rows:
            tag = f" [{risk}]" if risk else ""
            lines.append(f"  {letter:<4} -> {code:<5} {description}{tag}  ({status})")
        if problems:
            lines += ["", "Unresolved: " + ", ".join(problems)]
        else:
            lines += ["", "Every project letter resolves to one legend entry."]
        unused = [code for code in self.table.legend()
                  if code not in {row[1] for row in rows}]
        if unused:
            lines += ["", "Legend entries not used this week: " + ", ".join(unused)]

        duplicates = self.table.duplicate_legend_codes()
        if duplicates:
            lines += ["", "Codes defined more than once. The readers keep the "
                          "first and drop the rest:"]
            for code, descriptions in duplicates.items():
                lines.append(f"  {code}: " + " | ".join(descriptions))

        stray = self.table.stray_risk_tags()
        if stray:
            lines += ["", "Risk tags that name no class, so these projects stay "
                          "out of the barbell comparison:"]
            for code, tag in stray:
                lines.append(f"  {code}: :{tag}:  (write :safe: or :speculative:)")
        return "\n".join(lines)
