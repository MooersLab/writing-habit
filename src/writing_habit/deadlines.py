"""Deadline coverage: projects due soon that have no time left this week.

A plan can look full and still leave out the project whose deadline is
nearest. This module finds every project with a deadline inside a horizon,
three to four weeks by default, checks how much of this week's remaining plan
goes to it, and proposes one block to give each project that has none.

The projects come from the week's legend and from the semester project lists,
so a project that waits on a list with a near deadline is found too. A
proposal takes a block that is still ahead this week from a project with no
near deadline, keeps the block's time and its activity, and gives it to the
project at risk. Blocks of projects that are due soon are never taken.

Nothing here imports Qt, and nothing here changes a file. The editor applies
the proposals the writer accepts.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .name import split_deadline

#: Days ahead of today that count as soon, by default.
HORIZON_DAYS = 28

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


@dataclass
class Project:
    """A project with an ISO deadline, from the legend or from a list."""

    name: str
    deadline: _dt.date
    code: Optional[str] = None       # the legend code, or the list's code
    in_legend: bool = False
    source: str = "legend"           # "legend" or the name of a list
    description: str = ""


@dataclass
class Slot:
    """One planned block of the open week."""

    offset: int                      # 0 is Monday
    start: str
    end: str
    code: str
    category: str
    minutes: int
    row: int = -1
    column: int = -1

    def label(self) -> str:
        return f"{DAY_NAMES[self.offset]} {self.start}-{self.end}"


@dataclass
class Risk:
    """A project due soon with no block left this week, and the block proposed."""

    project: Project
    days_left: int
    planned_min: int                 # all of this week's minutes for it
    ahead_min: int                   # the minutes still ahead this week
    donor: Optional[Slot] = None
    donor_name: str = ""
    donor_deadline: Optional[_dt.date] = None
    donor_keeps: int = 0             # minutes the donor keeps ahead after the gift


@dataclass
class Coverage:
    """The result of a check: projects at risk and projects already covered."""

    today: _dt.date
    horizon: int
    risks: List[Risk] = field(default_factory=list)
    covered: List[Tuple[Project, int, int]] = field(default_factory=list)


def _iso(text: Optional[str]) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(text) if text else None
    except ValueError:
        return None


def projects_due(legend: Dict[str, str], lists: Iterable[Tuple[str, Optional[str], str]],
                 today: _dt.date, horizon: int = HORIZON_DAYS) -> List[Project]:
    """Return the projects due from today to ``horizon`` days ahead, soonest first.

    ``legend`` maps each code to its description. ``lists`` holds ``(list name,
    code, description)`` for the semester lists. A project in both is taken
    from the legend. A deadline already past is left out, because no block
    this week can meet it.
    """
    last = today + _dt.timedelta(days=horizon)
    found: Dict[str, Project] = {}
    for code, description in legend.items():
        name, due = split_deadline(description)
        day = _iso(due)
        if day and today <= day <= last:
            found.setdefault(name, Project(name, day, code, True, "legend", description))
    for list_name, code, description in lists:
        name, due = split_deadline(description)
        day = _iso(due)
        if day and today <= day <= last and name not in found:
            found[name] = Project(name, day, code, False, list_name, description)
    return sorted(found.values(), key=lambda p: (p.deadline, p.name))


def check(legend: Dict[str, str], lists: Iterable[Tuple[str, Optional[str], str]],
          slots: Sequence[Slot], monday: _dt.date, today: _dt.date,
          horizon: int = HORIZON_DAYS) -> Coverage:
    """Find the projects due soon with no block ahead, and propose a block for each.

    A block is ahead when its day is today or later. A donor block belongs to a
    project with no deadline inside the horizon. Generative and editing blocks
    are offered before support blocks, a project with no deadline gives before
    one with a later deadline, and a project with more time ahead gives first.
    A donor with a deadline keeps at least one block ahead. Each block is
    proposed once, and the nearest deadline is served first.
    """
    due = projects_due(legend, lists, today, horizon)
    due_codes = {p.code for p in due if p.in_legend}
    result = Coverage(today=today, horizon=horizon)
    ahead = [s for s in slots if monday + _dt.timedelta(days=s.offset) >= today]
    planned: Dict[str, int] = {}
    left: Dict[str, int] = {}
    blocks_left: Dict[str, int] = {}
    for s in slots:
        planned[s.code] = planned.get(s.code, 0) + s.minutes
    for s in ahead:
        left[s.code] = left.get(s.code, 0) + s.minutes
        blocks_left[s.code] = blocks_left.get(s.code, 0) + 1
    names = {code: split_deadline(desc)[0] for code, desc in legend.items()}
    deadlines = {code: _iso(split_deadline(desc)[1]) for code, desc in legend.items()}

    def donor_key(s: Slot):
        return (s.category == "support", deadlines.get(s.code) is not None,
                -left.get(s.code, 0), s.offset, s.start)

    used = set()
    for project in due:
        code = project.code if project.in_legend else None
        spent = planned.get(code, 0) if code else 0
        still = left.get(code, 0) if code else 0
        if still:
            result.covered.append((project, spent, still))
            continue
        risk = Risk(project, (project.deadline - today).days, spent, still)
        for s in sorted(ahead, key=donor_key):
            if (s.row, s.column) in used or s.code in due_codes:
                continue
            if deadlines.get(s.code) is not None and blocks_left.get(s.code, 0) < 2:
                continue
            used.add((s.row, s.column))
            blocks_left[s.code] = blocks_left.get(s.code, 0) - 1
            left[s.code] = left.get(s.code, 0) - s.minutes
            risk.donor = s
            risk.donor_name = names.get(s.code, s.code)
            risk.donor_deadline = deadlines.get(s.code)
            risk.donor_keeps = left[s.code]
            break
        result.risks.append(risk)
    return result


def _hours(minutes: int) -> str:
    hours, rest = divmod(int(minutes), 60)
    return f"{hours} h {rest:02d} min" if hours else f"{rest} min"


def _days(n: int) -> str:
    return "today" if n == 0 else ("tomorrow" if n == 1 else f"in {n} days")


def _who(project: Project) -> str:
    return f"{project.code} {project.name}" if project.code else project.name


def facts(result: Coverage) -> str:
    """Write the check as the facts the model receives."""
    lines = [f"Today: {result.today.isoformat()}",
             f"Deadlines counted: the next {result.horizon} days"]
    for risk in result.risks:
        p = risk.project
        lines.append(f"Due soon with no block left this week: {_who(p)}, due "
                     f"{p.deadline.isoformat()}, {_days(risk.days_left)}"
                     + ("" if p.in_legend else f", waiting on the {p.source} list"))
        if risk.donor is not None:
            d = risk.donor
            lines.append(f"Proposed block for it: {d.label()}, a {d.category} block "
                         f"of {d.minutes} minutes ({_hours(d.minutes)}) now planned for "
                         f"{d.code} {risk.donor_name}, which "
                         + ("has no deadline" if risk.donor_deadline is None else
                            f"is due {risk.donor_deadline.isoformat()}")
                         + f" and keeps {risk.donor_keeps} minutes "
                         f"({_hours(risk.donor_keeps)}) ahead this week")
        else:
            lines.append("Proposed block for it: none, because every block ahead "
                         "belongs to a project that is due soon")
    for project, spent, still in result.covered:
        lines.append(f"Covered: {_who(project)}, due {project.deadline.isoformat()}, "
                     f"{still} minutes ({_hours(still)}) still ahead this week")
    return "\n".join(lines)


def proposal_line(risk: Risk) -> str:
    """One checkable line for the dialog."""
    d = risk.donor
    return (f"Give {d.label()} ({d.category}) to {_who(risk.project)}, "
            f"taking it from {d.code} {risk.donor_name}")


def plain(result: Coverage) -> str:
    """Describe the check without a model."""
    if not result.risks:
        if not result.covered:
            return (f"No project in the legend or the lists is due in the next "
                    f"{result.horizon} days.")
        return (f"Every project due in the next {result.horizon} days has time "
                "left in this week's plan.")
    out = []
    for risk in result.risks:
        p = risk.project
        where = "" if p.in_legend else f" It waits on the {p.source} list."
        text = (f"{_who(p)} is due {p.deadline.isoformat()}, {_days(risk.days_left)}, "
                f"and has no block left this week.{where}")
        if risk.donor is not None:
            d = risk.donor
            text += (f" Give it {d.label()}, now planned for {d.code} "
                     f"{risk.donor_name}, which "
                     + ("has no deadline" if risk.donor_deadline is None else
                        f"is due later, on {risk.donor_deadline.isoformat()}")
                     + f" and keeps {_hours(risk.donor_keeps)} this week.")
        else:
            text += (" Every block ahead belongs to a project that is due soon, "
                     "so find time by adding a block or by moving a deadline.")
        out.append(text)
    if result.covered:
        out.append(f"{len(result.covered)} other project"
                   f"{'' if len(result.covered) == 1 else 's'} due soon "
                   f"{'has' if len(result.covered) == 1 else 'have'} time left "
                   "this week.")
    return "\n\n".join(out)
