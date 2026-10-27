"""The hour view of the weekly table, and the picker that places a block.

The row view lists every candidate time range of the file, which in a table of
quarter-hour candidates runs to hundreds of rows. The hour view folds the same
table into 24 rows, one per hour, with the days as columns. A cell lists the
blocks that start in that hour, and the hours a longer block runs into are
shaded as its continuation, so a 09:30-11:00 block reads as one bar.

The view does not change the file format. Choosing a range in the picker
writes the cell of the explicit row for that range, and inserts that row in
start-time order when the file lacks it. Removing a block clears its cell and
keeps the row, so the candidate rows the writer keeps stay in the file.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Dict, List, Optional, Tuple

from . import settings
from .qt import Qt, QtCore, QtGui, QtWidgets, pyqtSignal
from .table_model import (ACTIVITY_BUTTONS, ACTIVITY_COLOR, BREAK_COLOR,
                          CONFLICT_COLOR, FIND_COLOR, SOURCE_LABEL)
from .weekly_table import (CATEGORY_LETTER, PICK_MAX, PICK_STEP, WeeklyTable,
                           picker_ranges)

HOUR_COLUMN = 0

#: The shade of an hour outside the range the printed sheet covers.
OFF_HOURS_COLOR = "#f4f4f4"

#: The mark before a code in an hour that a longer block runs into.
CONTINUES = "↓ "

#: The role that gives the part of an hour each block fills, for the painter.
SEGMENTS_ROLE = Qt.UserRole + 41
#: The opacity of a block's fill, so the borders of overlapping or touching
#: blocks and the white of a break inside the hour both show through.
FILL_ALPHA = 128
#: The sideways step between blocks that overlap in time, in pixels, so their
#: borders do not lie on top of each other.
LANE_STEP = 4


class Segment(tuple):
    """``(top, bottom, color, lane, block, starts, ends)``: a block's share of one hour.

    ``top`` and ``bottom`` are fractions of the hour, 0 at its start and 1 at
    its end, ``color`` is the block's fill as a hex string, and ``lane`` counts
    the earlier blocks in the cell that it overlaps. ``starts`` and ``ends``
    say whether the block's own start and end fall in this hour, which is
    where its edges can be dragged.
    """

    __slots__ = ()

    def __new__(cls, top: float, bottom: float, color: str, lane: int = 0,
                block=None, starts: bool = False, ends: bool = False):
        return super().__new__(cls, (top, bottom, color, lane, block, starts, ends))

    top = property(lambda self: self[0])
    bottom = property(lambda self: self[1])
    color = property(lambda self: self[2])
    lane = property(lambda self: self[3])
    block = property(lambda self: self[4])
    starts = property(lambda self: self[5])
    ends = property(lambda self: self[6])


def _minutes(clock: str) -> int:
    return int(clock[:2]) * 60 + int(clock[3:5])


def hour_segments(hour: int, blocks, color_of) -> List[Segment]:
    """Return the part of hour ``hour`` that each of ``blocks`` fills.

    ``color_of`` gives a block's fill colour. A block that crosses midnight
    runs to the end of the day. Blocks that overlap in time take successive
    lanes, so the painter can offset their outlines.
    """
    first_minute, last_minute = hour * 60, hour * 60 + 60
    out: List[Segment] = []
    spans: List[Tuple[int, int, int]] = []
    for block in sorted(blocks, key=lambda b: (b.start, b.end, b.row, b.column)):
        start, end = _minutes(block.start), _minutes(block.end)
        if end <= start:
            end = 24 * 60
        top, bottom = max(start, first_minute), min(end, last_minute)
        if bottom <= top:
            continue
        lane = 0
        while any(lane == used and top < b and a < bottom for a, b, used in spans):
            lane += 1
        spans.append((top, bottom, lane))
        out.append(Segment((top - first_minute) / 60, (bottom - first_minute) / 60,
                           color_of(block), lane, block,
                           first_minute <= start < last_minute,
                           first_minute < end <= last_minute))
    return out


def sheet_hours() -> Tuple[int, int]:
    """Return the first and last hour the printed sheet draws."""
    try:
        from writing_schedule.config import Config
        config = Config()
        return config.timeblock_start_hour, config.timeblock_end_hour
    except Exception:                                  # pragma: no cover
        return 4, 23


def block_label(block) -> str:
    """Return ``gB 04:00-06:00`` for a block, with its activity letter."""
    letter = CATEGORY_LETTER.get(block.category, "")
    return f"{letter}{block.letter} {block.start}-{block.end}"


class HourGridModel(QtCore.QAbstractTableModel):
    """A :class:`WeeklyTable` folded into 24 hour rows by the days."""

    def __init__(self, table: Optional[WeeklyTable] = None, parent=None):
        super().__init__(parent)
        self.table: Optional[WeeklyTable] = None
        self._starts: Dict[Tuple[int, int], list] = {}
        self._spans: Dict[Tuple[int, int], list] = {}
        self._conflicts: set = set()
        self._breaks: set = set()
        #: The project codes the search box matches; their cells are tinted.
        self.highlight: set = set()
        #: A block being resized by dragging an edge, drawn at its new range:
        #: ``(block, start, end)``, or ``None``.
        self.preview = None
        self._hours = sheet_hours()
        self.set_table(table)

    def set_table(self, table: Optional[WeeklyTable]) -> None:
        self.beginResetModel()
        self.table = table
        self._index()
        self.endResetModel()

    def _index(self) -> None:
        if self.table is None:
            self._starts, self._spans = {}, {}
            self._conflicts, self._breaks = set(), set()
            return
        self._starts = self.table.hour_blocks()
        self._spans = self.table.hour_spans()
        self._conflicts = self.table.conflicting_cells()
        self._breaks = self.table.break_cells()

    def refresh(self) -> None:
        """Recompute after the document changed."""
        self._index()
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(self.rowCount() - 1,
                                             self.columnCount() - 1))

    def set_preview(self, preview) -> None:
        """Draw ``(block, start, end)`` at its new range while it is dragged."""
        self.preview = preview
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(self.index(0, 1),
                                  self.index(self.rowCount() - 1, self.columnCount() - 1),
                                  [SEGMENTS_ROLE])

    def set_highlight(self, codes) -> None:
        """Tint the cells of the projects in ``codes``; an empty set clears it."""
        codes = set(codes or ())
        if codes == self.highlight:
            return
        self.highlight = codes
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(self.rowCount() - 1, self.columnCount() - 1))

    # -- lookups -----------------------------------------------------------
    def offset(self, column: int) -> int:
        """Return the day offset of grid column ``column``."""
        return self.table.columns[column - 1][1]

    def blocks_at(self, row: int, column: int) -> list:
        """Return the blocks that start in hour ``row`` of day ``column``."""
        if self.table is None or column == HOUR_COLUMN:
            return []
        return list(self._starts.get((self.offset(column), row), []))

    def spans_at(self, row: int, column: int) -> list:
        """Return the earlier blocks that run into hour ``row`` of ``column``."""
        if self.table is None or column == HOUR_COLUMN:
            return []
        return list(self._spans.get((self.offset(column), row), []))

    def in_sheet(self, hour: int) -> bool:
        first, last = self._hours
        return first <= hour <= last

    # -- Qt ----------------------------------------------------------------
    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() or self.table is None else 24

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() or self.table is None else 1 + len(self.table.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or self.table is None:
            return None
        if orientation == Qt.Horizontal:
            return "Hour" if section == HOUR_COLUMN else self.table.day_labels[section - 1]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self.table is None:
            return None
        row, column = index.row(), index.column()
        if column == HOUR_COLUMN:
            if role == Qt.DisplayRole:
                return f"{row:02d}:00"
            if role == Qt.BackgroundRole and not self.in_sheet(row):
                return QtGui.QBrush(QtGui.QColor(OFF_HOURS_COLOR))
            if role == Qt.ToolTipRole and not self.in_sheet(row):
                return "Outside the hours the printed sheet draws"
            return None

        starts = self.blocks_at(row, column)
        spans = self.spans_at(row, column)
        if role == Qt.DisplayRole:
            lines = [block_label(b) for b in starts]
            if not starts:
                lines = [CONTINUES + CATEGORY_LETTER.get(b.category, "") + b.letter
                         for b in spans]
            return "\n".join(lines)
        found = bool(self.highlight) and any(
            b.letter in self.highlight for b in starts + spans)
        if role == Qt.FontRole and found:
            font = QtGui.QFont()
            font.setBold(True)
            return font
        if role == Qt.BackgroundRole:
            cells = {(b.row, b.column) for b in starts + spans}
            if cells & self._conflicts:
                return QtGui.QBrush(QtGui.QColor(CONFLICT_COLOR))
            if found:
                return QtGui.QBrush(QtGui.QColor(FIND_COLOR))
            if cells & self._breaks:
                return QtGui.QBrush(QtGui.QColor(BREAK_COLOR))
            first = (starts or spans or [None])[0]
            if first is not None:
                return QtGui.QBrush(QtGui.QColor(ACTIVITY_COLOR[first.category]))
            if not self.in_sheet(row):
                return QtGui.QBrush(QtGui.QColor(OFF_HOURS_COLOR))
            return None
        if role == SEGMENTS_ROLE:
            blocks = spans + starts
            if self.preview is not None:
                moving, start, end = self.preview
                key = (moving.row, moving.column)
                blocks = [b for b in blocks if (b.row, b.column) != key]
                if moving.offset == self.offset(column):
                    blocks.append(dataclasses.replace(moving, start=start, end=end))
            return hour_segments(row, blocks, lambda b: self.block_color(b, found))
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignCenter)
        if role == Qt.ToolTipRole:
            return self.tooltip(starts, spans)
        return None

    def block_color(self, block, found: bool = False) -> str:
        """Return the fill of one block, by the same priorities as the cell."""
        cell = (block.row, block.column)
        if cell in self._conflicts:
            return CONFLICT_COLOR
        if found and block.letter in self.highlight:
            return FIND_COLOR
        if cell in self._breaks:
            return BREAK_COLOR
        return ACTIVITY_COLOR[block.category]

    def tooltip(self, starts, spans) -> Optional[str]:
        lines: List[str] = []
        for block in starts + spans:
            info = self.table.project_info(block.letter)
            name = (info or {}).get("name") or "not in the key"
            lines.append(f"{block_label(block)}  {block.letter}: {name}")
            lines.append(f"  Activity: {block.category} "
                         f"({SOURCE_LABEL[block.activity_source]})")
            if (block.row, block.column) in self._conflicts:
                lines.append("  Overlaps another block")
            if (block.row, block.column) in self._breaks:
                lines.append(f"  Part of a run over {PICK_MAX // 60} hours "
                             "with no 15-minute break")
        if not lines:
            return "Double-click or press Enter to place a block in this hour"
        return "\n".join(lines)


class HourCellDelegate(QtWidgets.QStyledItemDelegate):
    """Paint each block as a half-transparent bar over the minutes it fills.

    A cell no longer takes one colour for the whole hour. Each block is drawn
    from its start to its end within the hour with a fill at half opacity and
    a solid outline, so two blocks that touch show the line between them, two
    that overlap show both outlines and a deeper colour where they cross, and
    a break inside the hour stays white.
    """

    def paint(self, painter, option, index):
        segments = index.data(SEGMENTS_ROLE)
        if not segments:
            super().paint(painter, option, index)
            return
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        rect = opt.rect
        painter.save()
        base = QtGui.QColor("#ffffff")
        hour = index.row()
        model = index.model()
        if hasattr(model, "in_sheet") and not model.in_sheet(hour):
            base = QtGui.QColor(OFF_HOURS_COLOR)
        painter.fillRect(rect, base)
        for segment in segments:
            top = rect.top() + round(segment.top * rect.height())
            bottom = rect.top() + round(segment.bottom * rect.height())
            inset = 1 + LANE_STEP * segment.lane
            bar = QtCore.QRect(rect.left() + inset, top,
                               max(rect.width() - 2 * inset, 4), max(bottom - top, 2))
            fill = QtGui.QColor(segment.color)
            outline = fill.darker(170)
            fill.setAlpha(FILL_ALPHA)
            painter.fillRect(bar, fill)
            painter.setPen(QtGui.QPen(outline, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(bar.adjusted(0, 0, -1, -1))
        painter.restore()
        # The text and any selection are drawn over the bars, without the
        # cell's own background, which the bars replace.
        opt.backgroundBrush = QtGui.QBrush(Qt.NoBrush)
        style = opt.widget.style() if opt.widget is not None else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, opt, painter, opt.widget)


class EdgeDragger(QtCore.QObject):
    """Resize a block in the hour view by dragging its top or bottom edge.

    Over an edge the cursor becomes a vertical double arrow. Pressing there
    and dragging moves that edge in steps of 15 minutes, and the block is
    drawn at its new range while the mouse moves. Releasing calls
    ``apply(block, start, end)``, which changes the table. Escape, or a
    release where the range has not changed, leaves the block as it was.
    """

    #: How near an edge, in pixels, the mouse must be to grab it.
    GRAB = 4

    def __init__(self, view, apply, parent=None):
        super().__init__(parent or view)
        self.view = view
        self.apply = apply
        self.drag = None          # (block, "top" or "bottom")
        self.range = None         # (start, end) under the mouse
        view.viewport().setMouseTracking(True)
        view.viewport().installEventFilter(self)
        view.installEventFilter(self)

    @property
    def model(self):
        return self.view.model()

    def edge_at(self, pos):
        """Return ``(block, "top" or "bottom")`` for the edge under ``pos``, or ``None``."""
        index = self.view.indexAt(pos)
        if not index.isValid() or index.column() == HOUR_COLUMN:
            return None
        rect = self.view.visualRect(index)
        for segment in reversed(index.data(SEGMENTS_ROLE) or []):
            inset = 1 + LANE_STEP * segment.lane
            if not rect.left() + inset <= pos.x() <= rect.right() - inset:
                continue
            top = rect.top() + round(segment.top * rect.height())
            bottom = rect.top() + round(segment.bottom * rect.height())
            if segment.ends and abs(pos.y() - bottom) <= self.GRAB:
                return segment.block, "bottom"
            if segment.starts and abs(pos.y() - top) <= self.GRAB:
                return segment.block, "top"
        return None

    def minute_at(self, y: int) -> Optional[int]:
        """Return the minute of the day at height ``y``, to the nearest 15 minutes."""
        row = self.view.rowAt(y)
        if row < 0:
            row = 0 if y < 0 else self.model.rowCount() - 1
            return row * 60 if y < 0 else 24 * 60
        top = self.view.rowViewportPosition(row)
        height = max(self.view.rowHeight(row), 1)
        minute = row * 60 + (y - top) * 60 / height
        return int(round(minute / PICK_STEP) * PICK_STEP)

    def new_range(self, y: int):
        block, edge = self.drag
        first, last = _minutes(block.start), _minutes(block.end)
        minute = self.minute_at(y)
        if edge == "top":
            first = max(0, min(minute, last - PICK_STEP))
        else:
            last = min(24 * 60, max(minute, first + PICK_STEP))
        return (f"{first // 60:02d}:{first % 60:02d}", f"{last // 60:02d}:{last % 60:02d}")

    def cancel(self) -> None:
        self.drag, self.range = None, None
        self.model.set_preview(None)
        self.view.viewport().unsetCursor()

    def eventFilter(self, obj, event):
        kind = event.type()
        if obj is self.view:
            if kind == QtCore.QEvent.KeyPress and self.drag and event.key() == Qt.Key_Escape:
                self.cancel()
                return True
            return False
        if kind == QtCore.QEvent.MouseMove:
            if self.drag is not None:
                self.range = self.new_range(event.pos().y())
                block = self.drag[0]
                self.model.set_preview((block, *self.range))
                self.view.setToolTip("")
                QtWidgets.QToolTip.showText(event.globalPos(), "-".join(self.range),
                                            self.view.viewport())
                return True
            if self.edge_at(event.pos()):
                self.view.viewport().setCursor(Qt.SizeVerCursor)
            else:
                self.view.viewport().unsetCursor()
            return False
        if kind == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            edge = self.edge_at(event.pos())
            if edge is None:
                return False
            self.drag = edge
            self.range = (edge[0].start, edge[0].end)
            self.view.setCurrentIndex(self.view.indexAt(event.pos()))
            return True
        if kind == QtCore.QEvent.MouseButtonRelease and self.drag is not None:
            block, _edge = self.drag
            start, end = self.range
            self.cancel()
            if (start, end) != (block.start, block.end):
                self.apply(block, start, end)
            return True
        return False


# -- remembered ranges -----------------------------------------------------
def remembered(code: str) -> Optional[Tuple[int, int]]:
    """Return the (minutes past the hour, length) last used for ``code``."""
    try:
        stored = json.loads(settings.get("picker_last") or "{}")
        offset, length = stored.get(code, (None, None))
    except (ValueError, TypeError, AttributeError):
        return None
    if offset is None or length is None:
        return None
    return int(offset), int(length)


def remember(code: str, offset: int, length: int) -> None:
    """Store the (minutes past the hour, length) just used for ``code``."""
    try:
        stored = json.loads(settings.get("picker_last") or "{}")
        if not isinstance(stored, dict):
            stored = {}
    except ValueError:
        stored = {}
    stored[code] = [offset, length]
    settings.put("picker_last", json.dumps(stored, sort_keys=True))


class HourPicker(QtWidgets.QDialog):
    """Choose a project, an activity, and one of 32 ranges for one hour.

    One click on a range places the block and closes the dialog. The range
    last used for the chosen project is the default button, so Enter repeats
    it. The blocks that already start in the hour are listed with a Remove
    button each.
    """

    #: Emitted with (row, column) of a cell the writer asked to clear.
    remove_requested = pyqtSignal(int, int)

    def __init__(self, table: WeeklyTable, offset: int, day_label: str,
                 hour: int, existing=(), parent=None, monday=None,
                 review_blocks=None, db_path=None):
        super().__init__(parent)
        self.table = table
        self.hour = hour
        self.offset = offset
        #: The (start, end, value) chosen, or ``None`` until a range is clicked.
        self.choice: Optional[Tuple[str, str, str]] = None
        self.setWindowTitle(f"Place a block: {day_label} {hour:02d}:00")
        outer = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(left)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Project"))
        self.code_box = QtWidgets.QComboBox()
        self.code_box.setEditable(True)
        legend = table.legend()
        for code, (description, _risk) in legend.items():
            self.code_box.addItem(f"{code}  {description}".strip(), code)
        top.addWidget(self.code_box, 1)
        self.activity_buttons: Dict[str, QtWidgets.QToolButton] = {}
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        for letter, label, tip in ACTIVITY_BUTTONS:
            button = QtWidgets.QToolButton()
            button.setText(label)
            button.setToolTip(tip)
            button.setCheckable(True)
            group.addButton(button)
            top.addWidget(button)
            self.activity_buttons[letter] = button
        layout.addLayout(top)

        grid = QtWidgets.QGridLayout()
        lengths = range(PICK_STEP, PICK_MAX + 1, PICK_STEP)
        for column, length in enumerate(lengths, start=1):
            hours, minutes = divmod(length, 60)
            head = QtWidgets.QLabel(f"{hours}:{minutes:02d}" if hours else f":{minutes:02d}")
            head.setAlignment(Qt.AlignCenter)
            grid.addWidget(head, 0, column)
        self.range_buttons: Dict[Tuple[int, int], QtWidgets.QPushButton] = {}
        for r, row in enumerate(picker_ranges(hour)):
            start_label = QtWidgets.QLabel(f"{hour:02d}:{r * PICK_STEP:02d}")
            grid.addWidget(start_label, r + 1, 0)
            for c, item in enumerate(row):
                button = QtWidgets.QPushButton(item[1] if item else "")
                button.setAutoDefault(False)
                button.setEnabled(item is not None)
                if item is not None:
                    button.setToolTip(f"{item[0]}-{item[1]}")
                    button.clicked.connect(
                        lambda _checked=False, item=item: self.choose(*item))
                grid.addWidget(button, r + 1, c + 1)
                self.range_buttons[(r * PICK_STEP, (c + 1) * PICK_STEP)] = button
        layout.addLayout(grid)
        note = QtWidgets.QLabel(
            f"Lengths run in {PICK_STEP}-minute steps up to {PICK_MAX // 60} hours, "
            "so every block ends in time for a break.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.push_box = QtWidgets.QCheckBox("Push later blocks down")
        self.push_box.setToolTip(
            "When the new block overlaps a block that starts after it on the "
            "same day, move that block down to start where the new one ends")
        self.push_box.setChecked(settings.get("push_blocks") != "false")
        layout.addWidget(self.push_box)

        self.existing = list(existing)
        if self.existing:
            box = QtWidgets.QGroupBox("Blocks that start in this hour")
            box_layout = QtWidgets.QVBoxLayout(box)
            self.remove_buttons = []
            for block in self.existing:
                line = QtWidgets.QHBoxLayout()
                line.addWidget(QtWidgets.QLabel(block_label(block)), 1)
                remove = QtWidgets.QPushButton("Remove")
                remove.setAutoDefault(False)
                remove.clicked.connect(
                    lambda _checked=False, b=block: self._remove(b))
                line.addWidget(remove)
                self.remove_buttons.append(remove)
                box_layout.addLayout(line)
            layout.addWidget(box)
        else:
            self.remove_buttons = []

        cancel = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        cancel.rejected.connect(self.reject)
        layout.addWidget(cancel)

        # The blocks of this hour carry their objectives and review on the
        # right, so the writer plans and reviews where the block is placed.
        self.review_panel = None
        blocks = list(review_blocks if review_blocks is not None else self.existing)
        if blocks:
            from .review_panel import ReviewPanel
            line = QtWidgets.QFrame()
            line.setFrameShape(QtWidgets.QFrame.VLine)
            outer.addWidget(line)
            self.review_panel = ReviewPanel(table, monday, blocks, db_path, self)
            outer.addWidget(self.review_panel, 1)

        self.code_box.currentIndexChanged.connect(lambda _i: self._follow_code())
        self._follow_code()

    def code(self) -> str:
        data = self.code_box.currentData()
        if data and self.code_box.currentText().startswith(data):
            return str(data)
        text = self.code_box.currentText().strip().split()
        return text[0].upper() if text else ""

    def push(self) -> bool:
        """Return whether the later blocks the new one overlaps move down."""
        return self.push_box.isChecked()

    def activity(self) -> str:
        for letter, button in self.activity_buttons.items():
            if button.isChecked():
                return letter
        return "g"

    def _follow_code(self) -> None:
        """Set the activity and the default range for the chosen project."""
        code = self.code()
        default = self.table.legend_defaults().get(code, "generative")
        letter = CATEGORY_LETTER.get(default, "g")
        self.activity_buttons[letter].setChecked(True)
        for button in self.range_buttons.values():
            button.setDefault(False)
        last = remembered(code) if code else None
        button = self.range_buttons.get(last) if last else None
        if button is not None and button.isEnabled():
            button.setDefault(True)
            button.setFocus()

    def default_range(self) -> Optional[Tuple[int, int]]:
        for key, button in self.range_buttons.items():
            if button.isDefault():
                return key
        return None

    def choose(self, start: str, end: str) -> None:
        code = self.code()
        if not code:
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), "Choose a project first")
            return
        self.choice = (start, end, self.activity() + code)
        offset = int(start[3:5])
        length = (int(end[:2]) * 60 + int(end[3:5])) - (int(start[:2]) * 60 + offset)
        remember(code, offset, length)
        self.accept()

    def done(self, result) -> None:
        if self.review_panel is not None:
            self.review_panel.save_if_changed()
        super().done(result)

    def _remove(self, block) -> None:
        self.remove_requested.emit(block.row, block.column)
        self.done(QtWidgets.QDialog.Accepted)
