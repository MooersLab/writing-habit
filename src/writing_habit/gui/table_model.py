"""A read-only Qt model over the weekly block table.

The grid shows the table as the writer laid it out. Rows are the section
headers and the time blocks in file order, so a section keeps its blocks, and
columns are the days named by the header row, so a six-day table and a seven-day
table both work without a setting.

A block cell is editable and a section row is not, because a section row names
the activity of the blocks under it and belongs to the file rather than to the
week. Every edit goes through the document, which rewrites one line and leaves
the rest of the file untouched.
"""

from __future__ import annotations

from typing import List, Optional

from .qt import Qt, QtCore, QtGui, QtWidgets, pyqtSignal
from .weekly_table import (BLOCK, SECTION, WeeklyTable,
                           split_cell)

TIME_COLUMN = 0

#: The tint of a section row, and the tint of a block that takes part in a clash.
SECTION_COLOR = "#eeeeee"
CONFLICT_COLOR = "#ffd7d7"

#: The tint of a block row that does not overlap the selected time.
CLEAR_COLOR = "#fff59d"

#: The tint of a block in a run of more than two hours with no 15-minute break.
#: A clash takes precedence, because it is the more urgent thing to see.
BREAK_COLOR = "#ffe0b2"

#: The shade of every other group of rows that start at the same time. Rows
#: sharing a start time are one group, so the eye reads 05:00-05:30,
#: 05:00-06:00, and 05:00-07:00 as the choices for one slot. The other groups
#: keep the plain background.
BAND_COLOR = "#f0f0f0"

#: The pale tint of a filled cell by its activity, so the kind of work in each
#: block shows at a glance whichever way the table names it. A clash and the
#: clear-of-selection tint both take precedence.
ACTIVITY_COLOR = {"generative": "#dcebfa", "editing": "#e2f2dc",
                  "support": "#efe7f6"}

#: How the tooltip names where a block's activity came from.
SOURCE_LABEL = {"cell": "from the cell", "legend": "the project's default",
                "section": "from the section", "none": "no section, so generative"}


class WeeklyTableModel(QtCore.QAbstractTableModel):
    """The section and block rows of a :class:`WeeklyTable`, as a grid."""

    #: Emitted after an edit reaches the document, so the panels can refresh.
    edited = pyqtSignal()

    def __init__(self, table: Optional[WeeklyTable] = None, parent=None):
        super().__init__(parent)
        self.table: Optional[WeeklyTable] = None
        self._rows: List[int] = []
        self._conflicts: set = set()
        self._breaks: set = set()
        #: The document row of the selected Time cell, and the rows clear of it.
        self._anchor: Optional[int] = None
        self._clear: set = set()
        #: The filled blocks by (document row, cell index), rebuilt on refresh.
        self._blocks: dict = {}
        #: The document rows of the shaded start-time groups.
        self._banded: set = set()
        self.set_table(table)

    # -- content -----------------------------------------------------------
    def set_table(self, table: Optional[WeeklyTable]) -> None:
        self.beginResetModel()
        self.table = table
        self._rows = []
        self._conflicts = set()
        self._anchor = None
        self._clear = set()
        if table is not None:
            self._rows = [i for i, row in enumerate(table.rows)
                          if row.kind in (SECTION, BLOCK)]
            self._conflicts = table.conflicting_cells()
            self._breaks = table.break_cells()
        else:
            self._breaks = set()
        self._blocks = self._index_blocks()
        self._banded = self._start_bands()
        self.endResetModel()

    def _start_bands(self) -> set:
        """Return the document rows of every other run of equal start times.

        The grid is walked in order, and the shade flips each time a block row
        starts at a different time from the block row before it. A section row
        keeps its own tint and does not break a run.
        """
        banded, shaded, previous = set(), False, None
        if self.table is None:
            return banded
        for document_row in self._rows:
            row = self.table.rows[document_row]
            if row.kind != BLOCK:
                continue
            start = row.parsed[0]
            if previous is not None and start != previous:
                shaded = not shaded
            previous = start
            if shaded:
                banded.add(document_row)
        return banded

    def band_brush(self, document_row: int):
        """Return the shade of a block row's start-time group, or ``None``."""
        if document_row in self._banded:
            return QtGui.QBrush(QtGui.QColor(BAND_COLOR))
        return None

    def _index_blocks(self) -> dict:
        if self.table is None:
            return {}
        return {(b.row, b.column): b for b in self.table.blocks()}

    def refresh(self) -> None:
        """Recompute the derived state after an edit."""
        if self.table is not None:
            self._conflicts = self.table.conflicting_cells()
            self._breaks = self.table.break_cells()
            self._clear = self._clear_rows(self._anchor)
            self._blocks = self._index_blocks()
            self._banded = self._start_bands()
        top = self.index(0, 0)
        bottom = self.index(max(0, self.rowCount() - 1),
                            max(0, self.columnCount() - 1))
        self.dataChanged.emit(top, bottom)

    # -- the time selection ------------------------------------------------
    def _clear_rows(self, anchor: Optional[int]) -> set:
        if self.table is None or anchor is None or anchor >= len(self.table.rows):
            return set()
        if self.table.rows[anchor].kind != BLOCK:
            return set()
        return set(self.table.rows_clear_of(anchor))

    def set_time_anchor(self, row: Optional[int]) -> None:
        """Tint the rows of the blocks that do not overlap grid row ``row``.

        ``None``, or a row that is not a time block, clears the tint. The tint
        answers where else in the day a block could go without a clash, which
        the grid cannot show on its own because blocks in different sections
        share the same clock. A day cell tinted for a clash keeps that tint,
        because the clash is the more urgent thing to see.
        """
        anchor = None
        if row is not None and 0 <= row < len(self._rows):
            document_row = self.document_row(row)
            if self.table.rows[document_row].kind == BLOCK:
                anchor = document_row
        clear = self._clear_rows(anchor)
        if anchor == self._anchor and clear == self._clear:
            return
        self._anchor, self._clear = anchor, clear
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(self.rowCount() - 1,
                                             self.columnCount() - 1),
                                  [Qt.BackgroundRole])

    def clear_of_selection(self) -> List[int]:
        """Return the grid rows tinted as clear of the selected time."""
        return [i for i, document_row in enumerate(self._rows)
                if document_row in self._clear]

    def document_row(self, row: int) -> int:
        """Return the index into ``WeeklyTable.rows`` for grid row ``row``."""
        return self._rows[row]

    def is_section(self, row: int) -> bool:
        return self.table.rows[self.document_row(row)].kind == SECTION

    def document_cell(self, row: int, column: int) -> int:
        """Return the index into the row's cells for grid column ``column``."""
        return self.table.columns[column - 1][0]

    # -- Qt ----------------------------------------------------------------
    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() or self.table is None else len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() or self.table is None else 1 + len(self.table.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or self.table is None:
            return None
        if orientation == Qt.Horizontal:
            if section == TIME_COLUMN:
                return "Time"
            return self.table.day_labels[section - 1]
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self.table is None:
            return None
        row, column = index.row(), index.column()
        document_row = self.document_row(row)
        entry = self.table.rows[document_row]

        if entry.kind == SECTION:
            if role == Qt.DisplayRole:
                return str(entry.parsed) if column == TIME_COLUMN else ""
            if role == Qt.FontRole:
                font = QtGui.QFont()
                font.setBold(True)
                return font
            if role == Qt.BackgroundRole:
                return QtGui.QBrush(QtGui.QColor(SECTION_COLOR))
            return None

        if role == Qt.DisplayRole:
            if column == TIME_COLUMN:
                start, end = entry.parsed
                return f"{start}-{end}"
            return self.table.cell(document_row, self.document_cell(row, column))

        if column == TIME_COLUMN:
            if role == Qt.BackgroundRole and document_row in self._clear:
                return QtGui.QBrush(QtGui.QColor(CLEAR_COLOR))
            if role == Qt.BackgroundRole:
                return self.band_brush(document_row)
            if role == Qt.ToolTipRole and document_row in self._clear:
                return "Does not overlap the selected time"
            return None

        cell_index = self.document_cell(row, column)
        if role == Qt.BackgroundRole and (document_row, cell_index) in self._conflicts:
            return QtGui.QBrush(QtGui.QColor(CONFLICT_COLOR))
        if role == Qt.BackgroundRole and (document_row, cell_index) in self._breaks:
            return QtGui.QBrush(QtGui.QColor(BREAK_COLOR))
        if role == Qt.BackgroundRole and document_row in self._clear:
            return QtGui.QBrush(QtGui.QColor(CLEAR_COLOR))
        if role == Qt.BackgroundRole:
            block = self.block_at(document_row, cell_index)
            if block is not None:
                return QtGui.QBrush(QtGui.QColor(ACTIVITY_COLOR[block.category]))
            return self.band_brush(document_row)
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignCenter)
        if role == Qt.ToolTipRole:
            return self.tooltip(self.table.cell(document_row, cell_index),
                                self.block_at(document_row, cell_index))
        return None

    def block_at(self, document_row: int, cell_index: int):
        """Return the filled block at a document cell, or ``None``."""
        return self._blocks.get((document_row, cell_index))

    def tooltip(self, code: str, block=None) -> Optional[str]:
        """Return the balloon text for a cell holding ``code``.

        The balloon names the project in full, gives its due date when the key
        carries one, and gives its risk class, all read from the key below the
        grid. A code missing from the key says so, because that is the cell the
        writer most needs to notice.
        """
        code = split_cell(code or "")[1]
        if not code:
            return None
        info = self.table.project_info(code)
        activity = []
        if block is not None:
            activity = [f"Activity: {block.category} "
                        f"({SOURCE_LABEL[block.activity_source]})"]
        if info is None:
            return "\n".join([f"{code}: not in the key"] + activity)
        lines = [f"{code}: {info['name'] or '(no name)'}"]
        if info["due"]:
            lines.append(f"Due: {info['due']}")
        lines.append(f"Risk: {info['risk'] or 'not tagged'}")
        return "\n".join(lines + activity)

    def flags(self, index):
        """A block cell takes an edit.  A section row and the time column do not."""
        if not index.isValid():
            return Qt.NoItemFlags
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == TIME_COLUMN or self.is_section(index.row()):
            return base
        return base | Qt.ItemIsEditable

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        """Write one project code into the document, then revalidate."""
        if role != Qt.EditRole or not index.isValid() or self.table is None:
            return False
        if not (self.flags(index) & Qt.ItemIsEditable):
            return False
        row, column = index.row(), index.column()
        changed = self.table.set_cell(self.document_row(row),
                                      self.document_cell(row, column),
                                      "" if value is None else str(value))
        if changed:
            self.dataChanged.emit(index, index)
            self.refresh()                      # a clash can appear or vanish
            self.edited.emit()
        return changed

    def codes(self) -> List[str]:
        """Return the blank entry and every legend code, for the cell editor."""
        return [""] + list(self.table.legend()) if self.table is not None else [""]


#: The activity buttons of the cell editor, as (letter, label, tooltip).
ACTIVITY_BUTTONS = [("g", "g", "Generative writing"),
                    ("e", "e", "Editing (rewriting)"),
                    ("s", "s", "Support writing")]


class CodeEditor(QtWidgets.QWidget):
    """Three activity buttons beside an editable box of the legend codes.

    No button pressed means the block takes its activity from the project's
    legend default or from the section header. Pressing a button writes its
    letter before the code, as in ``eA``, and pressing it again clears it.
    Typing ``eA`` into the box works too, and a letter typed there wins.
    """

    def __init__(self, codes, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        self.buttons = {}
        for letter, label, tip in ACTIVITY_BUTTONS:
            button = QtWidgets.QToolButton(self)
            button.setText(label)
            button.setToolTip(tip + ". Press again to take the activity from "
                              "the project or the section.")
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.toggled.connect(lambda on, letter=letter: self._toggled(letter, on))
            layout.addWidget(button)
            self.buttons[letter] = button
        self.box = QtWidgets.QComboBox(self)
        self.box.setEditable(True)
        self.box.addItems(codes)
        layout.addWidget(self.box, 1)
        self.setFocusProxy(self.box)

    def _toggled(self, letter: str, on: bool) -> None:
        if on:
            for other, button in self.buttons.items():
                if other != letter and button.isChecked():
                    button.setChecked(False)

    def activity(self) -> Optional[str]:
        for letter, button in self.buttons.items():
            if button.isChecked():
                return letter
        return None

    def set_value(self, text: str) -> None:
        letter, code = split_cell(text or "")
        for other, button in self.buttons.items():
            button.setChecked(other == letter)
        self.box.setCurrentText(code)

    def value(self) -> str:
        typed_letter, code = split_cell(self.box.currentText())
        if not code:
            return ""
        return (typed_letter or self.activity() or "") + code


class CodeDelegate(QtWidgets.QStyledItemDelegate):
    """Edit a cell with activity buttons and a box of the legend codes.

    A cell can then never hold a code the legend does not define, which is the
    mistake the legend check would otherwise report after the fact. The box is
    editable, so a writer can still type a code and add its legend row after.
    """

    def createEditor(self, parent, option, index):
        model = index.model()
        return CodeEditor(model.codes() if hasattr(model, "codes") else [""], parent)

    def setEditorData(self, editor, index):
        editor.set_value(index.data(Qt.DisplayRole) or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.value(), Qt.EditRole)
