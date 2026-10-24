"""The semester project lists, shown beside the legend in the same columns.

A weekly legend lists only the projects of the week, which keeps it short. The
semester lists hold the rest: the projects of the current semester, and those
that wait for the next two. Each list is a panel with the legend's columns and
buttons, plus one that copies the selected project into this week's legend.
See :mod:`writing_habit.project_lists` for how the lists are stored.
"""

from __future__ import annotations

import re
from typing import Optional

from ..name import CODE_PATTERN, join_deadline, valid_deadline
from ..project_lists import CARRIED, COMPLETED, CURRENT, GRASSCATCHER, Entry
from .legend_model import (ACTIVITY, ACTIVITY_CHOICES, ActivityDelegate, CODE,
                           DEADLINE, HEADERS, PROJECT, RISK, RISK_CHOICES,
                           DeadlineDelegate, RiskDelegate)
from .qt import Qt, QtCore, QtWidgets, pyqtSignal
from .weekly_table import RISK_TO_TAG


class ProjectListModel(QtCore.QAbstractTableModel):
    """One named list of a :class:`~writing_habit.gui.weekly_table.WeeklyTable`."""

    edited = pyqtSignal()

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.table = None

    def set_table(self, table) -> None:
        self.beginResetModel()
        self.table = table
        self.endResetModel()

    def entries(self):
        return self.table.lists.entries(self.name) if self.table is not None else []

    # -- Qt ----------------------------------------------------------------
    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.entries())

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if self.name == GRASSCATCHER and section == PROJECT:
                return "Task"
            return HEADERS[section]
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        entry = self.entries()[index.row()]
        column = index.column()
        if column == CODE:
            return entry.code or ""
        if column == PROJECT:
            return entry.project
        if column == DEADLINE:
            return entry.deadline or ""
        if column == RISK:
            return RISK_TO_TAG.get(entry.risk or "", "none")
        return entry.activity or "none"

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        if role != Qt.EditRole or not index.isValid() or self.table is None:
            return False
        entry = self.entries()[index.row()]
        text = "" if value is None else str(value).strip()
        column = index.column()
        if column == CODE:
            code = text.upper()
            if code and not re.fullmatch(CODE_PATTERN, code):
                return False
            entry.code = code or None
        elif column == PROJECT:
            entry.description = join_deadline(text, entry.deadline)
        elif column == DEADLINE:
            if not valid_deadline(text):
                return False
            entry.description = join_deadline(entry.project, text)
        elif column == RISK:
            entry.risk = dict(RISK_CHOICES).get(text or "none")
        elif column == ACTIVITY:
            entry.activity = dict(ACTIVITY_CHOICES).get(text or "none")
        if not self.table.lists.set_entry(self.name, index.row(), entry):
            return False
        self.table.dirty = True
        self.dataChanged.emit(index, index)
        self.edited.emit()
        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable


class ProjectListPanel(QtWidgets.QWidget):
    """A list's table and the buttons that change it."""

    #: Emitted after any change, so the editor can refresh and mark the file.
    edited = pyqtSignal()
    #: Emitted with the legend row a copied project landed on.
    copied = pyqtSignal(int)
    #: Emitted with the name of the list a project was moved to.
    moved = pyqtSignal(str)
    #: Emitted with the position of a grasscatcher task to commit to a block.
    commit_requested = pyqtSignal(int)
    #: Emitted when the writer asks the coach to rank the grasscatcher.
    rank_requested = pyqtSignal()
    #: Emitted when the writer asks to sync the grasscatcher with the logs.
    sync_requested = pyqtSignal()
    #: Emitted with the words typed or dictated into the capture box.
    capture_requested = pyqtSignal(str)
    logged = pyqtSignal(str)

    def __init__(self, name: str, title: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.title = title
        self.model = ProjectListModel(name, self)
        self.model.edited.connect(self.edited)

        self.view = QtWidgets.QTableView(self)
        self.view.setModel(self.model)
        self.view.setItemDelegateForColumn(RISK, RiskDelegate(self.view))
        self.view.setItemDelegateForColumn(ACTIVITY, ActivityDelegate(self.view))
        self.view.setItemDelegateForColumn(DEADLINE, DeadlineDelegate(self.view))
        header = self.view.horizontalHeader()
        header.setStretchLastSection(False)
        for column in range(len(HEADERS)):
            header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.Stretch if column == PROJECT
                else QtWidgets.QHeaderView.ResizeToContents)

        self.add_button = QtWidgets.QPushButton("Add project")
        self.add_button.setToolTip(f"Add a project below the selected one in {title}")
        self.add_button.clicked.connect(lambda: self.add_project())
        self.up_button = QtWidgets.QPushButton("Move up")
        self.up_button.clicked.connect(lambda: self.move(up=True))
        self.down_button = QtWidgets.QPushButton("Move down")
        self.down_button.clicked.connect(lambda: self.move(up=False))
        self.delete_button = QtWidgets.QPushButton("Delete project")
        self.delete_button.clicked.connect(lambda: self.delete())
        self.sort_button = QtWidgets.QPushButton("Sort by number")
        self.sort_button.setToolTip(
            "Order the projects by the four-digit number that starts each name")
        self.sort_button.clicked.connect(lambda: self.sort())
        self.copy_button = QtWidgets.QPushButton("Copy to this week's legend")
        self.copy_button.setToolTip(
            "Add the selected project to the legend of this week, keeping its "
            "code when the legend does not use it yet")
        self.copy_button.clicked.connect(lambda: self.copy_to_legend())

        # Only the current list can hand a project to the completed list.
        self.complete_button = None
        if name == CURRENT:
            self.complete_button = QtWidgets.QPushButton("Mark completed")
            self.complete_button.setToolTip(
                "Move the selected project to Completed this semester")
            self.complete_button.clicked.connect(lambda: self.mark_completed())

        # The Carried over list hands a project back to the current list, or
        # Delete project drops it, so every carried project gets a decision.
        self.keep_button = None
        if name == CARRIED:
            self.keep_button = QtWidgets.QPushButton("Move to current list")
            self.keep_button.setToolTip(
                "Keep the selected project: move it to this period's list")
            self.keep_button.clicked.connect(lambda: self.keep())

        # The grasscatcher holds tasks, so it commits one to a block instead
        # of copying a project to the legend.
        self.commit_button = None
        self.rank_button = None
        self.sync_button = None
        self.priority_button = None
        if name == GRASSCATCHER:
            self.sync_button = QtWidgets.QPushButton("Sync to-dos")
            self.sync_button.setToolTip(
                "Compare these tasks with the * Project TODOS section of each "
                "project's log file, such as ~/0142.../log0142.org, and bring "
                "both up to date after showing the changes")
            self.sync_button.clicked.connect(self.sync_requested)
            self.priority_button = QtWidgets.QPushButton("Sort by priority")
            self.priority_button.setToolTip(
                "Order the tasks by their priority cookie: [#A], [#A1], [#A2], "
                "[#B], then numbers such as [#1], then tasks without a cookie")
            self.priority_button.clicked.connect(lambda: self.sort_priority())
            self.add_button.setText("Add task")
            self.add_button.setToolTip(
                "Add a task to the grasscatcher. Put the project's code in the "
                "Code column so Commit knows where it belongs.")
            self.delete_button.setText("Delete task")
            self.commit_button = QtWidgets.QPushButton("Commit to this block")
            self.commit_button.setToolTip(
                "Make the selected task an objective of the block selected in "
                "the grid, and take it off the grasscatcher")
            self.commit_button.clicked.connect(
                lambda: self.commit_requested.emit(self.selected())
                if self.selected() is not None else None)
            self.rank_button = QtWidgets.QPushButton("Rank")
            self.rank_button.setToolTip(
                "Ask the coach to order the tasks by the nearest deadlines and "
                "this week's planned projects, with a reason for each. You "
                "accept or discard the order.")
            self.rank_button.clicked.connect(self.rank_requested)
            for column in (RISK, ACTIVITY):
                self.view.setColumnHidden(column, True)

        # The grasscatcher catches stray thoughts, so it takes them in plain
        # words, typed or dictated, and files them without a dialog.
        self.capture_edit = None
        self.capture_button = None
        if name == GRASSCATCHER:
            self.capture_edit = QtWidgets.QLineEdit()
            self.capture_edit.setPlaceholderText(
                "Capture a task in plain words (Ctrl+Shift+G), such as: email the "
                "reviewer about figure 3 for the R01, priority A")
            self.capture_edit.setToolTip(
                "The project is found from its code, number, or name in your words. "
                "Press Enter to add the task to the end of the list.")
            self.capture_edit.returnPressed.connect(self._capture)
            self.capture_button = QtWidgets.QPushButton("Capture")
            self.capture_button.clicked.connect(self._capture)

        bar = QtWidgets.QHBoxLayout()
        buttons = [self.add_button, self.up_button, self.down_button,
                   self.delete_button]
        if name != GRASSCATCHER:
            buttons += [self.sort_button, self.copy_button]
        else:
            buttons += [self.commit_button, self.priority_button,
                        self.sync_button, self.rank_button]
        if self.complete_button is not None:
            buttons.append(self.complete_button)
        if self.keep_button is not None:
            buttons.append(self.keep_button)
        for button in buttons:
            bar.addWidget(button)
        bar.addStretch(1)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if self.capture_edit is not None:
            capture_row = QtWidgets.QHBoxLayout()
            capture_row.addWidget(self.capture_edit, 1)
            capture_row.addWidget(self.capture_button)
            layout.addLayout(capture_row)
        layout.addLayout(bar)
        layout.addWidget(self.view)
        self.view.selectionModel().currentChanged.connect(
            lambda *_args: self.update_buttons())
        self.model.modelReset.connect(self.update_buttons)
        self.update_buttons()

    def _capture(self) -> None:
        text = self.capture_edit.text().strip()
        if text:
            self.capture_requested.emit(text)

    # -- state -------------------------------------------------------------
    @property
    def table(self):
        return self.model.table

    def set_table(self, table) -> None:
        self.model.set_table(table)

    def selected(self) -> Optional[int]:
        index = self.view.currentIndex()
        if not index.isValid() or not 0 <= index.row() < self.model.rowCount():
            return None
        return index.row()

    def update_buttons(self) -> None:
        row = self.selected()
        count = self.model.rowCount()
        self.add_button.setEnabled(self.table is not None)
        self.sort_button.setEnabled(count > 1)
        if self.rank_button is not None:
            self.rank_button.setEnabled(count > 1)
        for button in (self.delete_button, self.copy_button, self.complete_button,
                       self.keep_button, self.commit_button):
            if button is not None:
                button.setEnabled(row is not None)
        self.up_button.setEnabled(row is not None and row > 0)
        self.down_button.setEnabled(row is not None and row < count - 1)

    def _select(self, row: int, column: int = PROJECT) -> None:
        self.view.setCurrentIndex(self.model.index(row, column))
        self.update_buttons()

    def _changed(self) -> None:
        self.table.dirty = True
        self.edited.emit()

    # -- actions -----------------------------------------------------------
    def add_project(self, entry: Optional[Entry] = None) -> Optional[int]:
        """Add ``entry``, or a blank row to fill in, below the selection."""
        if self.table is None:
            return None
        entry = entry or Entry(None, "new task" if self.name == GRASSCATCHER
                               else "new project")
        row = self.selected()
        position = self.table.lists.insert(
            self.name, None if row is None else row + 1, entry)
        self.model.set_table(self.table)
        self._select(position)
        self.logged.emit(f"Added {entry.project} to {self.title}")
        self._changed()
        return position

    def move(self, up: bool) -> Optional[int]:
        row = self.selected()
        if row is None:
            return None
        new = self.table.lists.move(self.name, row, up)
        if new == row:
            return row
        self.model.set_table(self.table)
        self._select(new)
        self._changed()
        return new

    def sort(self) -> bool:
        """Order the list by project number.  Say whether anything moved."""
        if self.table is None or not self.table.lists.sort(self.name):
            return False
        self.model.set_table(self.table)
        self.logged.emit(f"Sorted {self.title} by project number")
        self._changed()
        return True

    def mark_completed(self) -> Optional[Entry]:
        """Move the selected project to Completed this semester."""
        row = self.selected()
        if row is None or self.complete_button is None:
            return None
        entry = self.table.lists.transfer(self.name, row, COMPLETED)
        self.model.set_table(self.table)
        if self.model.rowCount():
            self._select(min(row, self.model.rowCount() - 1))
        self.logged.emit(f"Marked {entry.project} completed this semester")
        self._changed()
        self.moved.emit(COMPLETED)
        return entry

    def sort_priority(self) -> bool:
        """Order the grasscatcher by priority cookie.  Say whether anything moved."""
        from ..todo_sync import sort_by_priority
        if self.table is None or not sort_by_priority(self.table.lists):
            return False
        self.model.set_table(self.table)
        self.logged.emit("Sorted the grasscatcher by priority")
        self._changed()
        return True

    def keep(self) -> Optional[Entry]:
        """Move the selected carried project to the current list."""
        row = self.selected()
        if row is None or self.keep_button is None:
            return None
        entry = self.table.lists.transfer(self.name, row, CURRENT)
        self.model.set_table(self.table)
        if self.model.rowCount():
            self._select(min(row, self.model.rowCount() - 1))
        self.logged.emit(f"Kept {entry.project} on the current list")
        self._changed()
        self.moved.emit(CURRENT)
        return entry

    def delete(self) -> Optional[Entry]:
        row = self.selected()
        if row is None:
            return None
        entry = self.table.lists.remove(self.name, row)
        self.model.set_table(self.table)
        if self.model.rowCount():
            self._select(min(row, self.model.rowCount() - 1))
        self.logged.emit(f"Deleted {entry.project} from {self.title}")
        self._changed()
        return entry

    def copy_to_legend(self) -> Optional[int]:
        """Copy the selected project into this week's legend.  Return its row."""
        row = self.selected()
        if row is None:
            return None
        entry = self.model.entries()[row]
        try:
            at = self.table.copy_to_legend(entry)
        except ValueError as exc:
            self.logged.emit(str(exc))
            QtWidgets.QToolTip.showText(
                self.copy_button.mapToGlobal(self.copy_button.rect().bottomLeft()),
                str(exc))
            return None
        code = self.table.rows[at].parsed[0]
        self.logged.emit(f"Copied {entry.project} to this week's legend as {code}")
        self.table.dirty = True
        self.copied.emit(at)
        return at
