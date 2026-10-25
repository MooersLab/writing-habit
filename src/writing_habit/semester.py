"""Semester review: the record of a semester, ready for an annual report.

At the end of a semester, faculty are often asked what they wrote. The habit
database already holds the answer: the weeks planned and the minutes written,
the share of the plan kept month by month, the projects that took the time,
the projects completed, and the objectives met in the writer's own words. This
module gathers those facts for one semester and writes them as a short
narrative in the first person, which the writer edits and pastes into an
annual faculty report.

Run it before rolling the lists forward, while the completed list still holds
the semester's projects.

Nothing here imports Qt, and nothing here changes a file.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .name import split_deadline

#: At most this many projects and objectives are named, so the text stays short.
TOP_PROJECTS = 3
DONE_QUOTED = 3

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def _key(name: str) -> str:
    m = re.match(r"\s*(\d{4})", name or "")
    return m.group(1) if m else (name or "").strip()


def _hours(minutes: int) -> str:
    hours, rest = divmod(int(minutes), 60)
    return f"{hours} h {rest:02d} min" if hours else f"{rest} min"


def _pct(actual: int, planned: int) -> Optional[int]:
    return int(round(100 * actual / planned)) if planned else None


def _month(text: str) -> str:
    return MONTHS[int(text[5:7]) - 1]


def _series(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (", and " if len(items) > 2 else " and ") + items[-1]


@dataclass
class Semester:
    """The facts of one semester, all computed from the habit database."""

    name: str
    start: str
    end: str
    planned: int = 0
    actual: int = 0
    weeks: int = 0                   # weeks with a plan
    weeks_written: int = 0           # planned weeks with some writing
    months: List[Tuple[str, int, int]] = field(default_factory=list)
    projects: List[Tuple[str, int]] = field(default_factory=list)
    completed: List[str] = field(default_factory=list)
    committed: int = 0
    met: int = 0
    done: List[str] = field(default_factory=list)

    @property
    def kept_pct(self) -> Optional[int]:
        return _pct(self.actual, self.planned)


def gather(con, name: str, start: str, end: str,
           completed: Sequence[str] = ()) -> Optional[Semester]:
    """Collect the semester from ``start`` to ``end``, ISO dates, inclusive.

    ``completed`` are the project names on the completed list. Return ``None``
    when no week of the semester carries a plan.
    """
    s = Semester(name, start, end, completed=[split_deadline(c)[0] for c in completed])
    months: Dict[str, List[int]] = {}
    for week, planned, actual in con.execute(
            "SELECT week_start, planned_min, actual_min FROM v_week_overall"
            " WHERE week_start BETWEEN ? AND ? ORDER BY week_start", (start, end)):
        planned, actual = int(planned or 0), int(actual or 0)
        if not planned:
            continue
        s.weeks += 1
        s.weeks_written += actual > 0
        s.planned += planned
        s.actual += actual
        month = months.setdefault(week[:7], [0, 0])
        month[0] += planned
        month[1] += actual
    if not s.weeks:
        return None
    s.months = [(m, p, a) for m, (p, a) in sorted(months.items())]
    totals: Dict[str, List] = {}
    for code, description, minutes in con.execute(
            "SELECT p.code, p.description, SUM(s.actual_min) FROM session s"
            " JOIN project p ON p.project_id = s.project_id"
            " WHERE s.day BETWEEN ? AND ? GROUP BY p.project_id", (start, end)):
        project = split_deadline(description or "")[0] or code
        entry = totals.setdefault(_key(project), [project, 0])
        entry[1] += int(minutes or 0)
    s.projects = sorted(((n, m) for n, m in totals.values() if m > 0),
                        key=lambda item: (-item[1], item[0]))
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "block_objective" in have:
        committed, met = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(done), 0) FROM block_objective"
            " WHERE day BETWEEN ? AND ?", (start, end)).fetchone()
        s.committed, s.met = int(committed), int(met)
        s.done = [re.sub(r"\s+", " ", t).strip() for (t,) in con.execute(
            "SELECT text FROM block_objective WHERE done = 1 AND day BETWEEN ? AND ?"
            " ORDER BY day, start_time, position, objective_id", (start, end))]
    return s


def facts(s: Semester) -> str:
    """Write the semester as the facts the model receives."""
    lines = [f"Semester: {s.name}, {s.start} to {s.end}",
             f"Weeks with a plan: {s.weeks}",
             f"Planned weeks with some writing: {s.weeks_written}",
             f"Minutes planned: {s.planned} ({_hours(s.planned)})",
             f"Minutes written: {s.actual} ({_hours(s.actual)})",
             f"Share of the plan kept: {s.kept_pct}%"]
    for month, planned, actual in s.months:
        lines.append(f"Month {_month(month)}: {_hours(actual)} written of "
                     f"{_hours(planned)} planned, {_pct(actual, planned)}% kept")
    for project, minutes in s.projects[:TOP_PROJECTS]:
        lines.append(f"Project with the most time: {project}, {_hours(minutes)}")
    lines += [f"Project completed: {p}" for p in s.completed]
    if s.committed:
        lines += [f"Objectives committed: {s.committed}",
                  f"Objectives met: {s.met}"]
    lines += [f"Objective met: {t}" for t in s.done[:DONE_QUOTED]]
    return "\n".join(lines)


def plain(s: Semester) -> str:
    """Write the narrative without a model, in the writer's own voice."""
    time = [f"During {s.name}, I planned {_hours(s.planned)} of writing over "
            f"{s.weeks} week{'' if s.weeks == 1 else 's'} and wrote "
            f"{_hours(s.actual)}, which is {s.kept_pct}% of the plan."]
    if s.weeks_written < s.weeks:
        time.append(f"I wrote in {s.weeks_written} of those {s.weeks} weeks.")
    rated = [(m, _pct(a, p)) for m, p, a in s.months if p]
    if len(rated) >= 2:
        best = max(rated, key=lambda r: (r[1], r[0]))
        worst = min(rated, key=lambda r: (r[1], r[0]))
        if best[1] != worst[1]:
            time.append(f"The share kept was highest in {_month(best[0])}, at "
                        f"{best[1]}%, and lowest in {_month(worst[0])}, at "
                        f"{worst[1]}%.")
    work = []
    if s.projects:
        named = [f"{p} ({_hours(m)})" for p, m in s.projects[:TOP_PROJECTS]]
        work.append(f"Most of the time went to {_series(named)}.")
    if s.completed:
        work.append(f"I completed {_series(s.completed)}.")
    else:
        work.append("No project was marked completed this semester.")
    if s.committed:
        work.append(f"I met {s.met} of the {s.committed} block objectives I "
                    "committed to.")
    if s.done:
        quoted = ['"' + t.rstrip(".") + '"' for t in s.done[:DONE_QUOTED]]
        label = ("The objective I met was" if len(quoted) == 1
                 else "Objectives I met include")
        work.append(f"{label} {_series(quoted)}.")
    return "\n\n".join(" ".join(p) for p in (time, work) if p)
