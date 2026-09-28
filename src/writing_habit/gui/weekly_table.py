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
from typing import Dict, List, Optional, Sequence, Tuple

from .. import name as namemod
from ..plan_import import SECTION_TO_CATEGORY

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
    """One filled cell of a block row, which is one planned writing block."""

    offset: int          # 0 is Monday
    start: str
    end: str
    letter: str
    section: str
    row: int             # index into ``WeeklyTable.rows``
    column: int          # index into the row's cells

    @property
    def category(self) -> str:
        return SECTION_TO_CATEGORY.get(
            self.section.strip().lower(), DEFAULT_CATEGORY)

    @property
    def minutes(self) -> int:
        from writing_schedule.parser import minutes_between
        return minutes_between(self.start, self.end)


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

    # -- reading -----------------------------------------------------------
    @classmethod
    def from_file(cls, path: str) -> "WeeklyTable":
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

    # -- writing -----------------------------------------------------------
    def to_text(self) -> str:
        """Return the file text.

        An untouched document returns its input byte for byte, which is the
        property the editor rests on, because a save that reformats a file the
        user did not change is a loss they cannot undo.
        """
        parts = list(self._before) + [row.raw for row in self.rows] + list(self._after)
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
        value = value.strip().upper()
        while len(row.cells) <= column_index:
            row.cells.append("")
        if row.cells[column_index] == value:
            return False
        row.cells[column_index] = value
        row.raw = self._render_cell(row, column_index)
        self.dirty = True
        return True

    def set_legend(self, row_index: int, code: str, description: str,
                   risk: Optional[str]) -> bool:
        """Rewrite one legend row.  ``risk`` is a class name, or ``None``."""
        row = self.rows[row_index]
        if row.kind != LEGEND:
            raise ValueError("not a legend row")
        code = code.strip().upper()
        description = description.strip()
        tag = RISK_TO_TAG.get(risk or "")
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

    def add_legend(self, code: str, description: str = "",
                   risk: Optional[str] = None) -> int:
        """Add a legend row for ``code`` and return its index.

        The new line copies the shape of the last legend row, so the column
        widths of the table survive. A table with no legend row yet gets a line
        as wide as its header.
        """
        code = code.strip().upper()
        tag = RISK_TO_TAG.get(risk or "")
        text = f"{code}: {description}".rstrip() + (f" :{tag}:" if tag else "")
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
        """Return the first letter that neither the legend nor the grid uses."""
        taken = set(self.legend()) | set(self.used_codes())
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if letter not in taken:
                return letter
        return ""

    def insert_legend(self, near: Optional[int], above: bool, code: str,
                      description: str = "", risk: Optional[str] = None) -> int:
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
            at = self.add_legend(code, description, risk)
        else:
            tag = RISK_TO_TAG.get(risk or "")
            text = f"{code}: {description.strip()}".rstrip() + (
                f" :{tag}:" if tag else "")
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
        if self.rows[row_index].kind != LEGEND:
            raise ValueError("not a legend row")
        del self.rows[row_index]
        self.dirty = True

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
        Path(target).write_text(self.to_text(), encoding="utf-8")
        self.path = str(target)
        self.dirty = False
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
        out: List[Block] = []
        for row_index, row in enumerate(self.rows):
            if row.kind != BLOCK:
                continue
            start, end = row.parsed
            for column_index, offset, _label in self.columns:
                text = self.cell(row_index, column_index)
                if text:
                    out.append(Block(offset, start, end, text.upper(),
                                     row.section, row_index, column_index))
        return out

    def events(self):
        """Return the blocks as scheduler ``Event`` objects, for its overlap check."""
        from writing_schedule.model import Event
        return [Event(section=b.section, offset=b.offset, start=b.start,
                      end=b.end, letter=b.letter) for b in self.blocks()]

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
        code = code.strip().upper()
        entry = self.legend().get(code)
        if entry is None:
            return None
        description, risk = entry
        name, due = split_due_date(description)
        return {"code": code, "name": name, "due": due,
                "risk": RISK_LABEL.get(risk or "")}

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
            if (b.offset, b.start, b.end, b.letter, b.section) in identities
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

        A file name gives one letter to one block, so a legend code such as
        ``EM`` cannot appear in a cell of a named table. The naming rules answer
        that with a single-letter alias, and the reason says so, because the
        writer has to choose the alias.
        """
        try:
            return self.code(), None
        except ValueError as exc:
            reason = str(exc)
            if "one uppercase letter" in reason:
                reason += (". Give that project a single-letter alias for the "
                           "file name, and keep its full code in the legend.")
            return None, reason

    def totals(self) -> Dict[str, Dict[str, int]]:
        """Return planned minutes by day label, by project, and by category."""
        by_day: Dict[str, int] = {label: 0 for label in self.day_labels}
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

    def unknown_sections(self) -> List[str]:
        """Return the section names that map to no activity category."""
        seen = []
        for row in self.rows:
            if row.kind == SECTION:
                name = str(row.parsed)
                if name.strip().lower() not in SECTION_TO_CATEGORY and name not in seen:
                    seen.append(name)
        return seen
