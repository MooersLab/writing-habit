"""A Qt model over the legend rows, with the risk class as a choice.

The legend is where a project code gets its meaning and its risk class, so it
belongs beside the grid rather than in a dialog. Editing a row rewrites that one
line of the file, in the same way a cell edit does.

The risk column offers the tags a writer types rather than the class names the
database stores, because the table is the thing being edited. ``:risky:`` is the
tag; ``speculative`` is what the database calls the class it names.
"""

from __future__ import annotations

from typing import List, Optional

from .qt import Qt, QtCore, QtGui, QtWidgets, pyqtSignal
from ..name import join_deadline, legend_activity, split_deadline, valid_deadline
from .weekly_table import KEEP, RISK_TO_TAG, WeeklyTable

CODE, PROJECT, DEADLINE, RISK, ACTIVITY = 0, 1, 2, 3, 4
#: The project name is the long, free part of the description, so code that
#: asks for the description column gets it.
DESCRIPTION = PROJECT
HEADERS = ["Code", "Project", "Deadline", "Risk tag", "Default activity"]

#: The choices of the risk column, from the shown label to the stored class.
RISK_CHOICES = [("none", None), ("safe", "safe"), ("risky", "speculative")]

#: The choices of the default-activity column. ``none`` leaves the activity to
#: the cell's letter or the section header.
ACTIVITY_CHOICES = [("none", None), ("generative", "generative"),
                    ("editing", "editing"), ("support", "support")]


class LegendModel(QtCore.QAbstractTableModel):
    """The legend rows of a :class:`WeeklyTable`."""

    edited = pyqtSignal()

    def __init__(self, table: Optional[WeeklyTable] = None, parent=None):
        super().__init__(parent)
        self.table: Optional[WeeklyTable] = None
        self._rows: List[int] = []
        self.set_table(table)

    def set_table(self, table: Optional[WeeklyTable]) -> None:
        self.beginResetModel()
        self.table = table
        self._rows = table.legend_rows() if table is not None else []
        self.endResetModel()

    def document_row(self, row: int) -> int:
        return self._rows[row]

    def entry(self, row: int):
        code, description, risk = self.table.rows[self.document_row(row)].parsed
        return code, description, risk

    # -- Qt ----------------------------------------------------------------
    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() or self.table is None else len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return HEADERS[section]
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        code, description, risk = self.entry(index.row())
        if index.column() == CODE:
            return code
        if index.column() == PROJECT:
            return split_deadline(description)[0]
        if index.column() == DEADLINE:
            return split_deadline(description)[1] or ""
        if index.column() == ACTIVITY:
            return self.activity(index.row()) or "none"
        return RISK_TO_TAG.get(risk or "", "none")

    def activity(self, row: int):
        """Return the default activity of legend row ``row``, or ``None``."""
        cells = self.table.rows[self.document_row(row)].cells
        return legend_activity(cells[0] if cells else "")

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        if role != Qt.EditRole or not index.isValid():
            return False
        code, description, risk = self.entry(index.row())
        activity = KEEP
        text = "" if value is None else str(value).strip()
        if index.column() == CODE:
            code = text
        elif index.column() == PROJECT:
            description = join_deadline(text, split_deadline(description)[1])
        elif index.column() == DEADLINE:
            if not valid_deadline(text):
                return False
            description = join_deadline(split_deadline(description)[0], text)
        elif index.column() == ACTIVITY:
            activity = dict(ACTIVITY_CHOICES).get(text or "none")
        else:
            risk = dict(RISK_CHOICES).get(text or "none")
        if not self.table.set_legend(self.document_row(index.row()),
                                     code, description, risk, activity):
            return False
        self.dataChanged.emit(index, index)
        self.edited.emit()
        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable


class ActivityDelegate(QtWidgets.QStyledItemDelegate):
    """Offer the default activities rather than free text."""

    def createEditor(self, parent, option, index):
        box = QtWidgets.QComboBox(parent)
        box.addItems([label for label, _activity in ACTIVITY_CHOICES])
        return box

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data(Qt.DisplayRole) or "none")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.EditRole)


class RiskDelegate(QtWidgets.QStyledItemDelegate):
    """Offer the three risk tags rather than free text."""

    def createEditor(self, parent, option, index):
        box = QtWidgets.QComboBox(parent)
        box.addItems([label for label, _class in RISK_CHOICES])
        return box

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data(Qt.DisplayRole) or "none")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.EditRole)


class DeadlineDelegate(QtWidgets.QStyledItemDelegate):
    """Accept a deadline only as ``YYYY-MM-DD``, or nothing to clear it."""

    def createEditor(self, parent, option, index):
        edit = QtWidgets.QLineEdit(parent)
        edit.setPlaceholderText("YYYY-MM-DD")
        edit.setValidator(QtGui.QRegularExpressionValidator(
            QtCore.QRegularExpression(r"^$|^\d{0,4}(-\d{0,2}(-\d{0,2})?)?$"), edit))
        return edit

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.DisplayRole) or "")

    def setModelData(self, editor, model, index):
        if not model.setData(index, editor.text(), Qt.EditRole):
            QtWidgets.QToolTip.showText(
                editor.mapToGlobal(editor.rect().bottomLeft()),
                "A deadline is a date written YYYY-MM-DD, such as 2026-11-15.")
