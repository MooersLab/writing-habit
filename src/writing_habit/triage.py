"""Roll-forward triage: keep, defer, or drop each carried-over project.

A roll forward moves the projects of the period that ended to the Carried over
list, and each one needs a decision. Keeping every one quietly overloads the
new period, which is how a list of thirty projects becomes a list nobody
reads. This module suggests a decision for each carried project from three
facts a writer can check: the minutes logged for it in recent weeks, the last
week it was worked, and its deadline. The rules, in order:

- Keep a project worked for at least an hour in the last four weeks, because
  it is alive.
- Keep a project whose deadline falls in the new period.
- Drop a project whose deadline has passed with no recent work, because the
  date it was held to is gone. The deadline may be renegotiated instead.
- Defer a project whose deadline falls after the new period to the next
  period's list.
- Defer a project worked earlier in the period but not lately, because it may
  return when time allows.
- Drop a project with no time logged in the period and no deadline, because
  it has been carried without being worked.

Dropping takes the project off the lists only. Its folder, its log, and its
history in the habit database are untouched, and it can be added back.

Everything here only suggests. Nothing imports Qt, and nothing changes a file.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .name import split_deadline

#: The weeks counted as recent, and the minutes in them that keep a project alive.
RECENT_WEEKS = 4
ACTIVE_MINUTES = 60

KEEP, DEFER, DROP = "keep", "defer", "drop"
VERBS = {KEEP: "Keep", DEFER: "Defer", DROP: "Drop"}


def _key(project: str) -> str:
    """Name a project by its four-digit number when it has one, else by its name."""
    from .project_lists import project_number
    return project_number(project) or (project or "").strip()


def _monday(day: _dt.date) -> _dt.date:
    return day - _dt.timedelta(days=day.weekday())


@dataclass
class Decision:
    """A suggested decision for one carried project, with its reason."""

    project: str
    action: str                      # keep, defer, or drop
    reason: str
    deadline: Optional[str] = None
    recent: int = 0                  # minutes in the last RECENT_WEEKS weeks
    total: int = 0                   # minutes since the history starts
    last_week: Optional[str] = None  # Monday of the last week with time logged
    target: str = ""                 # where a deferred project goes, by title

    def line(self) -> str:
        """One checkable line for the dialog."""
        where = {KEEP: " on the current list",
                 DEFER: f" to {self.target or 'the next period'}",
                 DROP: " from the lists"}[self.action]
        return f"{VERBS[self.action]} {self.project}{where}"


def minutes_by_project(con, names_by_code: Dict[str, str], since: str
                       ) -> Dict[str, Dict[str, int]]:
    """Return ``{project key: {week Monday: minutes}}`` from the habit database.

    A session is filed under a legend code, and a code can name another
    project from one week to the next. Each code is resolved to a project by
    ``names_by_code`` first, the codes of the open table and the carried list,
    and otherwise by the description the database holds for the code.
    """
    out: Dict[str, Dict[str, int]] = {}
    rows = con.execute(
        "SELECT s.week_start, p.code, p.description, SUM(s.actual_min) "
        "FROM session s JOIN project p ON p.project_id = s.project_id "
        "WHERE s.day >= ? GROUP BY s.week_start, p.code", (since,))
    for week, code, description, minutes in rows:
        name = names_by_code.get(code) or split_deadline(description or "")[0]
        if not name:
            continue
        weeks = out.setdefault(_key(name), {})
        weeks[week] = weeks.get(week, 0) + int(minutes or 0)
    return out


def decide(project: str, deadline: Optional[str], weeks: Dict[str, int],
           today: _dt.date, period_end: _dt.date, target: str = "") -> Decision:
    """Suggest keep, defer, or drop for one project, by the rules above."""
    cutoff = (_monday(today) - _dt.timedelta(weeks=RECENT_WEEKS)).isoformat()
    recent = sum(m for w, m in weeks.items() if w >= cutoff)
    total = sum(weeks.values())
    worked = sorted(w for w, m in weeks.items() if m > 0)
    last = worked[-1] if worked else None
    d = Decision(project, KEEP, "", deadline, recent, total, last, target)
    due = _dt.date.fromisoformat(deadline) if deadline else None
    if recent >= ACTIVE_MINUTES:
        d.reason = (f"{recent} minutes were logged for it in the last "
                    f"{RECENT_WEEKS} weeks, so it is alive")
    elif due is not None and today <= due <= period_end:
        d.reason = f"its deadline, {deadline}, falls in this period"
    elif due is not None and due < today:
        d.action = DROP
        d.reason = (f"its deadline, {deadline}, has passed with little time logged "
                    "lately. Renegotiate the date instead if it still matters")
    elif due is not None:
        d.action = DEFER
        d.reason = f"its deadline, {deadline}, falls after this period"
    elif total > 0:
        d.action = DEFER
        d.reason = (f"it was last worked the week of {last}, and no deadline "
                    "presses")
    else:
        d.action = DROP
        d.reason = ("no time was logged for it this period, and it has no "
                    "deadline")
    return d


def triage(entries: Sequence, history: Dict[str, Dict[str, int]],
           today: _dt.date, period_end: _dt.date, target: str = "") -> List[Decision]:
    """Suggest a decision for each carried entry, in list order.

    ``entries`` are :class:`writing_habit.project_lists.Entry` rows of the
    Carried over list, and ``history`` comes from :func:`minutes_by_project`.
    """
    out = []
    for entry in entries:
        project, deadline = split_deadline(entry.description)
        out.append(decide(project, deadline, history.get(_key(project), {}),
                          today, period_end, target))
    return out


def facts(found: Sequence[Decision], period: str) -> str:
    """Write the decisions as the facts the model receives, in words."""
    lines = [f"New period: {period}"]
    for d in found:
        lines.append(f"Carried project {d.project}: suggested {d.action}, because "
                     f"{d.reason}. Minutes in the last {RECENT_WEEKS} weeks: "
                     f"{d.recent}. Last week worked: {d.last_week or 'none'}.")
    return "\n".join(lines)


def plain(found: Sequence[Decision]) -> str:
    """Describe the decisions without a model."""
    if not found:
        return "Nothing is on the Carried over list, so nothing needs a decision."
    counts = {a: sum(d.action == a for d in found) for a in (KEEP, DEFER, DROP)}
    head = (f"{len(found)} carried project{'' if len(found) == 1 else 's'}: keep "
            f"{counts[KEEP]}, defer {counts[DEFER]}, drop {counts[DROP]}. Dropping "
            "takes a project off the lists only. Its folder and history stay.")
    return "\n".join([head] + [f"  {VERBS[d.action]} {d.project}, because {d.reason}."
                               for d in found])
