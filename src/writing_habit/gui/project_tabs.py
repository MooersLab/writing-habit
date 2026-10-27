"""The project lists of the Schedule tab, chosen by buttons in two rows.

The first row holds the weeks: This week, the eight weeks ahead, and the
grasscatcher. The second row holds the semesters: the current one, the
carried-over and completed lists, and the six semesters ahead. Each row wraps
when the window is narrow. One button is checked at a time, and its page shows
below both rows.

The widget answers the calls the editor made of the tab widget it replaces,
such as ``setCurrentIndex``, ``setTabText``, and ``setTabVisible``, with the
same indexes in the order the pages were added.
"""

from __future__ import annotations

from typing import List, Optional

from .qt import Qt, QtCore, QtWidgets, pyqtSignal

WEEK_ROW, SEMESTER_ROW = 0, 1
#: One look for a list's button in every state. The chosen button changes only
#: its colours, not its font, so its text never outgrows the button, and the
#: style sheet gives the same size on every platform, macOS included.
BUTTON_STYLE = (
    "QToolButton { padding: 4px 10px; border: 1px solid #c4c4c4; border-radius: 5px; "
    "background: #f7f7f7; color: #222222; }"
    "QToolButton:hover { background: #eef3fa; }"
    "QToolButton:checked { background: #dcebfa; border: 1px solid #5b8fc9; "
    "color: #0b3d75; }")
ROW_LABELS = ("Weeks", "Semesters")
#: The buttons' text is this much larger than the window's own text.
BUTTON_SCALE = 1.3


class FlowLayout(QtWidgets.QLayout):
    """Lay widgets out left to right and wrap them onto new lines as needed."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items: List[QtWidgets.QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QtCore.QRect(0, 0, width, 0), apply=False)

    def visible_width(self, rect) -> int:
        """Return how much of ``rect``'s width the window shows.

        The Schedule tab sits in a scroll area, and its toolbars keep it
        wider than a narrow window. Wrapping at the shown width, rather than
        the full width, keeps every button in view without scrolling
        sideways when the window is narrowed.
        """
        holder = self.parentWidget()
        width = rect.width()
        if holder is None:
            return width
        widget = holder.parentWidget()
        while widget is not None and not isinstance(widget, QtWidgets.QAbstractScrollArea):
            widget = widget.parentWidget()
        if widget is None:
            return width
        viewport = widget.viewport()
        # Measure from where the row starts with the view scrolled fully
        # left, so scrolling sideways does not wrap the rows again.
        left = holder.mapTo(viewport, QtCore.QPoint(rect.x(), 0)).x()
        left += widget.horizontalScrollBar().value()
        shown = viewport.width() - max(left, 0) - 8
        widest = max((item.sizeHint().width() for item in self._items), default=0)
        return max(min(width, shown), widest)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        rect = QtCore.QRect(rect.x(), rect.y(), self.visible_width(rect), rect.height())
        needed = self._arrange(rect, apply=True)
        # Ask for the height the wrapped buttons need, so the row below is
        # never drawn over this one, whatever height the style gives a button.
        holder = self.parentWidget()
        if holder is not None and holder.minimumHeight() != needed:
            holder.setMinimumHeight(needed)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.sizeHint())
        return size

    def _arrange(self, rect, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            if item.widget() is not None and not item.widget().isVisibleTo(
                    item.widget().parentWidget()):
                continue
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self._spacing, 0
            if apply:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y()


class ProjectTabs(QtWidgets.QWidget):
    """Pages chosen by checkable buttons in a week row and a semester row."""

    currentChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages: List[QtWidgets.QWidget] = []
        self._buttons: List[QtWidgets.QToolButton] = []
        self._visible: List[bool] = []
        self._current = -1
        self.group = QtWidgets.QButtonGroup(self)
        self.group.setExclusive(True)
        self.stack = QtWidgets.QStackedWidget()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.rows: List[QtWidgets.QWidget] = []
        self.flows: List[FlowLayout] = []
        for label in ROW_LABELS:
            row = QtWidgets.QWidget()
            row.setObjectName(f"projectRow{label}")
            line = QtWidgets.QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            caption = QtWidgets.QLabel(label)
            caption.setStyleSheet("color: #898781;")
            caption.setFixedWidth(caption.fontMetrics().horizontalAdvance("Semesters") + 8)
            caption.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            caption.setContentsMargins(0, 5, 0, 0)
            line.addWidget(caption)
            holder = QtWidgets.QWidget()
            flow = FlowLayout(holder)
            line.addWidget(holder, 1)
            row.setFocusPolicy(Qt.StrongFocus)
            layout.addWidget(row)
            self.rows.append(row)
            self.flows.append(flow)
        layout.addWidget(self.stack, 1)
        self._watched = None

    # -- following the window's width ---------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._watch_scroll_area()

    def _watch_scroll_area(self) -> None:
        """Wrap the rows again when the scroll area around them is resized."""
        widget = self.parentWidget()
        while widget is not None and not isinstance(widget, QtWidgets.QAbstractScrollArea):
            widget = widget.parentWidget()
        if widget is None or widget is self._watched:
            return
        self._watched = widget
        widget.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if self._watched is not None and obj is self._watched.viewport() \
                and event.type() == QtCore.QEvent.Resize:
            self.rewrap()
        return False

    def rewrap(self) -> None:
        """Lay the button rows out again for the width now shown."""
        for flow in self.flows:
            holder = flow.parentWidget()
            if holder is not None:
                flow.setGeometry(holder.rect())

    # -- adding --------------------------------------------------------------
    def addTab(self, page: QtWidgets.QWidget, title: str, row: int = WEEK_ROW) -> int:
        """Add ``page`` under a button titled ``title`` in ``row``.  Return its index."""
        index = len(self._pages)
        button = QtWidgets.QToolButton()
        button.setText(title)
        button.setCheckable(True)
        button.setAutoRaise(False)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setFocusPolicy(Qt.TabFocus)
        button.setStyleSheet(BUTTON_STYLE)
        font = button.font()
        font.setPointSizeF(font.pointSizeF() * BUTTON_SCALE)
        button.setFont(font)
        button.clicked.connect(lambda _checked=False, i=index: self.setCurrentIndex(i))
        self.group.addButton(button, index)
        self.flows[row].addWidget(button)
        self.stack.addWidget(page)
        self._pages.append(page)
        self._buttons.append(button)
        self._visible.append(True)
        if self._current < 0:
            self.setCurrentIndex(index)
        return index

    # -- the calls of a tab widget ------------------------------------------
    def count(self) -> int:
        return len(self._pages)

    def tabBar(self) -> QtWidgets.QWidget:
        """Return the week row, which takes the focus as a tab bar would."""
        return self.rows[WEEK_ROW]

    def button(self, index: int) -> QtWidgets.QToolButton:
        return self._buttons[index]

    def currentIndex(self) -> int:
        return self._current

    def currentWidget(self) -> Optional[QtWidgets.QWidget]:
        return self._pages[self._current] if self._current >= 0 else None

    def widget(self, index: int) -> Optional[QtWidgets.QWidget]:
        return self._pages[index] if 0 <= index < len(self._pages) else None

    def indexOf(self, page) -> int:
        return self._pages.index(page) if page in self._pages else -1

    def setCurrentIndex(self, index: int) -> None:
        if not 0 <= index < len(self._pages) or not self._visible[index]:
            return
        self._buttons[index].setChecked(True)
        if index == self._current:
            return
        self._current = index
        self.stack.setCurrentWidget(self._pages[index])
        self.currentChanged.emit(index)

    def setCurrentWidget(self, page) -> None:
        self.setCurrentIndex(self.indexOf(page))

    def tabText(self, index: int) -> str:
        return self._buttons[index].text()

    def setTabText(self, index: int, text: str) -> None:
        if self._buttons[index].text() != text:
            self._buttons[index].setText(text)
            self._relayout()

    def tabToolTip(self, index: int) -> str:
        return self._buttons[index].toolTip()

    def setTabToolTip(self, index: int, text: str) -> None:
        self._buttons[index].setToolTip(text)

    def isTabVisible(self, index: int) -> bool:
        return self._visible[index]

    def setTabVisible(self, index: int, visible: bool) -> None:
        if self._visible[index] == visible:
            return
        self._visible[index] = visible
        self._buttons[index].setVisible(visible)
        self._relayout()
        if not visible and index == self._current:
            self.setCurrentIndex(0)

    def order_row(self, row: int, indexes) -> None:
        """Show the buttons of ``row`` in the order of the page ``indexes``.

        The indexes the editor uses keep the order the pages were added, and
        only the places of the buttons change.
        """
        flow = self.flows[row]
        place = {self._buttons[i]: n for n, i in enumerate(indexes)}
        flow._items.sort(key=lambda item: place.get(item.widget(), len(place)))
        self._relayout()

    def _relayout(self) -> None:
        for flow in self.flows:
            flow.invalidate()
            if flow.parentWidget() is not None:
                flow.parentWidget().updateGeometry()
