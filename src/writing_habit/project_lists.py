"""Semester project lists kept beside the weekly table, with no Qt.

A weekly table file may carry up to six lists of projects after the weekly
table itself: the projects finished this semester, and one list per planning
horizon, which reaches about two years ahead. Each list is its own small org table,
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
    ("completed-this-semester", "Completed this semester"),
    ("next-semester-projects", "Next semester projects"),
    ("next-next-semester-projects", "Next next semester projects"),
    ("next-next-next-semester-projects", "3*Next semester projects"),
    ("next-next-next-next-semester-projects", "4*Next semester projects"),
]
NAMES = [name for name, _title in LISTS]
CURRENT = NAMES[0]
COMPLETED = "completed-this-semester"

_NAME_LINE = re.compile(r"^\s*#\+NAME:\s*(\S+)\s*$", re.IGNORECASE)
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
            if not m or m.group(1).lower() != name:
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
            if m and m.group(1).lower() == name:
                return index
        return None

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

    def move(self, name: str, position: int, up: bool) -> int:
        """Swap a row with its neighbour.  Return its new position."""
        rows = self.row_indexes(name)
        other = position - 1 if up else position + 1
        if not 0 <= other < len(rows):
            return position
        a, b = rows[position], rows[other]
        self.lines[a], self.lines[b] = self.lines[b], self.lines[a]
        return other


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
    """Read the lists of the weekly table file at ``path``."""
    return ProjectLists(after_first_table(Path(path).read_text(encoding="utf-8")))
