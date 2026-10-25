"""Missed-block rescue: make up a missed block, or let it go on purpose.

A missed block is information, not a verdict (Rule 9). Some missed blocks are
worth making up later in the week, and some are better let go so the rest of
the week stays keepable. This module decides which, by rules a writer can
check, and finds a slot for each block worth rescuing.

A block counts as missed when its time has passed and no session of its
project was tracked inside it. The rules, in order:

- Support blocks are let go, because email and chores fill whatever time they
  are given.
- At most two blocks a week are rescued, demanding work and the nearest
  deadline first, so missed time does not snowball into an overloaded week.
- A rescue slot is the length of the missed block, on the same day later or on
  a later day of the week. It lies in hours that the energy profile rates
  medium or high for the block's activity, overlaps no block, and keeps every
  run of blocks within two hours, with a break of at least 15 minutes after.
  The slot with the best energy wins. Among equals, a day without another
  make-up comes first, so make-ups spread across the week, then the earliest.
- A block with no such slot is let go, with the reason.

Nothing here imports Qt, and nothing here changes a file.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from . import energy
from .name import split_deadline

#: At most this many missed blocks are rescued in one week.
MAX_RESCUES = 2
#: The longest run of blocks without a break, and the shortest break, in minutes.
LONGEST_RUN = 120
BREAK_GAP = 15
#: Rescue slots start no earlier and end no later than these hours.
FIRST_HOUR, LAST_HOUR = 5, 22

DAY_NAMES = energy.DAY_NAMES


def _minute(clock: str) -> int:
    return int(clock[:2]) * 60 + int(clock[3:5])


def _clock(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


@dataclass
class Rescue:
    """A missed block and where to make it up, or why to let it go."""

    missed: energy.Slot
    offset: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None
    level: float = 0.0
    reason: str = ""

    @property
    def rescued(self) -> bool:
        return self.offset is not None

    def label(self) -> str:
        return f"{DAY_NAMES[self.offset]} {self.start}-{self.end}" if self.rescued else ""

    def line(self) -> str:
        """One checkable line for the dialog."""
        m = self.missed
        return (f"Make up {m.category} {m.code} from {m.label()} on "
                f"{self.label()}")


def missed_blocks(slots: Sequence[energy.Slot], outcomes: Sequence[dict],
                  monday: _dt.date, now: _dt.datetime) -> List[energy.Slot]:
    """Return the table's blocks that have passed with nothing tracked in them.

    ``outcomes`` are the rows of :func:`writing_habit.review.block_outcomes` for
    the week. A block is matched to its outcome by day, start, and code, so a
    block added to the table after plan import is not judged.
    """
    status = {(o["day"], o["start_time"], o["code"]): o["status"] for o in outcomes}
    out = []
    for s in slots:
        day = monday + _dt.timedelta(days=s.offset)
        ended = _dt.datetime.combine(day, _dt.time(*divmod(_minute(s.end), 60)))
        if _minute(s.end) <= _minute(s.start):
            ended += _dt.timedelta(days=1)
        if ended > now:
            continue
        if status.get((day.isoformat(), s.start, s.code)) == "missed":
            out.append(s)
    return out


def _fits_runs(intervals: List[Tuple[int, int]]) -> bool:
    """Whether every run of blocks on a day stays within two hours."""
    ordered = sorted(intervals)
    run_start, run_end = None, None
    for first, last in ordered:
        if run_end is not None and first - run_end < BREAK_GAP:
            run_end = max(run_end, last)
        else:
            run_start, run_end = first, last
        if run_end - run_start > LONGEST_RUN:
            return False
    return True


def find_slot(missed: energy.Slot, slots: Sequence[energy.Slot], profile,
              days: Sequence[int], monday: _dt.date, now: _dt.datetime,
              taken: Sequence[Tuple[int, int, int]] = ()):
    """Return ``(offset, start, end, level)`` of the best slot, or ``None``.

    ``days`` are the day offsets the table has columns for. ``taken`` holds
    ``(offset, first, last)`` minutes already promised to earlier rescues.
    """
    length = missed.minutes
    best = None
    for offset in days:
        day = monday + _dt.timedelta(days=offset)
        if day < now.date() or offset < missed.offset:
            continue
        busy = [(_minute(s.start), _minute(s.end)) for s in slots if s.offset == offset]
        busy += [(a, b) for o, a, b in taken if o == offset]
        earliest = FIRST_HOUR * 60
        if day == now.date():
            earliest = max(earliest, -(-(now.hour * 60 + now.minute) // 15) * 15)
        for first in range(earliest, LAST_HOUR * 60 - length + 1, 15):
            last = first + length
            if any(first < b and a < last for a, b in busy):
                continue
            level = energy.fit(profile, missed.category, _clock(first), _clock(last))
            if level < energy.FITS:
                continue
            if not _fits_runs(busy + [(first, last)]):
                continue
            crowded = any(o == offset for o, _a, _b in taken)
            key = (-level, crowded, offset, first)
            if best is None or key < best[0]:
                best = (key, (offset, _clock(first), _clock(last), level))
    return best[1] if best else None


def plan(slots: Sequence[energy.Slot], missed: Sequence[energy.Slot], profile,
         days: Sequence[int], monday: _dt.date, now: _dt.datetime,
         legend: Dict[str, str]) -> List[Rescue]:
    """Decide for each missed block whether to make it up, and where."""
    def deadline(code: str) -> str:
        return split_deadline(legend.get(code, ""))[1] or "9999-12-31"

    order = sorted(missed, key=lambda s: (s.category == "support", deadline(s.code),
                                          -s.offset, s.start))
    out: List[Rescue] = []
    taken: List[Tuple[int, int, int]] = []
    rescued = 0
    for m in order:
        if m.category == "support":
            out.append(Rescue(m, reason="support work fills whatever time it gets, "
                                        "so let it go"))
            continue
        if rescued >= MAX_RESCUES:
            out.append(Rescue(m, reason=f"{MAX_RESCUES} blocks are already being made "
                                        "up this week, and more would overload it"))
            continue
        found = find_slot(m, slots, profile, days, monday, now, taken)
        if found is None:
            out.append(Rescue(m, reason="no free time of that length is left this "
                                        "week in hours that suit the work"))
            continue
        offset, start, end, level = found
        taken.append((offset, _minute(start), _minute(end)))
        out.append(Rescue(m, offset, start, end, level))
        rescued += 1
    return sorted(out, key=lambda r: (r.missed.offset, r.missed.start))


def facts(found: Sequence[Rescue], profile) -> str:
    """Write the decisions as the facts the model receives, in words."""
    lines = []
    for r in found:
        m = r.missed
        if r.rescued:
            lines.append(f"Missed block to make up: {m.category} {m.code} from "
                         f"{m.label()}, {m.minutes} minutes, now proposed for "
                         f"{r.label()}, in {energy.word(r.level)} hours for "
                         f"{m.category} work")
        else:
            lines.append(f"Missed block to let go: {m.category} {m.code} from "
                         f"{m.label()}, because {r.reason}")
    return "\n".join(lines)


def plain(found: Sequence[Rescue]) -> str:
    """Describe the decisions without a model."""
    if not found:
        return ("No block of this week has been missed so far. Nothing needs "
                "making up.")
    lines = [f"{len(found)} block{'' if len(found) == 1 else 's'} passed with "
             "nothing tracked. A missed block is information, not a failure."]
    for r in found:
        m = r.missed
        if r.rescued:
            lines.append(f"  {m.category.capitalize()} {m.code} from {m.label()} "
                         f"can be made up on {r.label()}.")
        else:
            lines.append(f"  Let {m.category} {m.code} from {m.label()} go, "
                         f"because {r.reason}.")
    return "\n".join(lines)
