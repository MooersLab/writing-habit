"""Progress on the unfinished projects, kept in a table at the end of the week file.

The table is named ``progress`` and has five columns::

    #+NAME: progress
    | Project ID | Project name                | Est. hours | Hours spent | Weight |
    |------------+-----------------------------+------------+-------------+--------|
    | 0142       | RETKinaseCovalentInhibitors |        120 |        33.5 |      5 |

The writer fills in the estimated hours a project needs and its importance
weight. **Hours spent** is computed: it is the sum of the sessions of the
project in the ``zTimeSpent`` table of the time tracker, ``mytime.db``,
matched by the four-digit project number. The tracker is opened read-only.

The same table drives a suggestion for next week: the week's hours are shared
among the unfinished projects by weight, never more than a project has left,
and each project's blocks are placed in the hours the energy profile rates
best for new writing, keeping every run of blocks within two hours.

Nothing here imports Qt.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

NAME = "progress"
HEADER = ["Project ID", "Project name", "Est. hours", "Hours spent", "Weight"]
_NAME_LINE = re.compile(r"^\s*#\+NAME:\s*(.*?)\s*$", re.IGNORECASE)
_RULE = re.compile(r"^\s*\|[-+]")
_NUMBER = re.compile(r"(\d{4})")


@dataclass
class Row:
    """One project of the progress table."""

    number: str
    name: str
    estimate: Optional[float] = None    # hours the project is expected to need
    spent: float = 0.0                  # hours tracked so far
    weight: Optional[float] = None      # importance, set by the writer

    @property
    def remaining(self) -> Optional[float]:
        if self.estimate is None:
            return None
        return max(self.estimate - self.spent, 0.0)

    @property
    def label(self) -> str:
        return f"{self.number} {self.name}".strip()


def _number(text: str) -> Optional[float]:
    text = (text or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _cells(line: str) -> List[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _fmt(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:g}" if value == int(value) else f"{value:.1f}".rstrip("0").rstrip(".")


def span(lines: Sequence[str]) -> Optional[Tuple[int, int, int]]:
    """Return ``(name line, first table line, end)`` of the progress table, or ``None``."""
    for index, line in enumerate(lines):
        m = _NAME_LINE.match(line)
        if not m or m.group(1).strip().lower() != NAME:
            continue
        first = index + 1
        while first < len(lines) and lines[first].lstrip().startswith("#+"):
            first += 1
        end = first
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1
        return index, first, end
    return None


def read(lines: Sequence[str]) -> Optional[List[Row]]:
    """Return the rows of the progress table, or ``None`` when the file has none."""
    found = span(lines)
    if found is None:
        return None
    _name, first, end = found
    rows = []
    for line in lines[first:end]:
        if _RULE.match(line):
            continue
        cells = (_cells(line) + [""] * 5)[:5]
        if cells[0].lower().startswith("project"):
            continue                                   # the header row
        m = _NUMBER.search(cells[0]) or _NUMBER.match(cells[1])
        if not m:
            continue
        name = cells[1]
        if name.startswith(m.group(1)):
            name = name[4:]
        rows.append(Row(m.group(1), name.strip(), _number(cells[2]),
                        _number(cells[3]) or 0.0, _number(cells[4])))
    return rows


def render(rows: Sequence[Row]) -> List[str]:
    """Write the rows as an aligned org table with its header."""
    body = [[r.number, r.name, _fmt(r.estimate), _fmt(r.spent), _fmt(r.weight)]
            for r in rows]
    table = [HEADER] + body
    widths = [max(len(row[i]) for row in table) for i in range(5)]
    right = {2, 3, 4}

    def line(row):
        return "| " + " | ".join(c.rjust(widths[i]) if i in right and row is not HEADER
                                 else c.ljust(widths[i]) for i, c in enumerate(row)) + " |"

    rule = "|" + "+".join("-" * (w + 2) for w in widths) + "|"
    return [line(HEADER), rule] + [line(r) for r in body]


def write(lines: List[str], rows: Sequence[Row]) -> bool:
    """Write ``rows`` into the progress table of ``lines``, adding it at the end.

    Return whether the text changed. Only the table's own lines are touched.
    """
    table = render(rows)
    found = span(lines)
    if found is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", f"#+NAME: {NAME}"] + table
        return True
    _name, first, end = found
    if lines[first:end] == table:
        return False
    lines[first:end] = table
    return True


def seed(entries: Iterable, existing: Sequence[Row] = ()) -> List[Row]:
    """Return the progress rows for list ``entries``, keeping the rows already there.

    ``entries`` are project-list entries with a ``project`` name such as
    ``0142RETKinaseCovalentInhibitors``. A project without a four-digit number
    is left out, because the tracker files time by number.
    """
    rows = list(existing)
    have = {r.number for r in rows}
    for entry in entries:
        m = re.match(r"\s*(\d{4})(.*)", entry.project or "")
        if m and m.group(1) not in have:
            rows.append(Row(m.group(1), m.group(2).strip()))
            have.add(m.group(1))
    return sorted(rows, key=lambda r: r.number)


# -- hours spent, from the time tracker ---------------------------------------
def hours_spent(path, numbers: Iterable[str],
                since: Optional[str] = None) -> Dict[str, float]:
    """Return ``{number: hours}`` from the ``zTimeSpent`` table of ``path``.

    A session counts for a project when its ``ProjectID`` or the start of its
    ``ProjectDirectory`` is the project's four-digit number. The minutes come
    from the ``Start`` and ``End`` times, so they do not depend on the
    tracker's own computed columns. The tracker is opened read-only.
    """
    from .track.mytime_sync import SOURCE_TABLE, _clock, _minutes, _project_number

    wanted = set(numbers)
    totals = {n: 0 for n in wanted}
    src_path = Path(path).expanduser()
    if not src_path.is_file():
        raise FileNotFoundError(f"no time-tracking database at {src_path}")
    con = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    try:
        query = (f'SELECT DateDashed, Start, "End", ProjectID, ProjectDirectory '
                 f"FROM {SOURCE_TABLE}")
        params: list = []
        if since:
            query += " WHERE DateDashed >= ?"
            params.append(since)
        for day, start, end, project_id, directory in con.execute(query, params):
            start, end = _clock(start), _clock(end)
            if not start or not end:
                continue
            number = _project_number(project_id, directory)
            if number in wanted:
                minutes = _minutes(start, end)
                if minutes > 0:
                    totals[number] += minutes
    finally:
        con.close()
    return {n: round(m / 60, 1) for n, m in totals.items()}


def update(rows: Sequence[Row], hours: Dict[str, float]) -> int:
    """Put the tracked hours into ``rows``.  Return how many rows changed."""
    changed = 0
    for row in rows:
        new = hours.get(row.number, row.spent)
        if new != row.spent:
            row.spent = new
            changed += 1
    return changed


# -- next week's plan, from the weights and the energy profile ----------------------
@dataclass
class Placed:
    """One block of next week's suggested plan."""

    offset: int
    start: str
    end: str
    row: Row
    level: float

    def line(self) -> str:
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                "Saturday", "Sunday"]
        return f"{days[self.offset]} {self.start}-{self.end}  {self.row.label}"


@dataclass
class Plan:
    """Hours by project for next week, and the blocks that hold them."""

    capacity: int                                          # minutes to share
    shares: List[Tuple[Row, int]] = field(default_factory=list)   # (row, minutes)
    blocks: List[Placed] = field(default_factory=list)
    unplaced: List[Tuple[Row, int]] = field(default_factory=list)
    left_out: List[Row] = field(default_factory=list)       # no estimate or no weight


def share(rows: Sequence[Row], capacity: int, unit: int = 30) -> List[Tuple[Row, int]]:
    """Share ``capacity`` minutes among the rows by weight, in ``unit``-minute steps.

    Only rows with a weight above zero and time remaining take part. A row
    never gets more than it has left, and minutes it cannot use go to the
    others in proportion to their weights. The order is by weight, highest
    first, then by project number.
    """
    pool = [r for r in rows if r.weight and r.weight > 0 and r.remaining]
    left = {r.number: int(r.remaining * 60) for r in pool}
    got = {r.number: 0 for r in pool}
    units = capacity // unit
    for _ in range(units):
        open_rows = [r for r in pool if left[r.number] - got[r.number] >= unit]
        if not open_rows:
            break
        total = sum(r.weight for r in open_rows)
        # Give the next unit to the open row furthest below its fair share of
        # what the open rows hold, so time a finished row cannot use is shared
        # among the others by their weights alone.
        given = sum(got[r.number] for r in open_rows) + unit
        pick = max(open_rows, key=lambda r: (r.weight / total * given - got[r.number],
                                             r.weight, -int(r.number)))
        got[pick.number] += unit
    ordered = sorted(pool, key=lambda r: (-r.weight, r.number))
    return [(r, got[r.number]) for r in ordered if got[r.number]]


def place(shares: Sequence[Tuple[Row, int]], profile, days: Sequence[int] = range(5),
          longest: int = 90, first_hour: int = 5, last_hour: int = 21):
    """Place each project's minutes in blocks of at most ``longest`` minutes.

    The heaviest projects go first, into the slots the energy profile rates
    best for generative work. Blocks start on the quarter hour, never
    overlap, keep every run within two hours with a 15-minute break, and a
    day holds at most four blocks. Return ``(blocks, unplaced)``.
    """
    from . import energy
    from .rescue import _fits_runs

    taken: Dict[int, List[Tuple[int, int]]] = {d: [] for d in days}
    blocks: List[Placed] = []
    unplaced: List[Tuple[Row, int]] = []
    for row, minutes in shares:
        pieces = []
        while minutes > 0:
            piece = min(longest, minutes)
            pieces.append(piece)
            minutes -= piece
        missing = 0
        for piece in pieces:
            best = None
            for day in days:
                if len(taken[day]) >= 4:
                    continue
                for first in range(first_hour * 60, last_hour * 60 - piece + 1, 15):
                    last = first + piece
                    if any(first < b and a < last for a, b in taken[day]):
                        continue
                    if not _fits_runs(taken[day] + [(first, last)]):
                        continue
                    level = energy.fit(profile, "generative",
                                       f"{first // 60:02d}:{first % 60:02d}",
                                       f"{last // 60:02d}:{last % 60:02d}")
                    key = (-level, len(taken[day]), day, first)
                    if best is None or key < best[0]:
                        best = (key, day, first, last, level)
            if best is None:
                missing += piece
                continue
            _key, day, first, last, level = best
            taken[day].append((first, last))
            blocks.append(Placed(day, f"{first // 60:02d}:{first % 60:02d}",
                                 f"{last // 60:02d}:{last % 60:02d}", row, level))
        if missing:
            unplaced.append((row, missing))
    blocks.sort(key=lambda b: (b.offset, b.start))
    return blocks, unplaced


def plan(rows: Sequence[Row], capacity: int, profile) -> Plan:
    """Suggest next week's plan from the progress rows and the energy profile."""
    result = Plan(capacity)
    result.left_out = [r for r in rows if r.estimate is None or not r.weight]
    result.shares = share(rows, capacity)
    result.blocks, result.unplaced = place(result.shares, profile)
    return result


def _hours(minutes: int) -> str:
    hours, rest = divmod(int(minutes), 60)
    return f"{hours} h {rest:02d} min" if hours else f"{rest} min"


def facts(p: Plan) -> str:
    from . import energy
    lines = [f"Minutes to plan next week: {p.capacity} ({_hours(p.capacity)})"]
    for row, minutes in p.shares:
        lines.append(f"Project {row.label}: weight {_fmt(row.weight)}, "
                     f"{_fmt(row.remaining)} hours left of {_fmt(row.estimate)}, "
                     f"planned {minutes} minutes ({_hours(minutes)})")
    for b in p.blocks:
        lines.append(f"Block: {b.line()}, in {energy.word(b.level)} hours for new writing")
    for row, minutes in p.unplaced:
        lines.append(f"Not placed: {row.label}, {minutes} minutes, for want of a free slot")
    for row in p.left_out:
        lines.append(f"Left out: {row.label}, because it has no "
                     + ("estimate" if row.estimate is None else "weight"))
    return "\n".join(lines)


def plain(p: Plan) -> str:
    if not p.shares:
        return ("No project in the progress table has both a weight and time left, "
                "so there is nothing to share out. Fill in the Est. hours and Weight "
                "columns on the Progress tab.")
    named = [f"{row.label} ({_hours(minutes)})" for row, minutes in p.shares]
    text = (f"Next week's {_hours(p.capacity)} go by weight to "
            + (", ".join(named[:-1]) + (", and " if len(named) > 2 else " and ") + named[-1]
               if len(named) > 1 else named[0]) + ".")
    text += (" The heaviest projects take the hours your energy profile rates best "
             "for new writing, in blocks of at most 90 minutes with a break after "
             "every two hours.")
    if p.unplaced:
        text += " " + "; ".join(f"{_hours(m)} of {r.label} found no free slot"
                                for r, m in p.unplaced) + "."
    if p.left_out:
        text += (f" {len(p.left_out)} project{'' if len(p.left_out) == 1 else 's'} "
                 "without an estimate or a weight "
                 f"{'was' if len(p.left_out) == 1 else 'were'} left out.")
    return text
