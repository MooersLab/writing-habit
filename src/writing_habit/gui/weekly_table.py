"""The weekly block table as an editable document, with no Qt.

The table is the one plain-text artifact both packages read, so the editor must
hold it without losing anything. The document keeps every line of the file in
order, classified by the same four row kinds the scheduler parser recognizes,
which is what lets an untouched file be written back byte for byte.

Classification follows ``writing_schedule.parser`` in both its rules and its
order, because the first match wins there and a different order here would give
the editor a different table from the one the tools read. A test asserts the
agreement over every shipped table rather than trusting the resemblance.

The module imports Qt nowhere, so its tests run wherever the package runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .. import name as namemod
from ..plan_import import SECTION_TO_CATEGORY
from ..project_lists import Entry as ListEntry, ProjectLists

#: A row of letters and spaces, with an optional trailing colon.  Mirrors the
#: section rule of the scheduler parser.
SECTION_RE = re.compile(r"^[A-Za-z][A-Za-z ]*:?$")

#: A trailing tag the risk reader did not consume, such as ``:spec:``.  The
#: reader accepts only ``safe``, ``speculative``, and the legacy ``support``, so
#: an abbreviation silently leaves the project unclassified and the barbell
#: comparison then ignores it.  Finding the shape is enough to warn.
STRAY_TAG_RE = re.compile(r"(?::([A-Za-z][A-Za-z-]*):|\(([A-Za-z][A-Za-z-]*)\))\s*$")

#: The activity a section header names, and the fallback the plan importer uses.
DEFAULT_SECTION = "Writing"
DEFAULT_CATEGORY = "generative"

#: The tag written for each risk class.  The class the database calls
#: ``speculative`` is written ``:risky:`` in a table.
RISK_TO_TAG = {"safe": "safe", "speculative": "risky"}

#: The letter each category contributes to a schedule code.
CATEGORY_LETTER = {"generative": "g", "editing": "e", "support": "s"}

#: The category each activity letter of a day cell names, as in ``gA``.
LETTER_CATEGORY = {letter: category for category, letter in CATEGORY_LETTER.items()}

#: The section name the scheduler gives each category when a cell or a legend
#: default names it, so the editor's events match the scheduler's.
CATEGORY_SECTION = {"generative": "Generative", "editing": "Rewriting",
                    "support": "Supporting"}

#: A day cell with an activity letter before the code. The letter counts only
#: when it is lowercase and the code starts with a capital, so a cell typed
#: all in lowercase, such as ``ga``, is the code GA. This is the rule of
#: ``writing_schedule.parser.split_cell``, and a test holds the two together.
CELL_RE = re.compile(r"^([ges])(" + namemod.CODE_PATTERN + r")$")

#: Where the activity of a block came from, in the order the rule tries them.
ACTIVITY_SOURCES = ("cell", "legend", "section", "none")


def split_cell(text: str) -> Tuple[Optional[str], str]:
    """Return ``(activity letter or None, CODE)`` for a day cell."""
    text = (text or "").strip()
    match = CELL_RE.match(text)
    if match:
        return match.group(1), match.group(2)
    return None, text.upper()


def normalize_cell(text: str) -> str:
    """Return the text a cell should hold for what the writer typed.

    A valid activity letter is kept and the code is raised to capitals, so
    ``gA`` stays ``gA`` and ``a`` becomes ``A``.
    """
    activity, code = split_cell(text)
    return (activity or "") + code if code else ""

#: A due date at the end of a legend description, as in
#: ``A: 1003molGraphicsR01, Sept 25 :safe:`` or ``D: 0201dusp1 September 18``.
#: A month name or any word starting with a month's first letters (so a
#: slip such as ``Ocotober`` still reads) with a day and an optional year, an
#: ISO date, or a numeric month and day. A comma or a space separates it from
#: the name, and ``due``, ``by``, or ``before`` may lead. Anything else after a
#: comma, as in ``F: 0382CCinJN, 4072UsersMeeting2026``, stays in the name.
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oc|nov|dec)[a-z]*\.?"
DUE_DATE_RE = re.compile(
    r"(?:,\s*|\s+)(?:(?:due|by|before)\s*:?\s*)?(?P<due>"
    rf"{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{4}})?"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}/\d{1,2}(?:/\d{2,4})?"
    r")\s*$",
    re.IGNORECASE)

#: The word shown for each risk class in a tooltip.
RISK_LABEL = {"safe": "safe", "speculative": "risky"}

#: The codes offered to a new project, in order. The 26 single letters come
#: first, then the ten digits ``0`` to ``9``, and then the two-letter codes
#: ``AA`` to ``ZZ``, as the columns of a spreadsheet do. The 36 one-character
#: codes are the ones a table file name can carry, so they are used up first.
#: Both readers accept a code of up to four characters, so a two-letter code
#: works in the grid and in the legend, but not in the file name.
PROJECT_CODES: Tuple[str, ...] = tuple(
    [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [str(d) for d in range(10)]
    + [chr(a) + chr(b) for a in range(ord("A"), ord("Z") + 1)
       for b in range(ord("A"), ord("Z") + 1)])


def split_due_date(description: str) -> Tuple[str, Optional[str]]:
    """Return ``(project name, due date or None)`` for a legend description.

    The date is returned as the writer typed it, because the legend gives no
    year for most entries and a guessed year would be worse than none. A bare
    trailing comma, as in ``G: 0485GUIsc,``, is dropped from the name.
    """
    text = description.strip()
    match = DUE_DATE_RE.search(text)
    if match:
        return text[:match.start()].rstrip(" ,"), match.group("due").strip()
    return text.rstrip(" ,"), None


def _to_minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def _from_minutes(total: int) -> str:
    total = max(0, min(total, 24 * 60))
    return f"{total // 60:02d}:{total % 60:02d}"


def _interval(start: str, end: str) -> Tuple[int, int]:
    """Return ``[start, end)`` in minutes, wrapping an overnight block."""
    first, last = _to_minutes(start), _to_minutes(end)
    if last <= first:
        last += 24 * 60
    return first, last


#: The picker's step and its longest block, in minutes. Two hours at most
#: forces a break every two hours, which the break check then guards across
#: blocks placed back to back.
PICK_STEP = 15
PICK_MAX = 120
#: The shortest gap that counts as a break between two blocks, in minutes.
BREAK_GAP = 15


def picker_ranges(hour: int) -> List[List[Optional[Tuple[str, str]]]]:
    """Return the 4 by 8 grid of ``(start, end)`` ranges offered for ``hour``.

    The rows are the four quarter-hour starts in the hour and the columns are
    the eight lengths from 15 to 120 minutes. A range that would run past
    midnight, or end at 24:00, is ``None``, because the picker does not place
    overnight blocks.
    """
    grid: List[List[Optional[Tuple[str, str]]]] = []
    for offset in range(0, 60, PICK_STEP):
        start = hour * 60 + offset
        row: List[Optional[Tuple[str, str]]] = []
        for length in range(PICK_STEP, PICK_MAX + 1, PICK_STEP):
            end = start + length
            row.append(None if end >= 24 * 60
                       else (_from_minutes(start), _from_minutes(end)))
        grid.append(row)
    return grid


@dataclass
class BreakRun:
    """A run of blocks on one day with no break of ``BREAK_GAP`` minutes."""

    offset: int
    start: str
    end: str
    blocks: List["Block"]

    @property
    def minutes(self) -> int:
        first, last = _interval(self.start, self.end)
        return last - first


RULE, HEADER, SECTION, BLOCK, LEGEND, OTHER = (
    "rule", "header", "section", "block", "legend", "other")


@dataclass
class Row:
    """One line of the file, classified and kept verbatim."""

    kind: str
    raw: str
    cells: List[str] = field(default_factory=list)
    #: For a block row, the parsed ``(start, end)``; for a legend row, the
    #: ``(code, description, risk)``; for a section row, the bare name.
    parsed: object = None
    #: The section a block row belongs to.
    section: str = DEFAULT_SECTION


@dataclass
class Block:
    """One filled cell of a block row, which is one planned writing block.

    The activity comes from the first of these that is present: an activity
    letter in the cell, a default activity on the code's legend entry, the
    section header above the row, and finally the generative default. The
    scheduler applies the same rule, so the editor and the tools agree.
    """

    offset: int          # 0 is Monday
    start: str
    end: str
    letter: str          # the code, without any activity letter
    section: str
    row: int             # index into ``WeeklyTable.rows``
    column: int          # index into the row's cells
    cell_activity: Optional[str] = None     # category named by the cell
    legend_activity: Optional[str] = None   # category named by the legend
    headed: bool = True  # whether a section header precedes the row

    @property
    def category(self) -> str:
        if self.cell_activity:
            return self.cell_activity
        if self.legend_activity:
            return self.legend_activity
        return SECTION_TO_CATEGORY.get(
            self.section.strip().lower(), DEFAULT_CATEGORY)

    @property
    def activity_source(self) -> str:
        """Return ``cell``, ``legend``, ``section``, or ``none``."""
        if self.cell_activity:
            return "cell"
        if self.legend_activity:
            return "legend"
        return "section" if self.headed else "none"

    @property
    def event_section(self) -> str:
        """Return the section name the scheduler gives this block."""
        if self.activity_source in ("cell", "legend"):
            return CATEGORY_SECTION[self.category]
        return self.section

    @property
    def minutes(self) -> int:
        from writing_schedule.parser import minutes_between
        return minutes_between(self.start, self.end)


#: Passed as ``activity`` to keep the legend entry's current default activity.
KEEP = object()


def legend_text(code: str, description: str, risk: Optional[str],
                activity: Optional[str] = None) -> str:
    """Return the first cell of a legend row.

    The default activity is written before the risk tag, as in
    ``E: email @support :safe:``, because both readers expect the risk tag at
    the end of the cell.
    """
    tag = RISK_TO_TAG.get(risk or "")
    text = f"{code}: {description.strip()}".rstrip()
    if activity:
        text += f" @{activity}"
    return text + (f" :{tag}:" if tag else "")


class WeeklyTable:
    """A parsed weekly table that can be written back unchanged."""

    def __init__(self, text: str, path: Optional[str] = None):
        self.path = path
        self.rows: List[Row] = []
        self.columns: List[Tuple[int, int, str]] = []   # (cell index, offset, label)
        self._before: List[str] = []
        self._after: List[str] = []
        self.dirty = False
        #: Codes whose legend row :meth:`sync_legend` added.  Only these rows
        #: are ever dropped again, so a project the writer added, or one read
        #: from the file, stays even while no cell uses it yet.
        self._synced_codes: set = set()
        self._parse(text)
        #: Whether the file keeps its legend and lists as tables in columns
        #: (Code, Project Number, Project Name, ...). Such a file is written
        #: back in columns; see :mod:`writing_habit.columns`.
        self.columnar = False
        #: ``{code: (number, name)}`` read from a grasscatcher in columns.
        self._task_projects: dict = {}
        #: ``{list name: title}`` written as each list's caption in columns.
        self.list_titles: dict = {}
        self._read_columns()
        #: What the reader changed to bring a file to the standard layout, one
        #: line each. Such a file is marked changed, so a save writes it out.
        self.layout_notes: List[str] = self._absorb_legend_table()
        #: The semester project lists that follow the week, edited in place.
        self.lists = ProjectLists(self._after)
        self._original_text = text
        self._loaded_model = self._model_text()

    # -- reading -----------------------------------------------------------
    @classmethod
    def from_file(cls, path: str) -> WeeklyTable:
        return cls(Path(path).read_text(encoding="utf-8"), path=str(path))

    def _parse(self, text: str) -> None:
        from writing_schedule.parser import day_offset, parse_time
        from writing_schedule.orgtable import split_row

        lines = text.splitlines()
        in_table = False
        done = False
        section = DEFAULT_SECTION
        for line in lines:
            is_row = line.strip().startswith("|")
            if done or not is_row:
                (self._before if not in_table else self._after).append(line)
                if in_table and is_row is False:
                    done = True
                continue
            in_table = True

            if re.match(r"^[ \t]*\|[-+]", line):
                self.rows.append(Row(RULE, line))
                continue

            cells = split_row(line)
            first = cells[0] if cells else ""

            if not self.columns and any(
                    day_offset(c) is not None for c in cells[1:]):
                for index, cell in enumerate(cells):
                    offset = day_offset(cell)
                    if offset is not None and index > 0:
                        self.columns.append((index, offset, cell))
                self.rows.append(Row(HEADER, line, cells))
                continue

            legend = namemod.parse_legend_cell(first)
            if legend is not None:
                self.rows.append(Row(LEGEND, line, cells, parsed=legend))
                continue

            times = parse_time(first) if self.columns else None
            if self.columns and times is not None:
                self.rows.append(Row(BLOCK, line, cells, parsed=times, section=section))
                continue

            if first and SECTION_RE.match(first) and parse_time(first) is None:
                section = first.replace(":", "").strip()
                self.rows.append(Row(SECTION, line, cells, parsed=section))
                continue

            self.rows.append(Row(OTHER, line, cells))

    def _read_columns(self) -> None:
        """Read the tables kept in columns into the one-cell model."""
        from .. import columns
        from writing_schedule.orgtable import split_row
        lines, legend, tasks, found = columns.to_one_cell(self._after)
        if not found:
            return
        self.columnar = True
        self._after[:] = lines
        self._task_projects = tasks
        if legend:
            if self.rows and self.rows[-1].kind != RULE:
                rule = next((r.raw for r in self.rows if r.kind == RULE), None)
                if rule is not None:
                    self.rows.append(Row(RULE, rule))
            have = set()
            for cell in legend:
                parsed = namemod.parse_legend_cell(cell)
                if parsed is None or parsed[0] in have:
                    continue
                have.add(parsed[0])
                line = f"| {cell} |"
                self.rows.append(Row(LEGEND, line, split_row(line), parsed=parsed))

    def _model_text(self) -> str:
        """Return the document in the one-cell form, the model every edit changes."""
        parts = list(self._before) + [row.raw for row in self.rows] + list(self._after)
        return "\n".join(parts) + ("\n" if parts else "")

    def _task_lookup(self) -> dict:
        """Return ``{code: (number, name)}`` for the grasscatcher's columns."""
        from ..columns import split_project
        from ..project_lists import NAMES, GRASSCATCHER
        out = dict(self._task_projects)
        sources = [(code, desc) for code, (desc, _risk) in self.legend().items()]
        for name in NAMES:
            if name != GRASSCATCHER:
                sources += [(e.code, e.description) for e in self.lists.entries(name)
                            if e.code]
        for code, desc in reversed(sources):
            out[code] = split_project(split_due_date(desc)[0])
        legend = self.legend()
        for code, (desc, _risk) in legend.items():
            out[code] = split_project(split_due_date(desc)[0])
        return out

    #: Names under which a writer may keep the week's legend as its own table.
    LEGEND_TABLE_NAMES = {"this week", "legend", "this week's legend",
                          "week legend", "key"}

    def _absorb_legend_table(self) -> List[str]:
        """Move a legend kept in its own named table back into the week.

        The scheduler, plan import, and the sheets read the legend from the
        first table of the file, below the time blocks. A file whose legend
        sits in a later table named ``This week`` would leave all of them
        without project names, so its rows are moved under the time blocks
        and the named table is removed. A code the week already defines keeps
        that definition. Return a note for each change.
        """
        from writing_schedule.orgtable import split_row
        from ..project_lists import _NAME_LINE, normalize_title

        notes: List[str] = []
        index = 0
        while index < len(self._after):
            m = _NAME_LINE.match(self._after[index])
            if not m or normalize_title(m.group(1)) not in self.LEGEND_TABLE_NAMES:
                index += 1
                continue
            written = m.group(1)
            end = index + 1
            while end < len(self._after) and self._after[end].lstrip().startswith("|"):
                end += 1
            first = index - 1 if index > 0 and not self._after[index - 1].strip() else index
            block = self._after[index + 1:end]
            del self._after[first:end]
            index = first
            have = set(self.legend())
            moved = skipped = 0
            if self.rows and self.rows[-1].kind != RULE:
                rule = next((r.raw for r in self.rows if r.kind == RULE), None)
                if rule is not None:
                    self.rows.append(Row(RULE, rule))
            for line in block:
                if re.match(r"^[ \t]*\|[-+]", line):
                    continue
                cells = split_row(line)
                parsed = namemod.parse_legend_cell(cells[0] if cells else "")
                if parsed is None:
                    continue
                if parsed[0] in have:
                    skipped += 1
                    continue
                self.rows.append(Row(LEGEND, line, cells, parsed=parsed))
                have.add(parsed[0])
                moved += 1
            note = (f"Moved the {moved} project(s) of the table “{written}” into "
                    "the week's legend, below the time blocks, where the "
                    "scheduler and plan import read it")
            if skipped:
                note += f"; {skipped} code(s) the legend already had were left out"
            notes.append(note)
            self.dirty = True
        return notes

    # -- writing -----------------------------------------------------------
    def to_text(self) -> str:
        """Return the file text.

        An untouched document returns its input byte for byte, which is the
        property the editor rests on, because a save that reformats a file the
        user did not change is a loss they cannot undo.
        """
        if not self.columnar:
            return self._model_text()
        if self._model_text() == self._loaded_model:
            return self._original_text
        from .. import columns
        from ..project_lists import LISTS
        grid = [row.raw for row in self.rows if row.kind != LEGEND]
        legend = [row.cells[0] for row in self.rows if row.kind == LEGEND]
        titles = dict(LISTS)
        titles.update(self.list_titles or {})
        after = columns.to_columns(list(self._after), legend, titles, self._task_lookup())
        parts = list(self._before) + grid + after
        return "\n".join(parts) + ("\n" if parts else "")

    # -- editing -----------------------------------------------------------
    @staticmethod
    def _fit(chunk: str, value: str) -> str:
        """Return ``chunk`` carrying ``value``, keeping the column width if it fits.

        An org table is aligned by padding, so writing a cell back into its own
        slot keeps the table aligned and keeps the change to one line. A value
        too long for its slot widens that slot alone, which leaves the table
        misaligned until the writer realigns it, and that is better than
        reflowing lines they did not touch.
        """
        width = len(chunk) - 2 if len(chunk) >= 2 else 0
        if len(value) <= width:
            return " " + value.ljust(width) + " "
        return " " + value + " "

    def _render_cell(self, row: Row, index: int) -> str:
        """Rebuild the raw line of ``row``, rewriting only cell ``index``.

        Rebuilding every cell re-justified the ones the writer did not touch.
        A table whose Time column is padded on the left, as the scheduler's own
        tables are, came back left-justified after a single edit in a day
        column, so a diff of the file showed a line the writer had not changed.
        """
        parts = row.raw.split("|")
        slot = index + 1
        if slot < len(parts):
            parts[slot] = self._fit(parts[slot], row.cells[index])
        return "|".join(parts)

    def _render(self, row: Row) -> str:
        """Rebuild every cell of ``row``, for a line this class just created."""
        parts = row.raw.split("|")
        # parts[0] is the text before the first pipe, and the cells follow.
        for index, value in enumerate(row.cells):
            slot = index + 1
            if slot < len(parts):
                parts[slot] = self._fit(parts[slot], value)
        return "|".join(parts)

    def set_cell(self, row_index: int, column_index: int, value: str) -> bool:
        """Set one cell of a block row.  Return whether anything changed."""
        row = self.rows[row_index]
        if row.kind != BLOCK:
            raise ValueError("only a time-block row holds project codes")
        value = normalize_cell(value)
        while len(row.cells) <= column_index:
            row.cells.append("")
        if row.cells[column_index] == value:
            return False
        row.cells[column_index] = value
        row.raw = self._render_cell(row, column_index)
        self.dirty = True
        return True

    def set_legend(self, row_index: int, code: str, description: str,
                   risk: Optional[str], activity=KEEP) -> bool:
        """Rewrite one legend row.  ``risk`` is a class name, or ``None``.

        ``activity`` is a default activity (``generative``, ``editing``, or
        ``support``), ``None`` to remove it, or :data:`KEEP` to keep the one
        the row already names, so an edit of the description never drops it.
        """
        row = self.rows[row_index]
        if row.kind != LEGEND:
            raise ValueError("not a legend row")
        if activity is KEEP:
            activity = namemod.legend_activity(row.cells[0] if row.cells else "")
        code = code.strip().upper()
        description = description.strip()
        tag = RISK_TO_TAG.get(risk or "")
        if activity:
            text = legend_text(code, description, risk, activity)
        else:
            text = f"{code}: {description}" + (f" :{tag}:" if tag else "")
        if row.cells and row.cells[0] == text:
            return False
        if not row.cells:
            row.cells = [text]
        else:
            row.cells[0] = text
        row.raw = self._render_cell(row, 0)
        row.parsed = namemod.parse_legend_cell(text)
        self.dirty = True
        return True

    def tidy_legend(self, reference=None, apply: bool = False):
        """Split every legend description into a project name and a deadline.

        Return one ``(document row, code, old description, project, deadline,
        dropped text)`` tuple per entry the change would rewrite. With
        ``apply`` the rows are rewritten, keeping each risk tag and default
        activity. See :func:`writing_habit.name.tidy_description` for the rule.
        """
        changes = []
        for index in self.legend_rows():
            code, description, risk = self.rows[index].parsed
            project, deadline, dropped = namemod.tidy_description(description, reference)
            new = namemod.join_deadline(project, deadline)
            if new == (description or "").strip():
                continue
            changes.append((index, code, description, project, deadline, dropped))
            if apply:
                self.set_legend(index, code, new, risk)
        return changes

    def sort_legend(self) -> bool:
        """Order the legend rows by project number.  Say whether anything moved.

        Only the legend rows trade places, so rules, the grid, and the lines
        around the table stay where they are.
        """
        from ..project_lists import number_key
        rows = self.legend_rows()
        current = [self.rows[i] for i in rows]
        ordered = sorted(current, key=lambda row: number_key(
            namemod.split_deadline(row.parsed[1])[0]))
        if ordered == current:
            return False
        for index, row in zip(rows, ordered):
            self.rows[index] = row
        self.dirty = True
        return True

    def copy_to_legend(self, entry: ListEntry) -> int:
        """Add a project from a semester list to this week's legend.

        The entry keeps its code when the legend does not use it yet, and
        otherwise takes the first free code. Return the new legend row.
        """
        for code, (description, _risk) in self.legend().items():
            if namemod.split_deadline(description)[0] == entry.project:
                raise ValueError(f"{entry.project} is already in the legend as {code}")
        code = entry.code if entry.code and entry.code not in self.legend() else (
            self.next_free_code())
        return self.add_legend(code, entry.description, entry.risk, entry.activity)

    def adopt_lists(self, other: "WeeklyTable") -> bool:
        """Give this table the semester lists of ``other``.  Say whether any came."""
        if self.lists.present() or not other.lists.present():
            return False
        while self._after and not self._after[-1].strip():
            self._after.pop()
        # The #+PROJECT_PERIOD: line sits just before the first list, and it
        # must travel with them, or the new week asks again which period its
        # lists belong to.
        start = next(i for i, line in enumerate(other._after)
                     if line.strip().upper().startswith(("#+NAME:", "#+PROJECT_PERIOD:")))
        block = list(other._after[start:])
        self._after.extend([""] + block)
        self.dirty = True
        return True

    def add_legend(self, code: str, description: str = "",
                   risk: Optional[str] = None,
                   activity: Optional[str] = None) -> int:
        """Add a legend row for ``code`` and return its index.

        The new line copies the shape of the last legend row, so the column
        widths of the table survive. A table with no legend row yet gets a line
        as wide as its header.
        """
        code = code.strip().upper()
        text = legend_text(code, description, risk, activity)
        existing = self.legend_rows()
        if existing:
            model = self.rows[existing[-1]]
            cells = [""] * max(len(model.cells), 1)
            raw = model.raw
            at = existing[-1] + 1
        else:
            width = max((len(row.cells) for row in self.rows
                         if row.kind in (HEADER, BLOCK)), default=1)
            cells = [""] * width
            raw = "|" + "|".join("   " for _ in range(width)) + "|"
            at = len(self.rows)
        cells[0] = text
        row = Row(LEGEND, raw, cells, parsed=namemod.parse_legend_cell(text))
        row.raw = self._render(row)
        self.rows.insert(at, row)
        self.dirty = True
        return at

    def next_free_code(self) -> str:
        """Return the first code that neither the legend nor the grid uses.

        The single letters are offered first. Once all 26 are taken, the
        two-letter codes follow in the order ``AA``, ``AB``, and so on to
        ``ZZ``, so a legend is no longer capped at 26 projects. An empty string
        means every one of the 702 codes is taken.
        """
        taken = set(self.legend()) | set(self.used_codes())
        for code in PROJECT_CODES:
            if code not in taken:
                return code
        return ""

    def insert_legend(self, near: Optional[int], above: bool, code: str,
                      description: str = "", risk: Optional[str] = None,
                      activity: Optional[str] = None) -> int:
        """Insert a legend row beside legend row ``near`` and return its index.

        ``near`` of ``None`` puts the row at the end of the legend, or starts a
        legend when there is none. The new line copies the width of its
        neighbour, so the rest of the file is untouched.

        Raises ``ValueError`` for a code the readers would not recognize and
        for a code the legend already defines, because the readers keep the
        first definition of a code and silently drop the second.
        """
        code = code.strip().upper()
        if namemod.parse_legend_cell(f"{code}: x") is None:
            raise ValueError(
                f"{code or 'An empty code'} is not a project code. A code is a "
                "capital letter followed by up to three capitals or digits.")
        if code in self.legend():
            raise ValueError(f"{code} is already in the legend")
        existing = self.legend_rows()
        if near is not None and near not in existing:
            raise ValueError("not a legend row")
        if near is None:
            at = self.add_legend(code, description, risk, activity)
        else:
            text = legend_text(code, description, risk, activity)
            model = self.rows[near]
            cells = [""] * max(len(model.cells), 1)
            cells[0] = text
            raw = "|".join(
                part if n == 0 or n > len(cells) else " " * max(len(part), 3)
                for n, part in enumerate(model.raw.split("|")))
            row = Row(LEGEND, raw, cells, parsed=namemod.parse_legend_cell(text))
            row.raw = self._render(row)
            at = near if above else near + 1
            self.rows.insert(at, row)
            self.dirty = True
        return at

    def remove_legend(self, row_index: int) -> None:
        """Drop one legend row from the document."""
        if not 0 <= row_index < len(self.rows) or (
                self.rows[row_index].kind != LEGEND):
            raise ValueError("not a legend row")
        code = self.rows[row_index].parsed[0]
        del self.rows[row_index]
        # A later grid edit must not treat a project the writer deleted as one
        # that sync_legend added and may drop again.
        if code not in self.legend():
            self._synced_codes.discard(code)
        self.dirty = True

    def cells_using(self, code: str) -> int:
        """Return how many grid cells hold ``code``, with or without a letter."""
        code = split_cell(code)[1]
        return sum(1 for block in self.blocks() if block.letter == code)

    # -- deleting time-block rows ------------------------------------------
    def can_remove_block(self, row_index: int) -> bool:
        """Return whether :meth:`remove_block` would delete ``row_index``.

        Only a time-block row is deleted. A section header stays, because
        deleting it would silently move every block under it into the section
        above and change the activity those blocks count toward.
        """
        return 0 <= row_index < len(self.rows) and self.rows[row_index].kind == BLOCK

    def remove_block(self, row_index: int) -> Row:
        """Delete one time-block row and return it.

        The line is removed and every other line is left untouched, so the
        saved file differs from the one on disk by exactly one line. The
        legend is not touched here. A project whose last cell went with the
        row keeps its entry, unless :meth:`sync_legend` added that entry and
        it is still blank, which is the same rule a cleared cell follows.
        """
        if not self.can_remove_block(row_index):
            raise ValueError("only a time-block row can be deleted; a section "
                             "header and the legend stay")
        row = self.rows.pop(row_index)
        self._resection()
        self.dirty = True
        return row

    # -- inserting time-block rows -----------------------------------------
    def _section_at(self, index: int) -> str:
        """Return the section a block placed at ``rows[index]`` would join."""
        for row in reversed(self.rows[:index]):
            if row.kind == SECTION:
                return str(row.parsed)
        return DEFAULT_SECTION

    def _block_model(self, near: int) -> Optional[Row]:
        """Return the block row whose shape a new row should copy.

        The nearest block row is used, so the new line matches the widths of
        the lines around it. A table with no block row yet copies its header.
        """
        blocks = self.block_rows
        if blocks:
            return self.rows[min(blocks, key=lambda i: abs(i - near))]
        for row in self.rows:
            if row.kind == HEADER:
                return row
        return None

    def suggest_times(self, near: int, above: bool) -> Tuple[str, str]:
        """Return a ``(start, end)`` that fits beside document row ``near``.

        A row inserted above a block ends where that block starts, and a row
        inserted below one starts where it ends, and either takes the length of
        its neighbour. Beside a section header the first or last block of the
        neighbouring section serves as the neighbour. The suggestion is only a
        starting value, because the writer confirms or edits the time.
        """
        blocks = self.block_rows
        anchor: Optional[int] = None
        if near in blocks:
            anchor = near
        elif above:
            before = [i for i in blocks if i < near]
            anchor, above = (before[-1], False) if before else (None, above)
        else:
            after = [i for i in blocks if i > near]
            anchor, above = (after[0], True) if after else (None, above)
        if anchor is None:
            return "09:00", "10:00"
        start, end = self.rows[anchor].parsed
        length = max(_to_minutes(end) - _to_minutes(start), 15)
        if above:
            new_end = _to_minutes(start)
            new_start = max(new_end - length, 0)
        else:
            new_start = _to_minutes(end)
            new_end = min(new_start + length, 24 * 60)
        return _from_minutes(new_start), _from_minutes(new_end)

    def insert_block(self, near: int, above: bool, start: str, end: str) -> int:
        """Insert an empty time-block row beside document row ``near``.

        Return the index of the new row. ``near`` may be a block row or a
        section row. A row inserted above a section header belongs to the
        section before it, and a row inserted below a header belongs to that
        header's section, which is how the scheduler parser will read the file.

        Every other line of the file is left untouched, so a saved table
        differs from the one on disk by exactly one added line.
        """
        from writing_schedule.parser import parse_time

        if not self.columns:
            raise ValueError("the table has no header row naming the days")
        if not 0 <= near < len(self.rows) or self.rows[near].kind not in (
                BLOCK, SECTION):
            raise ValueError("select a time block or a section row first")
        times = parse_time(f"{start}-{end}")
        if times is None:
            raise ValueError(f"not a time range: {start}-{end}")
        if _to_minutes(times[1]) <= _to_minutes(times[0]):
            raise ValueError("the block must end after it starts")

        model = self._block_model(near)
        width = max(len(model.cells) if model else 0,
                    1 + max(i for i, _o, _l in self.columns))
        cells = [""] * width
        cells[0] = f"{times[0]}-{times[1]}"
        if model is not None:
            raw = "|".join(
                part if n == 0 or n > width else " " * max(len(part), 3)
                for n, part in enumerate(model.raw.split("|")))
        else:
            raw = "|" + "|".join("   " for _ in range(width)) + "|"

        at = near if above else near + 1
        row = Row(BLOCK, raw, cells, parsed=times, section=self._section_at(at))
        row.raw = self._render_time(row, model)
        self.rows.insert(at, row)
        self.dirty = True
        return at

    # -- moving time-block rows --------------------------------------------
    def _grid_rows(self) -> List[int]:
        """Return the document rows the grid shows, section rows and blocks."""
        return [i for i, row in enumerate(self.rows) if row.kind in (SECTION, BLOCK)]

    def move_target(self, row_index: int, up: bool) -> Optional[int]:
        """Return the grid neighbour a move of ``row_index`` would pass, or ``None``.

        Only a time-block row moves. It passes the next grid row in the chosen
        direction, which is either another block of its section or the header of
        the neighbouring section. A block never moves above the first section
        header, because a block there belongs to no section, and nothing moves
        past the top or the bottom of the grid.
        """
        if not 0 <= row_index < len(self.rows) or self.rows[row_index].kind != BLOCK:
            return None
        grid = self._grid_rows()
        position = grid.index(row_index) + (-1 if up else 1)
        if not 0 <= position < len(grid):
            return None
        target = grid[position]
        if up and self.rows[target].kind == SECTION and not any(
                self.rows[i].kind == SECTION for i in grid[:position]):
            return None
        return target

    def can_move(self, row_index: int, up: bool) -> bool:
        """Return whether :meth:`move_block` would move ``row_index``."""
        return self.move_target(row_index, up) is not None

    def move_block(self, row_index: int, up: bool) -> int:
        """Move a time-block row one place up or down.  Return its new index.

        The row trades places with its neighbour in the grid. Passing another
        block keeps the row in its section and swaps two lines of the file.
        Passing a section header moves the row into the neighbouring section,
        at the bottom of the section above or the top of the section below,
        which changes the activity the block counts toward.

        The line itself is moved, not rewritten, so the saved file holds the
        same lines as before in a new order, and every cell, time, and width is
        kept exactly.
        """
        target = self.move_target(row_index, up)
        if target is None:
            if not 0 <= row_index < len(self.rows) or (
                    self.rows[row_index].kind != BLOCK):
                raise ValueError("only a time-block row can be moved")
            raise ValueError("the row is already at the "
                             + ("top" if up else "bottom") + " of the grid")
        row = self.rows.pop(row_index)
        # Moving up, the row goes into the target's slot and pushes it down.
        # Moving down, the pop has already shifted the target up by one, so
        # the target's old index is now the slot just after it.
        at = target
        self.rows.insert(at, row)
        self._resection()
        self.dirty = True
        return at

    # -- moving legend rows ------------------------------------------------
    def legend_move_target(self, row_index: int, up: bool) -> Optional[int]:
        """Return the legend row a move of ``row_index`` would pass, or ``None``.

        A legend row trades places with the legend row beside it, so it never
        leaves the legend, and nothing moves past the first or the last entry.
        """
        legend = self.legend_rows()
        if row_index not in legend:
            return None
        position = legend.index(row_index) + (-1 if up else 1)
        if not 0 <= position < len(legend):
            return None
        return legend[position]

    def can_move_legend(self, row_index: int, up: bool) -> bool:
        """Return whether :meth:`move_legend` would move ``row_index``."""
        return self.legend_move_target(row_index, up) is not None

    def move_legend(self, row_index: int, up: bool) -> int:
        """Move a legend row one place up or down.  Return its new index.

        The order of the legend is the order a writer reads the projects in,
        and it also decides which definition wins when a code is defined twice,
        because the readers keep the first. The line is moved, not rewritten,
        so a move up undoes a move down byte for byte.
        """
        target = self.legend_move_target(row_index, up)
        if target is None:
            if not 0 <= row_index < len(self.rows) or (
                    self.rows[row_index].kind != LEGEND):
                raise ValueError("only a legend row can be moved in the legend")
            raise ValueError("the project is already at the "
                             + ("top" if up else "bottom") + " of the legend")
        row = self.rows.pop(row_index)
        # The same arithmetic as move_block: the target's old index is the
        # right slot in both directions.
        self.rows.insert(target, row)
        self.dirty = True
        return target

    def _resection(self) -> None:
        """Give every block row the section of the header above it."""
        section = DEFAULT_SECTION
        for row in self.rows:
            if row.kind == SECTION:
                section = str(row.parsed)
            elif row.kind == BLOCK:
                row.section = section

    def _render_time(self, row: Row, model: Optional[Row]) -> str:
        """Write the time cell of a new row, justified as its model's is.

        The scheduler pads its Time column on the left, and a hand-written
        table usually pads it on the right, so the new line copies whichever
        the neighbouring line uses.
        """
        parts = row.raw.split("|")
        if len(parts) < 2:
            return row.raw
        right = False
        if model is not None and model.kind == BLOCK:
            slot = model.raw.split("|")[1]
            right = len(slot) - len(slot.lstrip(" ")) > 1
        width = len(parts[1]) - 2
        value = row.cells[0]
        if len(value) <= width:
            text = value.rjust(width) if right else value.ljust(width)
            parts[1] = " " + text + " "
        else:
            parts[1] = " " + value + " "
        return "|".join(parts)

    def rows_clear_of(self, row_index: int) -> List[int]:
        """Return the block rows whose time range does not overlap ``row_index``.

        The rule is the scheduler's own, so this agrees with the Clashes panel.
        Each range is a half-open interval ``[start, end)``, so two blocks that
        only touch, such as 04:00-05:30 and 05:30-07:00, do not overlap. A range
        whose end is not after its start runs past midnight. The row itself is
        left out, because a block always overlaps itself.
        """
        row = self.rows[row_index]
        if row.kind != BLOCK:
            raise ValueError("only a time-block row has a time range")
        start, end = _interval(*row.parsed)
        clear = []
        for index in self.block_rows:
            if index == row_index:
                continue
            other_start, other_end = _interval(*self.rows[index].parsed)
            if not (start < other_end and other_start < end):
                clear.append(index)
        return clear

    def used_codes(self) -> List[str]:
        """Return the project codes the grid uses, in first-appearance order."""
        out: List[str] = []
        for block in self.blocks():
            if block.letter and block.letter not in out:
                out.append(block.letter)
        return out

    def sync_legend(self) -> bool:
        """Make the legend cover the codes the grid uses.  Return whether it changed.

        A code typed into a cell gains a legend row, because a code with no
        description reaches the database with no project name and no risk class.
        A row whose code has left the grid is dropped only when this method
        added it and it is still blank, which is the state an added row is born
        in. A description the writer typed is never thrown away by a keystroke
        in the grid, and neither is a project the writer inserted or one the
        file already held.
        """
        used = self.used_codes()
        defined = self.legend()
        changed = False
        for code in used:
            if code not in defined:
                self.add_legend(code)
                self._synced_codes.add(code)
                changed = True
        for index in reversed(self.legend_rows()):
            code, description, risk = self.rows[index].parsed
            if (code not in used and not description and risk is None
                    and code in self._synced_codes):
                self.remove_legend(index)
                self._synced_codes.discard(code)
                changed = True
        return changed

    def legend_blocks(self) -> List[List[int]]:
        """Return the legend rows grouped by the rules between them.

        A table in the older layout kept the semester lists inside the week's
        legend, one block after another with a rule between them, so every
        project of every semester read as a project of the week.
        """
        from ..project_lists import parse_entry
        blocks: List[List[int]] = []
        current: List[int] = []
        seen_legend = False
        for index, row in enumerate(self.rows):
            # A row such as "- 1452PHFSboXt 2027-03-01" has no code yet, so it
            # is not a legend row, but it belongs to its block all the same.
            listed = (row.kind == OTHER and seen_legend and row.cells
                      and parse_entry(row.cells[0]) is not None)
            if row.kind == LEGEND or listed:
                current.append(index)
                seen_legend = True
            elif row.kind == RULE and seen_legend and current:
                blocks.append(current)
                current = []
        if current:
            blocks.append(current)
        return blocks

    def split_legend_blocks(self) -> List[Tuple[str, int]]:
        """Move every legend block after the first into the semester lists.

        The second block goes to the current semester's list, the third to
        the next semester's, and so on, as the older layout kept them. A
        project already on a list is not added twice. The rules between the
        blocks go too. Return ``(list name, projects added)`` for each block.
        """
        from ..project_lists import HORIZONS, parse_entry
        blocks = self.legend_blocks()
        if len(blocks) < 2:
            return []
        out: List[Tuple[str, int]] = []
        drop = set()
        for target, block in zip(HORIZONS, blocks[1:]):
            added = 0
            for index in block:
                entry = parse_entry(self.rows[index].cells[0])
                if self.lists.find_project(target, entry.project) is None:
                    self.lists.insert(target, None, entry)
                    added += 1
                drop.add(index)
            out.append((target, added))
        extra = blocks[len(HORIZONS) + 1:]
        if extra:
            raise ValueError(f"the legend has {len(blocks)} blocks, more than the "
                             f"{len(HORIZONS)} semester lists can take")
        first_block_end = blocks[0][-1]
        for index in range(first_block_end + 1, blocks[-1][-1] + 1):
            if self.rows[index].kind == RULE:
                drop.add(index)
        self.rows = [row for i, row in enumerate(self.rows) if i not in drop]
        self.dirty = True
        return out

    def legend_rows(self) -> List[int]:
        """Return the indexes of the legend rows, in file order."""
        return [i for i, row in enumerate(self.rows) if row.kind == LEGEND]

    def rename_to_canonical(self) -> str:
        """Move the file to its canonical name and return the new path.

        The tracker groups weeks by the code stored at plan import, and that
        code comes from the file name, so a table whose name has drifted from
        its grid is filed under the wrong shape. Renaming is therefore a real
        correction rather than tidying.

        Raises ``ValueError`` when the week has no canonical name, when the
        document has unsaved edits, when it came from no file, or when a
        different file already holds the target name.
        """
        if self.dirty:
            raise ValueError("save the table before renaming it")
        if not self.path:
            raise ValueError("this table has never been saved")
        code, problem = self.code_or_problem()
        if code is None:
            raise ValueError(problem)
        source = Path(self.path)
        target = source.with_name(f"{code}.org")
        if target == source:
            return self.path
        if target.exists():
            raise ValueError(f"{target.name} already exists")
        source.rename(target)
        self.path = str(target)
        return self.path

    def name_matches_code(self) -> bool:
        """Return whether the file name is the canonical name of the grid."""
        code, _problem = self.code_or_problem()
        if code is None or not self.path:
            return False
        return Path(self.path).stem == code

    def save(self, path: Optional[str] = None) -> str:
        """Write the document and return the path written."""
        target = path or self.path
        if not target:
            raise ValueError("no path to save to")
        text = self.to_text()
        Path(target).write_text(text, encoding="utf-8")
        self.path = str(target)
        self.dirty = False
        self._original_text = text
        self._loaded_model = self._model_text()
        return self.path

    # -- content -----------------------------------------------------------
    @property
    def day_labels(self) -> List[str]:
        return [label for _index, _offset, label in self.columns]

    @property
    def block_rows(self) -> List[int]:
        return [i for i, row in enumerate(self.rows) if row.kind == BLOCK]

    def cell(self, row_index: int, column_index: int) -> str:
        cells = self.rows[row_index].cells
        return cells[column_index] if column_index < len(cells) else ""

    def blocks(self) -> List[Block]:
        """Return every filled block, in file order."""
        defaults = self.legend_defaults()
        out: List[Block] = []
        headed = False
        for row_index, row in enumerate(self.rows):
            if row.kind == SECTION:
                headed = True
            if row.kind != BLOCK:
                continue
            start, end = row.parsed
            for column_index, offset, _label in self.columns:
                text = self.cell(row_index, column_index)
                if text:
                    letter, code = split_cell(text)
                    out.append(Block(offset, start, end, code,
                                     row.section, row_index, column_index,
                                     cell_activity=LETTER_CATEGORY.get(letter or ""),
                                     legend_activity=defaults.get(code),
                                     headed=headed))
        return out

    def events(self):
        """Return the blocks as scheduler ``Event`` objects, for its overlap check."""
        from writing_schedule.model import Event
        return [Event(section=b.event_section, offset=b.offset, start=b.start,
                      end=b.end, letter=b.letter,
                      activity=CATEGORY_LETTER.get(b.cell_activity or ""))
                for b in self.blocks()]

    def legend_defaults(self) -> Dict[str, str]:
        """Return ``{code: activity}`` for every legend entry that names one.

        A code defined twice takes the activity of its first definition, as
        the readers keep the first definition of everything else.
        """
        out: Dict[str, str] = {}
        seen: set = set()
        for row in self.rows:
            if row.kind != LEGEND:
                continue
            code = row.parsed[0]
            if code in seen:
                continue
            seen.add(code)
            activity = namemod.legend_activity(row.cells[0] if row.cells else "")
            if activity:
                out[code] = activity
        return out

    def activity_fallbacks(self) -> List[Block]:
        """Return the blocks whose activity fell through to the default.

        Such a block has no activity letter, no legend default, and no section
        header above it, so the plan importer counts it as generative.
        """
        return [b for b in self.blocks() if b.activity_source == "none"]

    def prefix_overrides(self) -> List[Block]:
        """Return the blocks whose activity letter differs from their section."""
        out = []
        for b in self.blocks():
            if b.activity_source != "cell" or not b.headed:
                continue
            section = SECTION_TO_CATEGORY.get(b.section.strip().lower(),
                                              DEFAULT_CATEGORY)
            if section != b.cell_activity:
                out.append(b)
        return out

    # -- moving the activity into the cells --------------------------------
    def move_activities_into_cells(self) -> int:
        """Write the section's activity letter into every bare cell under it.

        Only a cell whose activity comes from its section header gains a
        letter. A cell that already has one keeps it, and a cell whose project
        names a default activity in the legend is left bare, because that
        default still applies once the headers are gone. Return the number of
        cells changed. Each changed cell rewrites only its own line.
        """
        changed = 0
        for block in self.blocks():
            if block.activity_source != "section":
                continue
            value = CATEGORY_LETTER[block.category] + block.letter
            if self.set_cell(block.row, block.column, value):
                changed += 1
        return changed

    def remove_section_rows(self) -> int:
        """Delete every section header row and return how many went.

        Call this after :meth:`move_activities_into_cells`, so no block loses
        its activity. The blocks then belong to the default section.
        """
        before = len(self.rows)
        self.rows = [row for row in self.rows if row.kind != SECTION]
        removed = before - len(self.rows)
        if removed:
            self._resection()
            self.dirty = True
        return removed

    def legend(self) -> Dict[str, Tuple[str, Optional[str]]]:
        """Return ``{code: (description, risk_class)}`` in first-appearance order."""
        out: Dict[str, Tuple[str, Optional[str]]] = {}
        for row in self.rows:
            if row.kind == LEGEND:
                code, desc, risk = row.parsed
                out.setdefault(code, (desc, risk))
        return out

    def project_info(self, code: str) -> Optional[Dict[str, Optional[str]]]:
        """Return the name, due date, and risk label of ``code``, or ``None``.

        This is what a cell explains about itself when the pointer rests on it,
        so a writer can read the grid without looking down at the key.
        """
        code = split_cell(code)[1]
        entry = self.legend().get(code)
        if entry is None:
            return None
        description, risk = entry
        name, due = split_due_date(description)
        return {"code": code, "name": name, "due": due,
                "risk": RISK_LABEL.get(risk or ""),
                "activity": self.legend_defaults().get(code)}

    # -- derived readings --------------------------------------------------
    def overlaps(self):
        """Return the clashing pairs, using the scheduler's own rule."""
        from writing_schedule.overlap import find_overlaps
        return find_overlaps(self.events())

    def conflicting_cells(self) -> set:
        """Return ``{(row, column)}`` for every block that takes part in a clash."""
        from writing_schedule.overlap import conflicting_identities
        identities = conflicting_identities(self.events())
        return {
            (b.row, b.column) for b in self.blocks()
            if (b.offset, b.start, b.end, b.letter, b.event_section) in identities
        }

    def week(self) -> List[List[Tuple[str, str]]]:
        """Return the week as :func:`writing_habit.name.encode` expects it.

        Each day holds its blocks in time order, and each block is the pair of
        the activity category and the project letter.
        """
        last = max((offset for _i, offset, _l in self.columns), default=-1)
        days: List[List[Tuple[str, str]]] = [[] for _ in range(last + 1)]
        for block in sorted(self.blocks(), key=lambda b: (b.offset, b.start)):
            days[block.offset].append((block.category, block.letter))
        return days

    def code(self) -> str:
        """Return the canonical schedule code for the current grid.

        Raises ``ValueError`` when the grid cannot be named, which happens when
        a cell holds a project code of more than one letter.
        """
        return namemod.encode(self.week())

    def code_or_problem(self) -> Tuple[Optional[str], Optional[str]]:
        """Return ``(code, None)``, or ``(None, reason)`` when the week has no name.

        A file name gives one character, a letter or a digit, to one block, so a
        legend code such as
        ``EM`` cannot appear in a cell of a named table. The naming rules answer
        that with a one-character alias, and the reason says so, because the
        writer has to choose the alias.
        """
        try:
            return self.code(), None
        except ValueError as exc:
            reason = str(exc)
            if "one uppercase letter" in reason:
                reason += (". Give that project a one-character alias, a letter "
                           "or a digit, for the file name, and keep its full code "
                           "in the legend.")
            return None, reason

    def totals(self) -> Dict[str, Dict[str, int]]:
        """Return planned minutes by day label, by project, and by category."""
        by_day: Dict[str, int] = dict.fromkeys(self.day_labels, 0)
        by_project: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        labels = {offset: label for _i, offset, label in self.columns}
        for block in self.blocks():
            minutes = block.minutes
            by_day[labels[block.offset]] = by_day.get(labels[block.offset], 0) + minutes
            by_project[block.letter] = by_project.get(block.letter, 0) + minutes
            by_category[block.category] = by_category.get(block.category, 0) + minutes
        return {"day": by_day, "project": by_project, "category": by_category}

    def legend_check(self):
        """Return the rows and problems of the project-letter check."""
        decoded = list(zip(namemod.DAYS, self.week()))
        return namemod.check_against_legend(decoded, self.legend())

    def duplicate_legend_codes(self) -> Dict[str, List[str]]:
        """Return ``{code: [description, ...]}`` for a code defined more than once.

        The readers keep the first definition and drop the rest without a word,
        so a table that defines ``H`` twice quietly loses one project. The panel
        says which code and which descriptions, because only the writer knows
        which one was meant.
        """
        seen: Dict[str, List[str]] = {}
        for row in self.rows:
            if row.kind == LEGEND:
                code, desc, _risk = row.parsed
                seen.setdefault(code, []).append(desc)
        return {code: descs for code, descs in seen.items() if len(descs) > 1}

    def stray_risk_tags(self) -> List[Tuple[str, str]]:
        """Return ``(code, tag)`` for a legend entry whose risk tag was not read.

        Only ``safe`` and ``speculative`` name a risk class, so an abbreviation
        such as ``:spec:`` stays in the description and the project ends up with
        no class at all. The barbell comparison then leaves it out.
        """
        out: List[Tuple[str, str]] = []
        for code, (desc, risk) in self.legend().items():
            if risk is not None:
                continue
            match = STRAY_TAG_RE.search(desc)
            if match:
                out.append((code, match.group(1) or match.group(2)))
        return out

    # -- the hour view ------------------------------------------------------
    def column_for(self, offset: int) -> int:
        """Return the cell index of the day column for ``offset`` (0 is Monday)."""
        for index, day, _label in self.columns:
            if day == offset:
                return index
        raise ValueError(f"the table has no column for day {offset}")

    def find_block_row(self, start: str, end: str) -> Optional[int]:
        """Return the first time-block row for exactly ``start``-``end``, or ``None``."""
        for index in self.block_rows:
            if tuple(self.rows[index].parsed) == (start, end):
                return index
        return None

    def ensure_block_row(self, start: str, end: str) -> Tuple[int, bool]:
        """Return the row for ``start``-``end``, inserting it if needed.

        The second value says whether a row was inserted. A new row goes after
        the last block row whose range sorts before it, or above the first
        block row when none does, so a sorted table stays sorted. Only that one
        line is added to the file.
        """
        found = self.find_block_row(start, end)
        if found is not None:
            return found, False
        blocks = self.block_rows
        if not blocks:
            raise ValueError("the table has no time-block row to place a new "
                             "row beside")
        key = (_interval(start, end))
        before = [i for i in blocks if _interval(*self.rows[i].parsed) <= key]
        if before:
            near = max(before, key=lambda i: (_interval(*self.rows[i].parsed), i))
            return self.insert_block(near, above=False, start=start, end=end), True
        near = min(blocks, key=lambda i: (_interval(*self.rows[i].parsed), i))
        return self.insert_block(near, above=True, start=start, end=end), True

    def place_block(self, offset: int, start: str, end: str,
                    value: str, push: bool = False) -> Tuple[int, bool]:
        """Write ``value`` (such as ``gA``) for day ``offset`` at ``start``-``end``.

        Return ``(row, inserted)``. The value should carry its activity letter,
        so a row inserted under a section header keeps the activity the writer
        chose. The range must be within the picker's limits. With ``push``,
        the later blocks of that day that the new block would overlap move
        down first, as :meth:`plan_push` describes.
        """
        first, last = _interval(start, end)
        if _to_minutes(end) <= _to_minutes(start):
            raise ValueError("the block must end after it starts, on the same day")
        if last - first > PICK_MAX:
            raise ValueError(f"a block is at most {PICK_MAX} minutes long")
        if not split_cell(value)[1]:
            raise ValueError("choose a project code")
        column = self.column_for(offset)
        if push:
            moves = self.plan_push(offset, start, end)
            if moves:
                self._check_targets(moves)
                self.apply_moves(moves)
        row, inserted = self.ensure_block_row(start, end)
        self.set_cell(row, column, value)
        return row, inserted

    def clear_block(self, row_index: int, column_index: int) -> bool:
        """Empty one cell and keep its row.  Return whether it changed."""
        return self.set_cell(row_index, column_index, "")

    # -- shifting blocks in time ---------------------------------------------
    def block_at(self, row_index: int, column_index: int) -> Optional[Block]:
        """Return the block in one cell, or ``None`` when the cell is empty."""
        for block in self.blocks():
            if (block.row, block.column) == (row_index, column_index):
                return block
        return None

    def _cell_value(self, block: Block) -> str:
        """Return the cell text that keeps ``block``'s activity wherever it goes.

        An activity that came from the section header would change when the
        block lands under another header, so it is written into the cell.
        """
        value = self.cell(block.row, block.column)
        if block.activity_source in ("section", "none"):
            letter = CATEGORY_LETTER.get(block.category, "")
            value = letter + block.letter
        return value

    def swap_blocks(self, first: Block, second: Block) -> None:
        """Exchange the work of two blocks, keeping each block's time.

        Each cell keeps its activity wherever it goes, so a block whose activity
        came from its section header carries the letter with it.
        """
        one, two = self._cell_value(first), self._cell_value(second)
        self.set_cell(first.row, first.column, two)
        self.set_cell(second.row, second.column, one)

    def give_block(self, block: Block, code: str) -> None:
        """Give ``block``'s time to project ``code``, keeping the block's activity."""
        self.set_cell(block.row, block.column,
                      CATEGORY_LETTER.get(block.category, "") + code)

    def plan_push(self, offset: int, start: str, end: str,
                  exclude=()) -> List[Tuple[Block, str, str]]:
        """Return the later blocks that ``start``-``end`` would push down.

        A block on day ``offset`` that starts at or after ``start`` and
        overlaps the range moves down to start where the range ends, keeping
        its length. The block after it moves on the same terms against the
        new end, and the chain stops at the first block that is clear, so a
        gap the writer left later in the day stays. Blocks that start before
        ``start`` never move, so an overlap with one of them stays a clash.
        ``exclude`` holds the ``(row, column)`` cells to leave out, such as
        the block being shifted. Raise :class:`ValueError` when a push would
        run past midnight.
        """
        first, chain_end = _interval(start, end)
        skip = set(exclude)
        later = sorted(
            (b for b in self.blocks()
             if b.offset == offset and (b.row, b.column) not in skip
             and _to_minutes(b.start) >= first),
            key=lambda b: (_interval(b.start, b.end), b.row))
        moves: List[Tuple[Block, str, str]] = []
        for block in later:
            b_first, b_last = _interval(block.start, block.end)
            if b_first >= chain_end:
                break
            length = b_last - b_first
            new_first, new_last = chain_end, chain_end + length
            if new_last > 24 * 60:
                raise ValueError(
                    f"pushing {block.letter} {block.start}-{block.end} down "
                    "would run past midnight")
            moves.append((block, _from_minutes(new_first), _from_minutes(new_last)))
            chain_end = new_last
        return moves

    def plan_shift(self, row_index: int, column_index: int, delta: int,
                   push: bool = True) -> List[Tuple[Block, str, str]]:
        """Return the moves a shift of ``delta`` minutes would make.

        The first move is the shifted block itself. With ``push``, the later
        blocks it would overlap follow, as :meth:`plan_push` finds them.
        Raise :class:`ValueError` when the cell is empty, the block runs
        overnight, the shift leaves the day, or a move lands on a slot that
        another block already holds.
        """
        block = self.block_at(row_index, column_index)
        if block is None:
            raise ValueError("select a block to shift")
        if _to_minutes(block.end) <= _to_minutes(block.start):
            raise ValueError("a block that runs past midnight cannot be shifted")
        first, last = _interval(block.start, block.end)
        new_first, new_last = first + delta, last + delta
        if new_first < 0:
            raise ValueError("the block would start before midnight of the "
                             "previous day")
        if new_last > 24 * 60:
            raise ValueError("the block would run past midnight")
        start, end = _from_minutes(new_first), _from_minutes(new_last)
        moves = [(block, start, end)]
        if push:
            moves += self.plan_push(block.offset, start, end,
                                    exclude={(row_index, column_index)})
        self._check_targets(moves)
        return moves

    def _check_targets(self, moves) -> None:
        """Refuse moves that would land on a cell a staying block holds."""
        moving = {(b.row, b.column) for b, _s, _e in moves}
        for block, start, end in moves:
            row = self.find_block_row(start, end)
            if row is None or (row, block.column) in moving:
                continue
            if self.cell(row, block.column):
                raise ValueError(
                    f"{start}-{end} on that day already holds "
                    f"{self.cell(row, block.column)}")

    def apply_moves(self, moves) -> List[Tuple[int, int]]:
        """Carry out ``moves`` and return the new ``(row, column)`` of each.

        Every old cell is emptied before any new one is written, so a chain
        of blocks can move down into each other's slots. Rows are kept, as
        :meth:`clear_block` keeps them, and a range the file lacks gets its
        row in start-time order.
        """
        values = [self._cell_value(block) for block, _s, _e in moves]
        for block, _start, _end in moves:
            self.set_cell(block.row, block.column, "")
        placed: List[Tuple[str, str, int, str]] = []
        for (block, start, end), value in zip(moves, values):
            row, _inserted = self.ensure_block_row(start, end)
            self.set_cell(row, block.column, value)
            placed.append((start, end, block.column, value))
        # Inserting a row moves the rows below it, so look every cell up again.
        return [(self.find_block_row(start, end), column)
                for start, end, column, _value in placed]

    def shift_block(self, row_index: int, column_index: int, delta: int,
                    push: bool = True) -> Tuple[Tuple[int, int], list]:
        """Move one block ``delta`` minutes, later when positive.

        Return the block's new ``(row, column)`` and the moves made, as
        :meth:`plan_shift` describes them. Nothing changes when the shift is
        refused with :class:`ValueError`.
        """
        moves = self.plan_shift(row_index, column_index, delta, push=push)
        cells = self.apply_moves(moves)
        return cells[0], moves

    def hour_blocks(self) -> Dict[Tuple[int, int], List[Block]]:
        """Return ``{(offset, hour): blocks starting in that hour}``, by start."""
        out: Dict[Tuple[int, int], List[Block]] = {}
        for block in sorted(self.blocks(), key=lambda b: (b.start, b.end, b.row)):
            hour = _to_minutes(block.start) // 60
            out.setdefault((block.offset, hour), []).append(block)
        return out

    def hour_spans(self) -> Dict[Tuple[int, int], List[Block]]:
        """Return ``{(offset, hour): blocks that started earlier and run into it}``.

        These are the hours the hour view shades as the continuation of a
        longer block. A block that only touches the hour, such as one ending
        at 10:00 for the 10 o'clock hour, does not run into it.
        """
        out: Dict[Tuple[int, int], List[Block]] = {}
        for block in sorted(self.blocks(), key=lambda b: (b.start, b.end, b.row)):
            first, last = _interval(block.start, block.end)
            last = min(last, 24 * 60)
            for hour in range(first // 60 + 1, 24):
                if hour * 60 >= last:
                    break
                out.setdefault((block.offset, hour), []).append(block)
        return out

    def break_runs(self, longest: int = PICK_MAX,
                   gap: int = BREAK_GAP) -> List[BreakRun]:
        """Return the runs of blocks that go more than ``longest`` minutes without a break.

        On each day the blocks are sorted by start and joined into a run while
        the next block starts less than ``gap`` minutes after the run ends, so
        touching and overlapping blocks join too. A run whose span from its
        first start to its last end exceeds ``longest`` is returned.
        """
        by_day: Dict[int, List[Block]] = {}
        for block in self.blocks():
            by_day.setdefault(block.offset, []).append(block)
        runs: List[BreakRun] = []
        for offset in sorted(by_day):
            ordered = sorted(by_day[offset],
                             key=lambda b: (_interval(b.start, b.end), b.row))
            current: List[Block] = []
            run_start = run_end = 0
            for block in ordered + [None]:
                if block is not None:
                    first, last = _interval(block.start, block.end)
                    if current and first - run_end < gap:
                        current.append(block)
                        run_end = max(run_end, last)
                        continue
                if current and run_end - run_start > longest:
                    runs.append(BreakRun(offset, _from_minutes(run_start),
                                         _from_minutes(run_end), current))
                if block is not None:
                    current, run_start, run_end = [block], first, last
        return runs

    def break_cells(self) -> set:
        """Return ``{(row, column)}`` for every block in a run with no break."""
        return {(b.row, b.column) for run in self.break_runs() for b in run.blocks}

    def unused_block_rows(self) -> List[int]:
        """Return the time-block rows whose day cells are all empty."""
        used = {b.row for b in self.blocks()}
        return [i for i in self.block_rows if i not in used]

    def drop_unused_block_rows(self) -> int:
        """Delete every time-block row with no filled cell.  Return how many went.

        Section headers, the legend, and every filled row stay, so the week's
        plan and its canonical name do not change.
        """
        drop = set(self.unused_block_rows())
        if not drop:
            return 0
        self.rows = [row for i, row in enumerate(self.rows) if i not in drop]
        self._resection()
        self.dirty = True
        return len(drop)

    def unknown_sections(self) -> List[str]:
        """Return the section names that map to no activity category."""
        seen = []
        for row in self.rows:
            if row.kind == SECTION:
                name = str(row.parsed)
                if name.strip().lower() not in SECTION_TO_CATEGORY and name not in seen:
                    seen.append(name)
        return seen
