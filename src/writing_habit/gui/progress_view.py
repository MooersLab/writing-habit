"""The Progress tab: how far each unfinished project has come.

The tab reads the ``progress`` table at the end of the open week file. Each
project is drawn as one horizontal bar. The bar's full length is the time the
project is expected to need, the green part is the time spent so far, and the
white part is the time left. A project that has run past its estimate shows
the overrun in a darker green beyond a tick at the estimate.

**Update hours spent** reads the sessions of each project from the
``zTimeSpent`` table of ``mytime.db`` and writes the totals into the table.
The estimate and the weight are typed into the table below the chart, and
both are saved with the week file.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import List, Optional

from .. import progress as progressmod
from . import settings
from .qt import Qt, QtCore, QtGui, QtWidgets, pyqtSignal

SPENT = QtGui.QColor("#4a9e5c")
OVER = QtGui.QColor("#2c6b3a")
OUTLINE = QtGui.QColor("#5f5e5a")
GRID = QtGui.QColor("#e3e2dd")
TEXT = QtGui.QColor("#2b2a27")
MUTED = QtGui.QColor("#898781")
NO_ESTIMATE = QtGui.QColor("#f1efe8")

COLUMNS = progressmod.HEADER
EDITABLE = {1, 2, 4}            # name, estimate, weight; hours spent is computed


def nice_step(span: float, ticks: int = 6) -> float:
    """Return a round tick spacing that puts about ``ticks`` ticks across ``span``."""
    if span <= 0:
        return 1.0
    raw = span / ticks
    power = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 5, 10):
        if raw <= factor * power:
            return factor * power
    return 10 * power


class ProgressChart(QtWidgets.QWidget):
    """Horizontal bars of hours spent against hours expected, one per project."""

    ROW = 26
    BAR = 16
    TOP = 34
    BOTTOM = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: List[progressmod.Row] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(120)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def set_rows(self, rows) -> None:
        self.rows = sorted(rows, key=lambda r: r.number)
        self.setFixedHeight(self.TOP + self.BOTTOM + max(len(self.rows), 1) * self.ROW)
        self.update()

    # -- geometry -------------------------------------------------------------
    def scale_max(self) -> float:
        longest = max([max(r.estimate or 0, r.spent) for r in self.rows] or [0])
        step = nice_step(longest or 10)
        return step * math.ceil((longest or 10) / step)

    #: The widest a project's label may be before its name is shortened.
    LABEL_MAX = 260

    def label_width(self) -> int:
        metrics = self.fontMetrics()
        widest = max([metrics.horizontalAdvance(r.label) for r in self.rows]
                     or [metrics.horizontalAdvance("0000")])
        return min(widest, self.LABEL_MAX) + 14

    def label(self, row) -> str:
        """The project's number and name, shortened at the end to fit."""
        return self.fontMetrics().elidedText(row.label, Qt.ElideRight,
                                             self.label_width() - 14)

    def plot_rect(self) -> QtCore.QRect:
        left = self.label_width()
        return QtCore.QRect(left, self.TOP, max(self.width() - left - 24, 40),
                            max(len(self.rows), 1) * self.ROW)

    def x_of(self, hours: float) -> float:
        plot = self.plot_rect()
        return plot.left() + plot.width() * hours / self.scale_max()

    def bar_rect(self, index: int, hours: float) -> QtCore.QRectF:
        plot = self.plot_rect()
        top = plot.top() + index * self.ROW + (self.ROW - self.BAR) / 2
        return QtCore.QRectF(plot.left(), top, self.x_of(hours) - plot.left(), self.BAR)

    def row_at(self, pos) -> int:
        plot = self.plot_rect()
        if pos.y() < plot.top():
            return -1
        index = int((pos.y() - plot.top()) // self.ROW)
        return index if 0 <= index < len(self.rows) else -1

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), Qt.white)
        plot = self.plot_rect()
        metrics = self.fontMetrics()
        if not self.rows:
            painter.setPen(MUTED)
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "No progress table in this week file yet.")
            return
        painter.setPen(TEXT)
        painter.drawText(QtCore.QRect(plot.left(), 6, plot.width(), 20),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         "Hours spent (green) of hours expected (whole bar)")
        top_value = self.scale_max()
        step = nice_step(top_value)
        value = 0.0
        while value <= top_value + 1e-9:
            x = self.x_of(value)
            painter.setPen(QtGui.QPen(GRID, 1))
            painter.drawLine(QtCore.QPointF(x, plot.top()), QtCore.QPointF(x, plot.bottom()))
            painter.setPen(MUTED)
            label = f"{value:g}"
            painter.drawText(QtCore.QRectF(x - 30, plot.bottom() + 4, 60, 18),
                             Qt.AlignHCenter | Qt.AlignTop, label)
            value += step
        painter.drawText(QtCore.QRect(plot.left(), plot.bottom() + 20, plot.width(), 16),
                         Qt.AlignHCenter | Qt.AlignTop, "hours")
        for index, row in enumerate(self.rows):
            centre = plot.top() + index * self.ROW + self.ROW / 2
            painter.setPen(TEXT)
            painter.drawText(QtCore.QRectF(0, centre - 10, plot.left() - 8, 20),
                             Qt.AlignRight | Qt.AlignVCenter, self.label(row))
            self._paint_bar(painter, index, row)
        painter.end()

    def _paint_bar(self, painter, index: int, row) -> None:
        if row.estimate is None or row.estimate <= 0:
            # No estimate: show the hours spent against a dashed, open end.
            spent = self.bar_rect(index, row.spent)
            painter.setPen(Qt.NoPen)
            painter.setBrush(SPENT)
            painter.drawRect(spent)
            painter.setPen(MUTED)
            painter.drawText(QtCore.QRectF(spent.right() + 6, spent.top() - 2, 200,
                                           spent.height() + 4),
                             Qt.AlignLeft | Qt.AlignVCenter, "no estimate")
            return
        whole = self.bar_rect(index, row.estimate)
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.white)
        painter.drawRect(whole)
        done = self.bar_rect(index, min(row.spent, row.estimate))
        painter.setBrush(SPENT)
        painter.drawRect(done)
        if row.spent > row.estimate:
            over = self.bar_rect(index, row.spent)
            over.setLeft(whole.right())
            painter.setBrush(OVER)
            painter.drawRect(over)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QtGui.QPen(OUTLINE, 1.2))
        painter.drawRect(whole)
        if row.spent > row.estimate:
            painter.drawLine(QtCore.QPointF(whole.right(), whole.top() - 3),
                             QtCore.QPointF(whole.right(), whole.bottom() + 3))

    # -- tooltips -------------------------------------------------------
    def tip(self, index: int) -> str:
        row = self.rows[index]
        lines = [f"{row.number} {row.name}".strip(),
                 f"Hours spent: {row.spent:g}"]
        if row.estimate is not None:
            lines.insert(1, f"Hours expected: {row.estimate:g}")
            lines.append(f"Hours left: {row.remaining:g}")
            if row.spent > row.estimate:
                lines.append(f"Over the estimate by {row.spent - row.estimate:g} hours")
        if row.weight is not None:
            lines.append(f"Weight: {row.weight:g}")
        return "\n".join(lines)

    def event(self, event):
        if event.type() == QtCore.QEvent.ToolTip:
            index = self.row_at(event.pos())
            if index >= 0:
                QtWidgets.QToolTip.showText(event.globalPos(), self.tip(index), self)
            else:
                QtWidgets.QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)


class ProgressView(QtWidgets.QWidget):
    """The Progress tab: the bar chart above the editable progress table."""

    logged = pyqtSignal(str)
    edited = pyqtSignal()

    def __init__(self, editor=None, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.rows: List[progressmod.Row] = []
        self._filling = False

        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "Each bar is one unfinished project from the <b>progress</b> table at "
            "the end of the week file. The whole bar is the time the project is "
            "expected to need, green is the time spent, and white is the time "
            "left. Type the expected hours and an importance weight in the "
            "table; the Schedule tab's Coach menu uses the weights to suggest "
            "next week's plan.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        bar = QtWidgets.QHBoxLayout()
        self.update_button = QtWidgets.QPushButton("Update hours spent")
        self.update_button.setToolTip(
            "Add up each project's sessions in the zTimeSpent table of mytime.db "
            "and write the totals into the Hours spent column. The tracker is "
            "only read.")
        self.update_button.clicked.connect(lambda: self.update_hours())
        bar.addWidget(self.update_button)
        self.seed_button = QtWidgets.QPushButton("Add projects from the current list")
        self.seed_button.setToolTip(
            "Add a row for each numbered project on this semester's list that "
            "the progress table does not have yet. The table is made at the end "
            "of the file when there is none.")
        self.seed_button.clicked.connect(lambda: self.seed())
        bar.addWidget(self.seed_button)
        self.remove_button = QtWidgets.QPushButton("Remove row")
        self.remove_button.setToolTip("Take the selected project off the progress table, "
                                      "for example when it is finished")
        self.remove_button.clicked.connect(lambda: self.remove_selected())
        bar.addWidget(self.remove_button)
        bar.addStretch(1)
        self.status = QtWidgets.QLabel("")
        self.status.setStyleSheet("color: #898781;")
        bar.addWidget(self.status)
        layout.addLayout(bar)

        splitter = QtWidgets.QSplitter(Qt.Vertical)
        self.chart = ProgressChart()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.chart)
        scroll.setStyleSheet("QScrollArea { background: white; }")
        splitter.addWidget(scroll)
        self.grid = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.grid.setHorizontalHeaderLabels(COLUMNS)
        self.grid.verticalHeader().setVisible(False)
        self.grid.horizontalHeader().setStretchLastSection(False)
        self.grid.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.grid.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.grid.itemChanged.connect(self.on_item_changed)
        splitter.addWidget(self.grid)
        splitter.setSizes([400, 220])
        layout.addWidget(splitter, 1)

        if editor is not None:
            editor.opened.connect(lambda _p: self.reload())
            editor.edited.connect(self.reload)
            self.logged.connect(editor.logged)
        self.reload()

    # -- the table of the open week file -----------------------------------
    def table(self):
        return getattr(self.editor, "table", None) if self.editor is not None else None

    def lines(self) -> Optional[list]:
        table = self.table()
        return table.lists.lines if table is not None else None

    def reload(self) -> None:
        """Read the progress table from the open week file again."""
        if self._filling:
            return
        lines = self.lines()
        rows = progressmod.read(lines) if lines is not None else None
        self.rows = rows or []
        if lines is None:
            self.status.setText("Open a week file on the Schedule tab.")
        elif rows is None:
            self.status.setText("This week file has no progress table yet.")
        else:
            self.status.setText(f"{len(self.rows)} project"
                                f"{'' if len(self.rows) == 1 else 's'}")
        self._fill_grid()
        self.chart.set_rows(self.rows)
        has_table = lines is not None
        self.seed_button.setEnabled(has_table)
        self.update_button.setEnabled(has_table and rows is not None)
        self.remove_button.setEnabled(bool(self.rows))

    def _fill_grid(self) -> None:
        self._filling = True
        try:
            self.grid.setRowCount(len(self.rows))
            for r, row in enumerate(self.rows):
                values = [row.number, row.name, progressmod._fmt(row.estimate),
                          progressmod._fmt(row.spent), progressmod._fmt(row.weight)]
                for c, value in enumerate(values):
                    item = QtWidgets.QTableWidgetItem(value)
                    if c not in EDITABLE:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    if c >= 2:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.grid.setItem(r, c, item)
            self.grid.resizeColumnToContents(0)
        finally:
            self._filling = False

    def store(self) -> bool:
        """Write ``self.rows`` into the week file's lines.  Return whether they changed."""
        lines = self.lines()
        if lines is None:
            return False
        if not progressmod.write(lines, self.rows):
            return False
        table = self.table()
        table.dirty = True
        self._filling = True
        try:
            if self.editor is not None and hasattr(self.editor, "on_edit"):
                self.editor.on_edit()
        finally:
            self._filling = False
        self.edited.emit()
        return True

    def on_item_changed(self, item) -> None:
        if self._filling or item.row() >= len(self.rows):
            return
        row = self.rows[item.row()]
        text = item.text().strip()
        if item.column() == 1:
            row.name = text
        elif item.column() in (2, 4):
            value = progressmod._number(text)
            if text and value is None:
                self.logged.emit(f"{text!r} is not a number of hours or a weight")
                self._fill_grid()
                return
            if item.column() == 2:
                row.estimate = value
            else:
                row.weight = value
        self.store()
        self.chart.set_rows(self.rows)

    # -- buttons ---------------------------------------------------------
    def seed(self) -> int:
        """Add the numbered projects of the current list.  Return how many were added."""
        table = self.table()
        if table is None:
            return 0
        from ..project_lists import CURRENT
        before = len(self.rows)
        self.rows = progressmod.seed(table.lists.entries(CURRENT), self.rows)
        added = len(self.rows) - before
        if added or progressmod.read(self.lines()) is None:
            self.store()
        self.reload()
        self.logged.emit(f"Added {added} project{'' if added == 1 else 's'} "
                         "to the progress table")
        return added

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.grid.selectedIndexes()}, reverse=True)
        if not rows:
            return
        for r in rows:
            if r < len(self.rows):
                del self.rows[r]
        self.store()
        self.reload()

    def mytime_path(self) -> Path:
        stored = settings.get("mytime_db")
        if stored:
            return Path(stored).expanduser()
        from ..pom_count import database_path
        return database_path()

    def update_hours(self, path=None) -> Optional[int]:
        """Fill Hours spent from mytime.db.  Return how many rows changed."""
        if not self.rows:
            self.logged.emit("The progress table has no projects to update")
            return None
        path = Path(path).expanduser() if path else self.mytime_path()
        try:
            hours = progressmod.hours_spent(path, [r.number for r in self.rows])
        except (OSError, sqlite3.Error) as exc:
            self.logged.emit(f"Could not read the hours spent from {path}: {exc}")
            self.status.setText("Could not read mytime.db")
            return None
        changed = progressmod.update(self.rows, hours)
        self.store()
        self.reload()
        total = sum(hours.values())
        self.logged.emit(f"Updated the hours spent from {path.name}: {changed} "
                         f"project{'' if changed == 1 else 's'} changed, "
                         f"{total:g} hours in all")
        self.status.setText(f"Hours spent read from {path.name}")
        return changed
