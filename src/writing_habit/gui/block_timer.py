"""The block timer: a button that counts down the writing block under way.

The button sits on the Schedule tab's second bar. It reads the open week's
planned blocks and the clock, and shows one of four states.

- In a block, the time left, such as ``A 05:00-06:30, 42 min left``.
- In the last five minutes, the same with a warm tint, so the writer can
  finish the sentence and write a next-step note.
- Just after a block, for fifteen minutes, ``A block ended. Review it``.
  Pressing the button then opens that block's objectives and review, which is
  the moment the review takes thirty seconds.
- Otherwise, the next block of the day and how soon it starts, or that no
  block is left today. Pressing it selects that block in the grid.

The timer never sounds an alarm and never interrupts. It counts the plan's
blocks only for the week the open table belongs to.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Iterable, Optional

from .qt import QtCore, QtWidgets, pyqtSignal

#: Minutes before a block's end when the button turns warm.
WARN_MINUTES = 5

#: Minutes after a block's end during which the button offers the review.
REVIEW_MINUTES = 15

#: How often the button rereads the clock, in milliseconds.
TICK_MS = 15_000

WARM_STYLE = "background: #fff0d9; border: 1px solid #e0a040;"
LIVE_STYLE = "background: #e3f0fd; border: 1px solid #2a78d6;"


def _span(block):
    first = int(block.start[:2]) * 60 + int(block.start[3:5])
    last = int(block.end[:2]) * 60 + int(block.end[3:5])
    if last <= first:
        last += 24 * 60
    return first, last


def _left(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if hours:
        return f"{hours} h {rest:02d} min"
    return f"{rest} min"


@dataclass
class TimerState:
    """What the button shows, and the block a press acts on."""

    kind: str                      # "live", "ending", "review", "next", "idle"
    text: str
    block: object = None
    minutes: Optional[int] = None


def timer_state(blocks: Iterable, monday: Optional[_dt.date],
                now: _dt.datetime) -> TimerState:
    """Return the timer's state for the clock ``now``."""
    if monday is None:
        return TimerState("idle", "No week date for the block timer")
    offset = (now.date() - monday).days
    if not 0 <= offset <= 6:
        return TimerState("idle", "This table is not this week")
    minute = now.hour * 60 + now.minute + now.second / 60.0
    today = sorted((b for b in blocks if b.offset == offset), key=_span)
    for block in today:
        first, last = _span(block)
        if first <= minute < last:
            left = int(last - minute + 0.999)       # round a part-minute up
            kind = "ending" if left <= WARN_MINUTES else "live"
            return TimerState(kind, f"{block.letter} {block.start}-{block.end}, "
                                    f"{_left(left)} left", block, left)
    ended = [b for b in today if 0 <= minute - _span(b)[1] < REVIEW_MINUTES]
    if ended:
        block = ended[-1]
        return TimerState("review", f"{block.letter} block ended. Review it", block)
    later = [b for b in today if _span(b)[0] > minute]
    if later:
        block = later[0]
        wait = int(_span(block)[0] - minute + 0.999)
        return TimerState("next", f"Next block {block.letter} at {block.start}, in "
                                  f"{_left(wait)}", block, wait)
    return TimerState("idle", "No more blocks today")


class BlockTimerButton(QtWidgets.QPushButton):
    """A button that shows the time left in the current block."""

    #: Emitted with the block to select in the grid.
    select_requested = pyqtSignal(object)
    #: Emitted with the block whose review should open.
    review_requested = pyqtSignal(object)

    def __init__(self, blocks, monday, parent=None):
        super().__init__(parent)
        self.blocks = blocks
        self.monday = monday
        #: The clock.  A test replaces it.
        self.now = _dt.datetime.now
        self.state = TimerState("idle", "")
        self.setToolTip(
            "Time left in the writing block under way. After a block ends, "
            "press to review it. Between blocks, press to select the next one.")
        self.clicked.connect(self._pressed)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_state)
        self.timer.start(TICK_MS)
        self.update_state()

    def update_state(self) -> TimerState:
        try:
            blocks = self.blocks()
            monday = self.monday()
        except Exception:                                # pragma: no cover
            blocks, monday = [], None
        self.state = timer_state(blocks, monday, self.now())
        self.setText(self.state.text)
        self.setStyleSheet(WARM_STYLE if self.state.kind in ("ending", "review")
                           else LIVE_STYLE if self.state.kind == "live" else "")
        self.setEnabled(self.state.block is not None)
        return self.state

    def _pressed(self) -> None:
        block = self.update_state().block
        if block is None:
            return
        if self.state.kind == "review":
            self.review_requested.emit(block)
        else:
            self.select_requested.emit(block)
