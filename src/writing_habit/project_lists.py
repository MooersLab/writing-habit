"""Semester project lists kept beside the weekly table, with no Qt.

A weekly table file may carry up to nine lists of projects after the weekly
table itself: the projects finished this semester, the projects carried over
from the last period, and one list per planning horizon. The seven horizons
reach six semesters, about two years, ahead. A tenth list, the grasscatcher,
holds tasks rather than projects: the to-do items that did not make a block's objectives. Each list is its own small org table,
named by an org ``#+NAME:`` line so Emacs and this package find it the same way::

    #+NAME: current-semester-projects
    | B: 1006AIrxOpt 2026-12-15 :safe: |
    | - 1002RNAeditingR01 2027-02-05 :safe: |

A row has the same one-cell form as a legend row, so a row can be copied
between a list and the legend by hand. A project that has no code yet is
written with a dash in place of the code.

The lists sit outside the first table of the file, and the scheduler reads only
the first table, so plan import, the calendar export, and the sheets never see
them. Only the editor and ``track sync`` read them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .name import legend_activity, parse_legend_cell, split_deadline

#: (name in the file, title in the interface), in order of the horizon.
LISTS: List[Tuple[str, str]] = [
    ("current-semester-projects", "Current semester projects"),
    ("carried-over-projects", "Carried over"),
    ("completed-this-semester", "Completed this semester"),
    ("next-semester-projects", "Next semester projects"),
    ("next-next-semester-projects", "Next next semester projects"),
    ("next-next-next-semester-projects", "3*Next semester projects"),
    ("next-next-next-next-semester-projects", "4*Next semester projects"),
    ("next-next-next-next-next-semester-projects", "5*Next semester projects"),
    ("next-next-next-next-next-next-semester-projects", "6*Next semester projects"),
    ("grasscatcher", "Grasscatcher"),
]
NAMES = [name for name, _title in LISTS]
CURRENT = NAMES[0]
COMPLETED = "completed-this-semester"
CARRIED = "carried-over-projects"
#: The tasks that did not make a block's one to three objectives, kept for
#: later. A row is a task rather than a project, written ``B: find three
#: citations`` with the code of its project, or ``- tidy the bib file``.
GRASSCATCHER = "grasscatcher"
#: The lists that move one step nearer at each roll forward, nearest first.
HORIZONS = [CURRENT, "next-semester-projects", "next-next-semester-projects",
            "next-next-next-semester-projects",
            "next-next-next-next-semester-projects",
            "next-next-next-next-next-semester-projects",
            "next-next-next-next-next-next-semester-projects"]

_PERIOD_LINE = re.compile(r"^\s*#\+PROJECT_PERIOD:\s*(.*?)\s*$", re.IGNORECASE)


def list_titles(periods) -> dict:
    """Return ``{list name: title}`` from the periods of the horizons.

    ``periods`` holds the current period and those ahead, nearest first, as
    objects with a ``name``, or ``None`` past the end of the calendar. A list
    whose period is unknown keeps its plain title.
    """
    titles = dict(LISTS)
    named = dict(zip(HORIZONS, periods))
    for name, period in named.items():
        if period is not None:
            titles[name] = f"{period.name} projects"
    current = periods[0] if periods else None
    if current is not None:
        titles[COMPLETED] = f"Completed in {current.name}"
    return titles


@dataclass
class RollResult:
    """What one roll forward moved."""

    period: str
    completed: List["Entry"]
    carried: List["Entry"]

#: A table name may contain spaces, as in ``#+NAME: Fall 2026 projects``.
_NAME_LINE = re.compile(r"^\s*#\+NAME:\s*(.*?)\s*$", re.IGNORECASE)


def normalize_title(text: str) -> str:
    """Return a table name or tab title in a form two spellings can be compared in.

    Case, repeated spaces, a final colon, and a trailing count such as
    ``(26)`` or ``(1 of 3)`` are ignored, so ``Fall 2026 projects (26)`` and
    ``fall  2026 Projects`` match.
    """
    text = re.sub(r"\s*\((?:\d+(?:\s+of\s+\d+)?)\)\s*$", "", text or "")
    text = re.sub(r"\s+", " ", text).strip().rstrip(":").strip()
    return text.lower()


def default_title_map() -> dict:
    """Return ``{normalized title: list name}`` for the plain tab titles."""
    out = {normalize_title(title): name for name, title in LISTS}
    out.update({normalize_title(name): name for name in NAMES})
    out[normalize_title("Completed")] = "completed-this-semester"
    out[normalize_title("Current semester")] = "current-semester-projects"
    out[normalize_title("Next semester")] = "next-semester-projects"
    return out
_RULE = re.compile(r"^\s*\|[-+]")
_TAG_TO_RISK_TEXT = {"safe": "safe", "speculative": "risky"}


@dataclass
class Entry:
    """One project in a list. ``code`` is ``None`` while none is assigned."""

    code: Optional[str]
    description: str
    risk: Optional[str] = None          # a class name, safe or speculative
    activity: Optional[str] = None      # a default activity, or None

    @property
    def project(self) -> str:
        return split_deadline(self.description)[0]

    @property
    def deadline(self) -> Optional[str]:
        return split_deadline(self.description)[1]

    def text(self) -> str:
        """The first cell of the row, in the legend's own form."""
        head = f"{self.code}:" if self.code else "-"
        text = f"{head} {self.description.strip()}".rstrip()
        if self.activity:
            text += f" @{self.activity}"
        tag = _TAG_TO_RISK_TEXT.get(self.risk or "")
        return text + (f" :{tag}:" if tag else "")


def number_key(project: str):
    """Sort key: the project's four-digit number, with unnumbered projects last.

    The sort is stable, so projects without a number, such as ``email``, keep
    their order after the numbered ones, and so do two rows with one number.
    """
    m = re.match(r"\s*(\d{4})", project or "")
    return (0, int(m.group(1))) if m else (1, 0)


def parse_entry(cell: str) -> Optional[Entry]:
    """Read one row's first cell, or return ``None`` when it is not a project."""
    cell = (cell or "").strip()
    if not cell:
        return None
    code = None
    probe = cell
    if cell.startswith("-") and not cell.startswith("--"):
        probe = "X: " + cell[1:].strip()      # parse the rest as a legend row
    parsed = parse_legend_cell(probe)
    if parsed is None:
        return None
    letter, description, risk = parsed
    if probe is cell:
        code = letter
    return Entry(code, description, risk, legend_activity(probe))


def _cells(line: str) -> List[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return inner.split("|")


def _with_first_cell(line: str, text: str) -> str:
    """Return ``line`` with its first cell replaced, keeping the slot's width."""
    lead = line[: len(line) - len(line.lstrip())]
    cells = _cells(line)
    width = max(len(cells[0]) - 2, 0)
    cells[0] = " " + (text.ljust(width) if len(text) <= width else text) + " "
    return lead + "|" + "|".join(cells) + "|"


class ProjectLists:
    """The named lists found in ``lines``, edited in place.

    ``lines`` is the part of the file after the weekly table. The object keeps
    a reference to that list and changes it, so the owner writes the file back
    with every edit included and every other line untouched.
    """

    def __init__(self, lines: List[str]):
        self.lines = lines

    # -- finding -----------------------------------------------------------
    def _span(self, name: str) -> Optional[Tuple[int, int]]:
        """Return ``(first, end)`` line indexes of the named table, or ``None``.

        ``first`` is the first table line, and ``end`` is one past the last.
        A named list with no rows yet is the span ``(after the name, same)``.
        """
        for index, line in enumerate(self.lines):
            m = _NAME_LINE.match(line)
            if not m or normalize_title(m.group(1)) != name:
                continue
            start = index + 1
            while start < len(self.lines) and self.lines[start].lstrip().startswith("#+"):
                start += 1
            end = start
            while end < len(self.lines) and self.lines[end].lstrip().startswith("|"):
                end += 1
            return start, end
        return None

    def _name_line(self, name: str) -> Optional[int]:
        for index, line in enumerate(self.lines):
            m = _NAME_LINE.match(line)
            if m and normalize_title(m.group(1)) == name:
                return index
        return None

    def _block(self, name_line: int) -> Tuple[int, int]:
        """Return ``(first, end)`` of the lines of the table named on ``name_line``.

        ``first`` takes in one blank line before the name, so removing the
        block leaves the spacing of the file as it was.
        """
        end = name_line + 1
        while end < len(self.lines) and self.lines[end].lstrip().startswith("#+") \
                and not _NAME_LINE.match(self.lines[end]):
            end += 1
        while end < len(self.lines) and self.lines[end].lstrip().startswith("|"):
            end += 1
        first = name_line
        if first > 0 and not self.lines[first - 1].strip():
            first -= 1
        return first, end

    def tidy_names(self, titles: Optional[dict] = None) -> List[str]:
        """Give every list its standard name, and merge a list named twice.

        ``titles`` maps a normalized title, such as ``"fall 2026 projects"``,
        to the list name it stands for, such as ``current-semester-projects``.
        The plain tab titles are always understood. A list written under a tab
        title is renamed, and a second table with the same name is merged into
        the first, keeping each project once. Return one line per change, for
        the writer to read; an empty list means the file already used the
        standard names.
        """
        mapping = default_title_map()
        mapping.update(titles or {})
        notes: List[str] = []
        for index, line in enumerate(self.lines):
            m = _NAME_LINE.match(line)
            if not m:
                continue
            written = m.group(1)
            key = mapping.get(normalize_title(written))
            if key is None:
                continue
            canonical = f"#+NAME: {key}"
            if line != canonical:
                self.lines[index] = canonical
                if normalize_title(written) != key:
                    notes.append(f"Read the list “{written}” as {key}")
        for key in NAMES:
            while True:
                found = [i for i, line in enumerate(self.lines)
                         if (_NAME_LINE.match(line) and
                             normalize_title(_NAME_LINE.match(line).group(1)) == key)]
                if len(found) < 2:
                    break
                later = found[1]
                first, end = self._block(later)
                rows = [line for line in self.lines[later + 1:end]
                        if line.lstrip().startswith("|") and not _RULE.match(line)
                        and parse_entry(_cells(line)[0]) is not None]
                del self.lines[first:end]
                added = 0
                for line in rows:
                    entry = parse_entry(_cells(line)[0])
                    if self.find_project(key, entry.project) is None:
                        self.insert(key, None, entry)
                        added += 1
                notes.append(f"Merged a second {key} table into the first "
                             f"({added} project(s) added, {len(rows) - added} "
                             "already there)")
        return notes

    def present(self) -> List[str]:
        """The names of the lists the file carries, in horizon order."""
        return [name for name in NAMES if self._span(name) is not None]

    def row_indexes(self, name: str) -> List[int]:
        span = self._span(name)
        if span is None:
            return []
        return [i for i in range(*span)
                if not _RULE.match(self.lines[i])
                and parse_entry(_cells(self.lines[i])[0]) is not None]

    def entries(self, name: str) -> List[Entry]:
        return [parse_entry(_cells(self.lines[i])[0]) for i in self.row_indexes(name)]

    def find_project(self, name: str, project: str) -> Optional[int]:
        """The position of ``project`` in list ``name``, matched by name."""
        for position, entry in enumerate(self.entries(name)):
            if entry.project == project:
                return position
        return None

    # -- editing -----------------------------------------------------------
    def set_entry(self, name: str, position: int, entry: Entry) -> bool:
        index = self.row_indexes(name)[position]
        new = _with_first_cell(self.lines[index], entry.text())
        if new == self.lines[index]:
            return False
        self.lines[index] = new
        return True

    def _create(self, name: str) -> int:
        """Add an empty named list after the lists before it.  Return its row slot."""
        order = NAMES.index(name)
        at = len(self.lines)
        while at > 0 and not self.lines[at - 1].strip():
            at -= 1                       # keep trailing blank lines at the end
        earlier = [self._span(n) for n in NAMES[:order]]
        later = [self._name_line(n) for n in NAMES[order + 1:]]
        if any(span is not None for span in earlier):
            at = [span for span in earlier if span is not None][-1][1]
        elif any(index is not None for index in later):
            # Before the first later list, and before the blank line above it.
            at = min(index for index in later if index is not None)
            while at > 0 and not self.lines[at - 1].strip():
                at -= 1
        block = ["", f"#+NAME: {name}"]
        self.lines[at:at] = block
        return at + len(block)

    def insert(self, name: str, position: Optional[int], entry: Entry) -> int:
        """Insert ``entry`` before ``position``, or at the end.  Return its position."""
        rows = self.row_indexes(name)
        span = self._span(name)
        if span is None:
            at = self._create(name)
            shape = None
        else:
            at = rows[position] if position is not None and position < len(rows) else (
                rows[-1] + 1 if rows else span[1])
            shape = self.lines[rows[-1]] if rows else None
        line = _with_first_cell(shape, entry.text()) if shape else f"| {entry.text()} |"
        if shape:
            # A fresh row copies the sibling's cells but none of their values.
            cells = _cells(line)
            line = line[: len(line) - len(line.lstrip())] + "|" + "|".join(
                [cells[0]] + [" " * len(c) for c in cells[1:]]) + "|"
        self.lines.insert(at, line)
        return self.row_indexes(name).index(at)

    def remove(self, name: str, position: int) -> Entry:
        index = self.row_indexes(name)[position]
        entry = parse_entry(_cells(self.lines[index])[0])
        del self.lines[index]
        return entry

    def sort(self, name: str) -> bool:
        """Order list ``name`` by project number.  Say whether anything moved."""
        rows = self.row_indexes(name)
        lines = [self.lines[i] for i in rows]
        ordered = sorted(lines, key=lambda line: number_key(
            parse_entry(_cells(line)[0]).project))
        if ordered == lines:
            return False
        for index, line in zip(rows, ordered):
            self.lines[index] = line
        return True

    def transfer(self, source: str, position: int, target: str) -> Entry:
        """Move a project from list ``source`` to the end of list ``target``.

        A project that ``target`` already names, matched by project name, is
        not added twice, so marking a project completed a second time only
        takes it off the source list.
        """
        entry = self.remove(source, position)
        if self.find_project(target, entry.project) is None:
            self.insert(target, None, entry)
        return entry

    def reorder(self, name: str, order: List[int]) -> bool:
        """Put list ``name`` in ``order``, a permutation of its positions.

        Return whether anything moved.
        """
        rows = self.row_indexes(name)
        if sorted(order) != list(range(len(rows))):
            raise ValueError("the order must name every row of the list once")
        lines = [self.lines[i] for i in rows]
        ordered = [lines[p] for p in order]
        if ordered == lines:
            return False
        for index, line in zip(rows, ordered):
            self.lines[index] = line
        return True

    def move(self, name: str, position: int, up: bool) -> int:
        """Swap a row with its neighbour.  Return its new position."""
        rows = self.row_indexes(name)
        other = position - 1 if up else position + 1
        if not 0 <= other < len(rows):
            return position
        a, b = rows[position], rows[other]
        self.lines[a], self.lines[b] = self.lines[b], self.lines[a]
        return other


    # -- the period the lists are filed under --------------------------------
    def period(self) -> Optional[str]:
        """Return the period named by ``#+PROJECT_PERIOD:``, or ``None``."""
        for line in self.lines:
            m = _PERIOD_LINE.match(line)
            if m:
                return m.group(1) or None
        return None

    def set_period(self, period: str) -> bool:
        """Write ``#+PROJECT_PERIOD: period``.  Return whether the text changed.

        A new line goes before the first list, or at the end when there is
        none, so the lists stay together.
        """
        text = f"#+PROJECT_PERIOD: {period}"
        for index, line in enumerate(self.lines):
            if _PERIOD_LINE.match(line):
                if line == text:
                    return False
                self.lines[index] = text
                return True
        first = [self._name_line(n) for n in NAMES]
        first = [i for i in first if i is not None]
        if first:
            at = min(first)
            while at > 0 and not self.lines[at - 1].strip():
                at -= 1
            self.lines[at:at] = ["", text]
        else:
            while self.lines and not self.lines[-1].strip():
                self.lines.pop()
            self.lines += ["", text]
        return True

    def _clear(self, name: str) -> List[Entry]:
        entries = self.entries(name)
        for index in reversed(self.row_indexes(name)):
            del self.lines[index]
        return entries

    def roll_forward(self, period: str) -> RollResult:
        """Move every list one period nearer and file the lists under ``period``.

        The completed list is emptied and returned, for the archive. The
        current list goes to the Carried over list, for the writer to review.
        Each later list becomes the one before it, and the farthest list is
        left empty. Only the lists and the period line change.
        """
        completed = self._clear(COMPLETED)
        carried = self._clear(CURRENT)
        for entry in carried:
            if self.find_project(CARRIED, entry.project) is None:
                self.insert(CARRIED, None, entry)
        for near, far in zip(HORIZONS, HORIZONS[1:]):
            for entry in self._clear(far):
                self.insert(near, None, entry)
        self.set_period(period)
        return RollResult(period, completed, carried)


def after_first_table(text: str) -> List[str]:
    """The lines of ``text`` after its first org table."""
    lines = text.splitlines()
    seen = False
    for index, line in enumerate(lines):
        is_row = line.lstrip().startswith("|")
        if is_row:
            seen = True
        elif seen:
            return lines[index:]
    return []


def read_lists(path: str) -> ProjectLists:
    """Read the lists of the weekly table file at ``path``.

    Lists kept in columns are read as well as lists of one-cell rows, and a
    list named by its tab title, such as ``Completed this semester``, gets its
    standard name.
    """
    from .columns import to_one_cell
    lines, _legend, _tasks, _found = to_one_cell(
        after_first_table(Path(path).read_text(encoding="utf-8")))
    lists = ProjectLists(lines)
    lists.tidy_names()
    return lists
