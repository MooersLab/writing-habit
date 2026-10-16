"""Named planning periods, such as semesters, quarters, or fiscal years.

One calendar file serves every weekly table. It is a plain org table named
``periods``, so Emacs and this package read it the same way::

    #+NAME: periods
    | Kind     | Name        | Start      | End        | Horizon |
    |----------+-------------+------------+------------+---------|
    | semester | Fall 2026   | 2026-08-04 | 2026-12-18 | yes     |
    | semester | Spring 2027 | 2026-12-19 | 2027-05-14 | yes     |

The project lists of a weekly table are named relative to the current period
(current, next, next next, and so on). The calendar turns those relative names
into titles such as "Fall 2027 projects", and tells the editor when a new
period has begun so the lists can be rolled forward.

Nothing here imports Qt.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Tuple

#: The name of the org table in the calendar file.
TABLE_NAME = "periods"
HEADERS = ["Kind", "Name", "Start", "End", "Horizon"]
DEFAULT_KIND = "semester"
#: The file name looked for beside the weekly tables.
FILE_NAME = "periods.org"
#: The archive of completed projects, beside the calendar.
ARCHIVE_NAME = "completed.org"

_NAME_LINE = re.compile(r"^\s*#\+NAME:\s*(\S+)\s*$", re.IGNORECASE)
_RULE = re.compile(r"^\s*\|[-+]")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: The longest gap between two periods of one kind before the check warns.
GAP_DAYS = 60

#: The styles offered by Fill a year, as (key, label).
TEMPLATES = [
    ("semesters", "Semesters: spring, summer, fall"),
    ("quarters", "Academic quarters: winter, spring, summer, fall"),
    ("trimesters", "Trimesters: fall, winter, spring"),
    ("calendar-quarters", "Calendar quarters: Q1 to Q4"),
    ("fiscal-year", "Fiscal year"),
]


@dataclass(frozen=True)
class Period:
    kind: str
    name: str
    start: _dt.date
    end: _dt.date
    horizon: bool = True

    def holds(self, day: _dt.date) -> bool:
        return self.start <= day <= self.end

    def cells(self) -> List[str]:
        return [self.kind, self.name, self.start.isoformat(),
                self.end.isoformat(), "yes" if self.horizon else "no"]


def parse_date(text: str) -> Optional[_dt.date]:
    text = (text or "").strip()
    if not _DATE.match(text):
        return None
    try:
        return _dt.date.fromisoformat(text)
    except ValueError:
        return None


def _cells(line: str) -> List[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _row_text(cells: List[str], widths: List[int]) -> str:
    return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"


class Calendar:
    """The periods of one calendar file, with the file's other lines kept."""

    def __init__(self, periods: Optional[List[Period]] = None,
                 path: Optional[str] = None,
                 before: Optional[List[str]] = None,
                 after: Optional[List[str]] = None,
                 problems: Optional[List[str]] = None):
        self.periods: List[Period] = list(periods or [])
        self.path = path
        self._before = list(before if before is not None
                            else ["#+TITLE: Planning periods", ""])
        self._after = list(after or [])
        #: Rows that could not be read, as messages.
        self.read_problems: List[str] = list(problems or [])

    # -- reading and writing -------------------------------------------------
    @classmethod
    def parse(cls, text: str, path: Optional[str] = None) -> "Calendar":
        lines = text.splitlines()
        start = None
        for index, line in enumerate(lines):
            m = _NAME_LINE.match(line)
            if m and m.group(1).lower() == TABLE_NAME:
                start = index
                break
        if start is None:
            return cls([], path, before=lines, after=[])
        end = start + 1
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1
        periods: List[Period] = []
        problems: List[str] = []
        for line in lines[start + 1:end]:
            if _RULE.match(line):
                continue
            cells = _cells(line) + [""] * 5
            kind, name, first, last, horizon = cells[:5]
            if kind.lower() == "kind" and name.lower() == "name":
                continue
            d1, d2 = parse_date(first), parse_date(last)
            if not kind or not name or d1 is None or d2 is None:
                problems.append(f"Could not read the row: {line.strip()}")
                continue
            periods.append(Period(kind.strip().lower(), name.strip(), d1, d2,
                                  horizon.strip().lower() not in ("no", "n", "false")))
        return cls(periods, path, before=lines[:start], after=lines[end:],
                   problems=problems)

    @classmethod
    def from_file(cls, path: str) -> "Calendar":
        return cls.parse(Path(path).read_text(encoding="utf-8"), path=str(path))

    def table_lines(self) -> List[str]:
        rows = [HEADERS] + [p.cells() for p in self.periods]
        widths = [max(len(r[i]) for r in rows) for i in range(5)]
        out = [f"#+NAME: {TABLE_NAME}", _row_text(HEADERS, widths),
               "|" + "+".join("-" * (w + 2) for w in widths) + "|"]
        out += [_row_text(p.cells(), widths) for p in self.periods]
        return out

    def to_text(self) -> str:
        lines = self._before + self.table_lines() + self._after
        return "\n".join(lines) + "\n"

    def save(self, path: Optional[str] = None) -> str:
        target = path or self.path
        if not target:
            raise ValueError("the calendar has no file yet")
        Path(target).write_text(self.to_text(), encoding="utf-8")
        self.path = str(target)
        return self.path

    # -- reading periods -----------------------------------------------------
    def kinds(self) -> List[str]:
        out: List[str] = []
        for p in self.periods:
            if p.kind not in out:
                out.append(p.kind)
        return out

    def of_kind(self, kind: str) -> List[Period]:
        return sorted((p for p in self.periods if p.kind == kind),
                      key=lambda p: (p.start, p.end))

    def current(self, kind: str, day: _dt.date) -> Optional[Period]:
        """Return the period of ``kind`` that holds ``day``.

        In a gap between two periods, the one that ended most recently stays
        current until the next one starts. Before the first period, there is
        none.
        """
        periods = self.of_kind(kind)
        for p in periods:
            if p.holds(day):
                return p
        ended = [p for p in periods if p.end < day]
        return ended[-1] if ended else None

    def ahead(self, kind: str, day: _dt.date, count: int) -> List[Optional[Period]]:
        """Return the current period and the horizons after it, ``count`` in all.

        Only periods marked as a horizon count as steps ahead. A position past
        the last period in the file is ``None``.
        """
        now = self.current(kind, day)
        out: List[Optional[Period]] = [now]
        if now is None:
            return [None] * count
        later = [p for p in self.of_kind(kind)
                 if p.start > now.start and p.horizon]
        out += later[:count - 1]
        return out + [None] * (count - len(out))

    def find(self, kind: str, name: str) -> Optional[Period]:
        for p in self.of_kind(kind):
            if p.name == name:
                return p
        return None

    def steps_between(self, kind: str, earlier: str, later: str) -> Optional[int]:
        """Return how many horizon steps lead from period ``earlier`` to ``later``."""
        a, b = self.find(kind, earlier), self.find(kind, later)
        if a is None or b is None:
            return None
        if b.start <= a.start:
            return 0
        return len([p for p in self.of_kind(kind)
                    if a.start < p.start <= b.start and p.horizon])

    # -- checks ----------------------------------------------------------------
    def check(self) -> List[str]:
        problems = list(self.read_problems)
        seen = {}
        for p in self.periods:
            key = (p.kind, p.name)
            if key in seen:
                problems.append(f"{p.name} appears twice as a {p.kind}")
            seen[key] = p
            if p.end < p.start:
                problems.append(f"{p.name} ends before it starts")
        for kind in self.kinds():
            periods = self.of_kind(kind)
            for a, b in zip(periods, periods[1:]):
                if b.start <= a.end:
                    problems.append(f"{a.name} and {b.name} overlap")
                elif (b.start - a.end).days - 1 > GAP_DAYS:
                    problems.append(f"{(b.start - a.end).days - 1} days pass between "
                                    f"{a.name} and {b.name}")
        return problems


# -- templates ---------------------------------------------------------------
def _d(year: int, month: int, day: int) -> _dt.date:
    return _dt.date(year, month, day)


def fill_year(style: str, year: int, first_month: int = 7) -> List[Period]:
    """Return starter periods for one year in ``style``, to be adjusted by hand.

    Every style gives contiguous periods, so a break between terms counts
    toward the term it prepares for.
    """
    if style == "semesters":
        return [Period("semester", f"Spring {year}", _d(year - 1, 12, 19), _d(year, 5, 14)),
                Period("semester", f"Summer {year}", _d(year, 5, 15), _d(year, 8, 2)),
                Period("semester", f"Fall {year}", _d(year, 8, 3), _d(year, 12, 18))]
    if style == "quarters":
        return [Period("quarter", f"Winter {year}", _d(year - 1, 12, 16), _d(year, 3, 31)),
                Period("quarter", f"Spring {year}", _d(year, 4, 1), _d(year, 6, 15)),
                Period("quarter", f"Summer {year}", _d(year, 6, 16), _d(year, 9, 15)),
                Period("quarter", f"Fall {year}", _d(year, 9, 16), _d(year, 12, 15))]
    if style == "trimesters":
        return [Period("trimester", f"Fall {year}", _d(year, 8, 1), _d(year, 11, 30)),
                Period("trimester", f"Winter {year + 1}", _d(year, 12, 1), _d(year + 1, 3, 31)),
                Period("trimester", f"Spring {year + 1}", _d(year + 1, 4, 1), _d(year + 1, 7, 31))]
    if style == "calendar-quarters":
        bounds = [(1, 1, 3, 31), (4, 1, 6, 30), (7, 1, 9, 30), (10, 1, 12, 31)]
        return [Period("quarter", f"Q{i} {year}", _d(year, m1, d1), _d(year, m2, d2))
                for i, (m1, d1, m2, d2) in enumerate(bounds, start=1)]
    if style == "fiscal-year":
        if not 1 <= first_month <= 12:
            raise ValueError("the first month must be 1 to 12")
        start = _d(year - 1, first_month, 1) if first_month > 1 else _d(year, 1, 1)
        end = _d(start.year + 1, start.month, 1) - _dt.timedelta(days=1)
        return [Period("fiscal", f"FY {year}", start, end)]
    raise ValueError(f"unknown style {style!r}")


# -- finding the calendar and the week -------------------------------------------
def calendar_path(table_path: Optional[str], setting: str = "") -> Optional[Path]:
    """Return the calendar file to use: the setting, else ``periods.org`` beside the table."""
    if setting:
        return Path(setting).expanduser()
    if table_path:
        return Path(table_path).parent / FILE_NAME
    return None


def archive_path(calendar_file: Path) -> Path:
    return Path(calendar_file).parent / ARCHIVE_NAME


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
     "nov", "dec"], start=1)}
_STEM = re.compile(r"^([A-Za-z]{3,9})\.?(\d{1,2})$")


def week_date(stem: str, today: _dt.date) -> Optional[_dt.date]:
    """Read a file name such as ``Oct12`` or ``sept14`` as the date nearest ``today``.

    The name carries no year, so the year that puts the date closest to today
    is used. A canonical name such as ``gAeB-gA`` gives ``None``.
    """
    m = _STEM.match(stem)
    if not m:
        return None
    month = _MONTHS.get(m.group(1)[:3].lower())
    if month is None:
        return None
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            day = _dt.date(year, month, int(m.group(2)))
        except ValueError:
            continue
        if best is None or abs((day - today).days) < abs((best - today).days):
            best = day
    return best


# -- the completed archive -------------------------------------------------------
def archive_completed(path: Path, period: str, cells: List[str]) -> int:
    """Append completed projects under a heading for ``period`` in ``path``.

    ``cells`` are first cells in the legend's form, such as
    ``B: 1006AIrxOpt 2026-12-15 :safe:``. A project already filed under the
    period is not filed twice. Return the number of rows added.
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else [
        "#+TITLE: Completed projects", ""]
    key = "completed-" + re.sub(r"[^a-z0-9]+", "-", period.lower()).strip("-")
    name_at = None
    for index, line in enumerate(lines):
        m = _NAME_LINE.match(line)
        if m and m.group(1).lower() == key:
            name_at = index
            break
    if name_at is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", f"* {period}", f"#+NAME: {key}"]
        name_at = len(lines) - 1
    end = name_at + 1
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1
    have = {_cells(line)[0] for line in lines[name_at + 1:end]}
    new = [f"| {cell} |" for cell in cells if cell not in have]
    lines[end:end] = new
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(new)


def with_period(periods: List[Period], index: int, **changes) -> List[Period]:
    """Return ``periods`` with one period changed, for the editor."""
    out = list(periods)
    out[index] = replace(out[index], **changes)
    return out
