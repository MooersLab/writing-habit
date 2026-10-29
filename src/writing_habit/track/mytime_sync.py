"""Synchronize actual sessions from a time-tracking SQLite database.

The source is the ``zTimeSpent`` table of ``mytime.db``, one row per timed
block with the columns ``id``, ``DateDashed``, ``Start``, ``End``,
``ProjectID``, ``ProjectDirectory``, ``Description``, and ``Activity``.

The sync reads that table directly, so no CSV file sits between the two
databases. It is idempotent. Each imported row carries the reference
``<file>:zTimeSpent:<id>`` in ``session.source_ref``, and a second run updates
a row whose times or project changed and inserts only the rows it has not seen.
A run therefore never double counts, which is the hazard of a date cutoff.

Projects. A weekly table legend names a project by a letter, for example
``Z: 1008ToolsForQCrOfRNA, submitted October 5 :safe:``, and plan import stores
the letter as the project code. The time tracker names the same project by its
number, 1008. The sync reads the legend of the table that planned the week of
each session, finds every four-digit project number in each description, and
files the session under that week's letter, so planned and actual minutes
join on the same project. A week with no imported plan borrows the legend of
the ``table`` argument, or of the nearest planned week. With ``scope="semester"``,
the default, a session whose project is on the table's current semester list but
not in the week's legend is kept as unplanned work under its directory name.
With ``scope="legend"`` a session
whose project is not in the legend is left out, because the tracker also logs
commuting and other time that is not writing. With ``scope="all"`` such a
session is kept under its project directory name as unplanned work.

Risky prospecting. A session whose project is in neither the week's legend nor
the semester lists is exploratory work on a project that has not earned a place
in the plan. Such prospecting has a high risk of being abandoned for lack of
time. With ``scope="semester"`` or ``scope="all"``, a session whose project
number falls in the writing-project ranges (``prospect_ranges``, by default
0000-1999 and 2100-5999) is kept under its directory name and flagged
``prospecting``, which labels it risky. The comparison views leave it out of
planned versus actual, and the dashboard reports it in a section of its own.
Numbers outside the ranges, such as commuting (6004) or committee work (7401),
stay out as before. A later sync clears the flag once the project is added to a
list, so the label follows the lists.

Activities. The tracker's ``Activity`` column holds a short tag. Its first
letter maps g to generative, e or r to editing, and s to support. A session
with no usable tag takes the category of a planned block for the same project
on the same day that overlaps it, and otherwise has no category.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..db import (get_category_id, get_or_create_project, has_prospecting,
                  log_import, migrate)

SOURCE_TABLE = "zTimeSpent"

#: Which projects a sync keeps. ``legend`` keeps the week's legend.
#: ``semester`` also keeps the current semester list, as unplanned work.
#: ``all`` keeps every project.
SCOPES = ("semester", "legend", "all")

#: The project-number ranges whose unlisted work counts as risky prospecting.
#: The 2000s up to 2099 hold the yearly journals, such as 2026words, and the
#: 6000s and above hold administration, service, mentoring, meetings, and
#: personal time, so none of those is prospecting.
DEFAULT_PROSPECT_RANGES = "0000-1999,2100-5999"

#: First letter of the tracker's Activity tag -> activity category.
ACTIVITY_PREFIX = {"g": "generative", "e": "editing", "r": "editing", "s": "support"}

#: A project number at the start of a legend token, for example 0104BaGquad.
PROJECT_NUMBER = re.compile(r"(?<![0-9])([0-9]{4})(?=[A-Za-z])")


@dataclass
class SyncReport:
    """What one sync read and did."""

    rows_read: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_no_time: int = 0
    skipped_no_project: int = 0
    skipped_not_in_legend: int = 0
    skipped_no_legend: int = 0
    semester_unplanned: int = 0
    prospecting: int = 0
    prospecting_minutes: Counter = field(default_factory=Counter)
    weeks_without_plan: set = field(default_factory=set)
    weeks_without_legend: set = field(default_factory=set)
    left_out_minutes: Counter = field(default_factory=Counter)

    def render(self, source: str, since: str, until: Optional[str], dry_run: bool) -> str:
        span = f"{since} to {until}" if until else f"{since} onward"
        head = "Dry run, nothing written. " if dry_run else ""
        lines = [
            f"{head}Read {self.rows_read} rows of {SOURCE_TABLE} in {source} ({span}).",
            f"  inserted {self.inserted}, updated {self.updated}, unchanged {self.unchanged}",
            f"  skipped {self.skipped_no_time} without start and end times",
            f"  skipped {self.skipped_no_project} without a project",
            f"  left out {self.skipped_not_in_legend} whose project is not in the week's legend",
        ]
        if self.semester_unplanned:
            lines.append(
                f"  kept {self.semester_unplanned} on the current semester list but not in "
                "the week's legend, as unplanned work")
        if self.prospecting:
            lines.append(
                f"  kept {self.prospecting} on no list as risky prospecting, with their minutes:")
            for name, minutes in self.prospecting_minutes.most_common(12):
                lines.append(f"    {name:<36} {minutes:>6}")
        if self.skipped_no_legend:
            weeks = ", ".join(sorted(self.weeks_without_legend))
            lines.append(
                f"  left out {self.skipped_no_legend} in weeks with no legend to read: {weeks}")
            lines.append(
                "    Import the plan for these weeks (plan import), or name a table "
                "with --table; the Track tab uses the table open in the Schedule tab.")
        if self.weeks_without_plan:
            weeks = ", ".join(sorted(self.weeks_without_plan))
            lines.append(f"  weeks with no imported plan, read with another table's legend: {weeks}")
        if self.left_out_minutes:
            lines.append("  projects left out, with their minutes:")
            for name, minutes in self.left_out_minutes.most_common(12):
                lines.append(f"    {name:<36} {minutes:>6}")
        return "\n".join(lines)


def _clock(value) -> Optional[str]:
    """Return HH:MM for a tracker time such as 3:45 or 03:45, or None."""
    text = (value or "").strip() if isinstance(value, str) else ""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 24 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _minutes(start: str, end: str) -> int:
    """Minutes from START to END, wrapping past midnight (21:00 to 00:00 is 180)."""
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    span = (eh * 60 + em) - (sh * 60 + sm)
    return span + 1440 if span < 0 else span


def parse_ranges(text: Optional[str]) -> List[Tuple[int, int]]:
    """Return ``[(low, high), ...]`` from text such as ``0000-1999,2100-5999``.

    A single number names a range of one. An empty text names no range, which
    turns the prospecting label off.
    """
    ranges: List[Tuple[int, int]] = []
    for part in (text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,4})\s*(?:-\s*(\d{1,4}))?", part)
        if not m:
            raise ValueError(f"not a project-number range: {part!r}")
        low = int(m.group(1))
        high = int(m.group(2)) if m.group(2) else low
        ranges.append((min(low, high), max(low, high)))
    return ranges


def in_ranges(number: Optional[str], ranges) -> bool:
    """Say whether the four-digit project NUMBER falls in one of RANGES."""
    if not number:
        return False
    value = int(number)
    return any(low <= value <= high for low, high in ranges)


def _monday(day: str) -> str:
    d = date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def _project_number(project_id, directory) -> Optional[str]:
    """The four-digit project number from the tracker's id or directory name."""
    if isinstance(project_id, int) or (isinstance(project_id, str) and project_id.strip().isdigit()):
        return f"{int(project_id):04d}"
    m = re.match(r"\s*(\d{4})", directory or "")
    return m.group(1) if m else None


def semester_numbers(table_path: str) -> set:
    """The project numbers of this semester's lists in a weekly table file.

    A project counts while it is on the current list, while it waits on the
    Carried over list after a roll forward, and after it moves to the
    completed list, because late work on a finished project is still writing.
    """
    from ..project_lists import CARRIED, COMPLETED, CURRENT, read_lists

    found = set()
    lists = read_lists(table_path)
    for name in (CURRENT, CARRIED, COMPLETED):
        for entry in lists.entries(name):
            found.update(PROJECT_NUMBER.findall(entry.description))
    return found


def legend_numbers(table_path: str) -> Dict[str, str]:
    """Return {project number: legend letter} from a weekly table's legend.

    A letter whose description names two projects, such as
    ``F: 4072UsersMeeting2026 Sep 16, 0382CCinJN``, claims both numbers. When a
    number appears under two letters the first letter wins, the same rule the
    plan importer follows for a letter defined twice.
    """
    from ..name import read_legend

    numbers: Dict[str, str] = {}
    for letter, (desc, _risk) in read_legend(table_path).items():
        for number in PROJECT_NUMBER.findall(desc or ""):
            numbers.setdefault(number, letter)
    return numbers


class _Legends:
    """Find the legend that governs each week, reading each table once."""

    def __init__(self, con, fallback: Optional[str]):
        self.fallback = fallback
        self.cache: Dict[str, Dict[str, str]] = {}
        self.semester_cache: Dict[str, set] = {}
        self.weeks = [
            (r["week_start"], r["table_path"])
            for r in con.execute(
                "SELECT week_start, table_path FROM plan_week"
                " WHERE table_path IS NOT NULL ORDER BY week_start"
            )
        ]

    def _read(self, path: str) -> Dict[str, str]:
        if path not in self.cache:
            self.cache[path] = legend_numbers(path) if Path(path).is_file() else {}
        self.last_path = path
        return self.cache[path]

    def semester(self) -> set:
        """Project numbers on the current semester list of the last table read."""
        path = getattr(self, "last_path", None)
        if not path or not Path(path).is_file():
            return set()
        if path not in self.semester_cache:
            self.semester_cache[path] = semester_numbers(path)
        return self.semester_cache[path]

    def for_week(self, monday: str, report: SyncReport) -> Optional[Dict[str, str]]:
        """The legend for the week of ``monday``, or ``None`` when there is none.

        The table that planned the week comes first. A week with no imported
        plan uses the ``--table`` fallback, then the nearest earlier planned
        week, then the earliest one.
        """
        exact = [p for w, p in self.weeks if w == monday]
        if exact and self._read(exact[0]):
            return self._read(exact[0])
        candidates = []
        if self.fallback:
            candidates.append(self.fallback)
        earlier = [p for w, p in self.weeks if w < monday]
        if earlier:
            candidates.append(earlier[-1])
        if self.weeks:
            candidates.append(self.weeks[0][1])
        for path in candidates:
            numbers = self._read(path)
            if numbers:
                report.weeks_without_plan.add(monday)
                return numbers
        report.weeks_without_legend.add(monday)
        return None


def _planned_category(con, day, pid, start, end) -> Optional[int]:
    row = con.execute(
        "SELECT category_id FROM plan_block WHERE day = ? AND project_id = ?"
        " AND start_time < ? AND end_time > ? ORDER BY start_time LIMIT 1",
        (day, pid, end, start),
    ).fetchone()
    return row["category_id"] if row else None


def default_since(con) -> str:
    """The first planned week, or this week's Monday when nothing is planned."""
    row = con.execute("SELECT MIN(week_start) AS w FROM plan_week").fetchone()
    return row["w"] if row and row["w"] else _monday(date.today().isoformat())


def sync_mytime(
    con,
    source: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    scope: str = "semester",
    table: Optional[str] = None,
    dry_run: bool = False,
    prospect_ranges: Optional[str] = DEFAULT_PROSPECT_RANGES,
) -> SyncReport:
    """Bring sessions from ``source`` (mytime.db) into the habit database ``con``.

    ``prospect_ranges`` names the project numbers whose work on no list is kept
    and labeled risky prospecting. An empty text turns the label off.
    """
    if scope not in SCOPES:
        raise ValueError("scope must be one of " + ", ".join(SCOPES))
    ranges = parse_ranges(prospect_ranges)
    if not dry_run:
        migrate(con)
    src_path = Path(source).expanduser()
    if not src_path.is_file():
        raise FileNotFoundError(f"no time-tracking database at {src_path}")
    since = since or default_since(con)
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    query = (
        f'SELECT id, DateDashed, Start, "End", ProjectID, ProjectDirectory,'
        f" Description, Activity FROM {SOURCE_TABLE} WHERE DateDashed >= ?"
    )
    params = [since]
    if until:
        query += " AND DateDashed <= ?"
        params.append(until)
    rows = src.execute(query + " ORDER BY DateDashed, Start", params).fetchall()
    src.close()

    legends = _Legends(con, table)
    report = SyncReport()
    has_flag = has_prospecting(con)
    ref_prefix = f"{src_path.name}:{SOURCE_TABLE}:"
    for r in rows:
        report.rows_read += 1
        day = (r["DateDashed"] or "").strip()
        start, end = _clock(r["Start"]), _clock(r["End"])
        if not day or not start or not end:
            report.skipped_no_time += 1
            continue
        minutes = _minutes(start, end)
        if minutes <= 0:
            report.skipped_no_time += 1
            continue
        number = _project_number(r["ProjectID"], r["ProjectDirectory"])
        directory = (r["ProjectDirectory"] or "").strip()
        if not number and not directory:
            report.skipped_no_project += 1
            continue

        numbers = legends.for_week(_monday(day), report)
        if numbers is None and scope != "all":
            report.skipped_no_legend += 1
            continue
        letter = (numbers or {}).get(number) if number else None
        listed = (letter is None and number is not None and numbers is not None
                  and number in legends.semester())
        on_semester = listed and scope == "semester"
        prospect = (letter is None and not listed and scope != "legend"
                    and numbers is not None and in_ranges(number, ranges))
        if on_semester:
            report.semester_unplanned += 1
        elif prospect:
            report.prospecting += 1
            report.prospecting_minutes[directory or number] += minutes
        elif letter is None and scope != "all":
            report.skipped_not_in_legend += 1
            report.left_out_minutes[directory or number] += minutes
            continue
        code = letter or directory or number

        pid = get_or_create_project(con, code, None if letter else directory or None)
        tag = (r["Activity"] or "").strip().lower()
        cat_name = ACTIVITY_PREFIX.get(tag[:1]) if tag and tag != "none" else None
        cat_id = (
            get_category_id(con, cat_name) if cat_name
            else _planned_category(con, day, pid, start, end)
        )
        note = (r["Description"] or "").strip() or None
        ref = f"{ref_prefix}{r['id']}"
        values = (day, start, end, minutes, pid, cat_id, note, int(prospect))

        # A dry run on a database made before the prospecting flag cannot
        # read the column, so it compares the other fields only.
        flag = "prospecting" if has_flag else "0"
        old = con.execute(
            "SELECT session_id, day, start_time, end_time, actual_min, project_id,"
            f" category_id, note, {flag} FROM session"
            " WHERE source = 'sqlite' AND source_ref = ?",
            (ref,),
        ).fetchone()
        if old is None:
            if not dry_run:
                con.execute(
                    "INSERT INTO session(day, start_time, end_time, actual_min,"
                    " project_id, category_id, source, source_ref, note, prospecting)"
                    " VALUES (?, ?, ?, ?, ?, ?, 'sqlite', ?, ?, ?)",
                    (*values[:6], ref, note, int(prospect)),
                )
            report.inserted += 1
        elif tuple(old)[1:] != values:
            if not dry_run:
                con.execute(
                    "UPDATE session SET day = ?, start_time = ?, end_time = ?,"
                    " actual_min = ?, project_id = ?, category_id = ?, note = ?,"
                    " prospecting = ? WHERE session_id = ?",
                    (*values, old["session_id"]),
                )
            report.updated += 1
        else:
            report.unchanged += 1

    if dry_run:
        con.rollback()
    else:
        con.commit()
        log_import(
            con, "sqlite", str(src_path), report.rows_read,
            report.inserted + report.updated, note=f"track sync since {since}",
        )
    return report
