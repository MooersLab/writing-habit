"""The editor for the calendar of planning periods.

The calendar is an org table in ``periods.org``, so it can be edited in Emacs
as well. This dialog shows the same five columns, offers starter rows for a
year in several styles, checks the dates before saving, and chooses which kind
of period names the project lists.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import List, Optional

from ..periods import (DEFAULT_KIND, HEADERS, TEMPLATES, Calendar, Period,
                       fill_year)
from .qt import QtCore, QtWidgets, Qt

KIND, NAME, START, END, HORIZON = range(5)


class DateDelegate(QtWidgets.QStyledItemDelegate):
    """Edit a YYYY-MM-DD cell with a date picker."""

    def createEditor(self, parent, option, index):
        editor = QtWidgets.QDateEdit(parent)
        editor.setCalendarPopup(True)
        editor.setDisplayFormat("yyyy-MM-dd")
        return editor

    def setEditorData(self, editor, index):
        date = QtCore.QDate.fromString(index.data() or "", "yyyy-MM-dd")
        editor.setDate(date if date.isValid() else QtCore.QDate.currentDate())

    def setModelData(self, editor, model, index):
        model.setData(index, editor.date().toString("yyyy-MM-dd"))


class PeriodsDialog(QtWidgets.QDialog):
    """Edit the periods of one calendar file and the kind used for list titles."""

    def __init__(self, calendar: Calendar, path: Path, kind: str = DEFAULT_KIND,
                 parent=None):
        super().__init__(parent)
        self.calendar = calendar
        self.path = Path(path)
        self.setWindowTitle(f"Planning periods: {self.path}")
        self.resize(720, 460)
        layout = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        header = self.table.horizontalHeader()
        for column in (KIND, START, END, HORIZON):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(NAME, QtWidgets.QHeaderView.Stretch)
        for column in (START, END):
            self.table.setItemDelegateForColumn(column, DateDelegate(self.table))
        self.table.itemChanged.connect(lambda _item: self.update_problems())
        layout.addWidget(self.table)

        bar = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton("Add")
        self.add_button.clicked.connect(lambda: self.add_row())
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.delete_button.clicked.connect(lambda: self.delete_row())
        self.up_button = QtWidgets.QPushButton("Move up")
        self.up_button.clicked.connect(lambda: self.move_row(True))
        self.down_button = QtWidgets.QPushButton("Move down")
        self.down_button.clicked.connect(lambda: self.move_row(False))
        self.sort_button = QtWidgets.QPushButton("Sort by start")
        self.sort_button.clicked.connect(lambda: self.sort_rows())
        self.fill_button = QtWidgets.QToolButton()
        self.fill_button.setText("Fill a year")
        self.fill_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(self.fill_button)
        for key, label in TEMPLATES:
            action = menu.addAction(label)
            action.triggered.connect(lambda _c=False, key=key: self.ask_fill(key))
        self.fill_button.setMenu(menu)
        for button in (self.add_button, self.delete_button, self.up_button,
                       self.down_button, self.sort_button, self.fill_button):
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)

        kind_row = QtWidgets.QHBoxLayout()
        kind_row.addWidget(QtWidgets.QLabel("Kind of period that names the project lists"))
        self.kind_box = QtWidgets.QComboBox()
        self.kind_box.setEditable(True)
        layout.addLayout(kind_row)
        kind_row.addWidget(self.kind_box, 1)

        self.problems = QtWidgets.QLabel()
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color: #a33;")
        layout.addWidget(self.problems)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.set_periods(calendar.periods)
        self._fill_kinds(kind)

    # -- rows --------------------------------------------------------------
    def _fill_kinds(self, chosen: str) -> None:
        kinds = [p.kind for p in self.periods(strict=False)]
        self.kind_box.clear()
        for kind in dict.fromkeys(kinds + [chosen or DEFAULT_KIND]):
            self.kind_box.addItem(kind)
        self.kind_box.setCurrentText(chosen or DEFAULT_KIND)

    def _set_row(self, row: int, period: Period) -> None:
        self.table.blockSignals(True)
        for column, text in enumerate(period.cells()[:4]):
            self.table.setItem(row, column, QtWidgets.QTableWidgetItem(text))
        horizon = QtWidgets.QTableWidgetItem()
        horizon.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
        horizon.setCheckState(Qt.Checked if period.horizon else Qt.Unchecked)
        self.table.setItem(row, HORIZON, horizon)
        self.table.blockSignals(False)

    def set_periods(self, periods: List[Period]) -> None:
        self.table.setRowCount(0)
        for period in periods:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._set_row(row, period)
        self.update_problems()

    def periods(self, strict: bool = True) -> List[Period]:
        """Return the rows as periods.  A row that cannot be read is skipped."""
        out = []
        for row in range(self.table.rowCount()):
            text = [(self.table.item(row, c).text() if self.table.item(row, c) else "")
                    for c in range(4)]
            try:
                start = _dt.date.fromisoformat(text[START].strip())
                end = _dt.date.fromisoformat(text[END].strip())
            except ValueError:
                continue
            if not text[KIND].strip() or not text[NAME].strip():
                continue
            item = self.table.item(row, HORIZON)
            horizon = item is None or item.checkState() == Qt.Checked
            out.append(Period(text[KIND].strip().lower(), text[NAME].strip(),
                              start, end, horizon))
        return out

    def unreadable_rows(self) -> List[int]:
        good = len(self.periods())
        return [] if good == self.table.rowCount() else [
            row + 1 for row in range(self.table.rowCount())
            if not self._row_ok(row)]

    def _row_ok(self, row: int) -> bool:
        text = [(self.table.item(row, c).text() if self.table.item(row, c) else "")
                for c in range(4)]
        try:
            _dt.date.fromisoformat(text[START].strip())
            _dt.date.fromisoformat(text[END].strip())
        except ValueError:
            return False
        return bool(text[KIND].strip() and text[NAME].strip())

    def add_row(self, period: Optional[Period] = None) -> int:
        current = self.table.currentRow()
        if period is None:
            today = _dt.date.today()
            kind = self.kind_box.currentText() or DEFAULT_KIND
            period = Period(kind, "New period", today, today)
        row = current + 1 if current >= 0 else self.table.rowCount()
        self.table.insertRow(row)
        self._set_row(row, period)
        self.table.setCurrentCell(row, NAME)
        self.update_problems()
        return row

    def delete_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.update_problems()

    def move_row(self, up: bool) -> None:
        row = self.table.currentRow()
        other = row - 1 if up else row + 1
        if row < 0 or not 0 <= other < self.table.rowCount():
            return
        periods = {r: self._row_period(r) for r in (row, other)}
        if None in periods.values():
            return
        self._set_row(row, periods[other])
        self._set_row(other, periods[row])
        self.table.setCurrentCell(other, self.table.currentColumn())

    def _row_period(self, row: int) -> Optional[Period]:
        if not self._row_ok(row):
            return None
        text = [self.table.item(row, c).text() for c in range(4)]
        item = self.table.item(row, HORIZON)
        return Period(text[KIND].strip().lower(), text[NAME].strip(),
                      _dt.date.fromisoformat(text[START].strip()),
                      _dt.date.fromisoformat(text[END].strip()),
                      item is None or item.checkState() == Qt.Checked)

    def sort_rows(self) -> None:
        self.set_periods(sorted(self.periods(), key=lambda p: (p.kind, p.start)))

    # -- Fill a year ----------------------------------------------------------
    def ask_fill(self, style: str) -> None:
        year, ok = QtWidgets.QInputDialog.getInt(
            self, "Fill a year", "Year", _dt.date.today().year + 1, 1900, 2200)
        if not ok:
            return
        first = 7
        if style == "fiscal-year":
            first, ok = QtWidgets.QInputDialog.getInt(
                self, "Fill a year", "First month of the fiscal year (1 to 12)",
                7, 1, 12)
            if not ok:
                return
        self.fill(style, year, first)

    def fill(self, style: str, year: int, first_month: int = 7) -> int:
        """Add the starter rows of one year.  Return how many were added."""
        have = {(p.kind, p.name) for p in self.periods()}
        added = 0
        for period in fill_year(style, year, first_month):
            if (period.kind, period.name) in have:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._set_row(row, period)
            added += 1
        self._fill_kinds(self.kind_box.currentText())
        self.update_problems()
        return added

    # -- checking and saving ----------------------------------------------------
    def problem_list(self) -> List[str]:
        problems = [f"Row {row} needs a kind, a name, and two YYYY-MM-DD dates"
                    for row in self.unreadable_rows()]
        problems += Calendar(self.periods()).check()
        return problems

    def update_problems(self) -> None:
        problems = self.problem_list()
        self.problems.setText("\n".join(problems))

    def kind(self) -> str:
        return (self.kind_box.currentText() or DEFAULT_KIND).strip().lower()

    #: Asks whether to save despite problems.  A test replaces it.
    def confirm_problems(self, problems: List[str]) -> bool:
        answer = QtWidgets.QMessageBox.question(
            self, "Save the periods",
            "The calendar has problems:\n\n" + "\n".join(problems)
            + "\n\nSave anyway?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        return answer == QtWidgets.QMessageBox.Yes

    def save(self) -> Optional[str]:
        problems = self.problem_list()
        if problems and not self.confirm_problems(problems):
            return None
        self.calendar.periods = self.periods()
        self.calendar.read_problems = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        written = self.calendar.save(str(self.path))
        self.accept()
        return written
