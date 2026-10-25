"""The Monday message: the week's plan, told to an accountability partner.

Rule 8 suggests exchanging the plan on Monday and the comparison on Friday.
The Friday summary is in :mod:`writing_habit.coach`. This module writes the
Monday half from the open weekly table: the hours planned, the blocks and the
days they fall on, the projects that take the most time, and the one project
that matters most this week, the one with the nearest deadline, with its first
objective when one is already set. The writer edits the draft and sends it.

Nothing here imports Qt, and nothing is sent from here.
"""

from __future__ import annotations

import datetime as _dt
from typing import Dict, List, Optional, Sequence, Tuple

from .name import split_deadline

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
#: At most this many projects are named, so the message stays short.
TOP_PROJECTS = 3


def _hours(minutes: int) -> str:
    hours, rest = divmod(int(minutes), 60)
    return f"{hours} h {rest:02d} min" if hours else f"{rest} min"


def _date_words(iso: str) -> str:
    day = _dt.date.fromisoformat(iso)
    return f"{MONTHS[day.month - 1]} {day.day}"


def _series(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (", and " if len(items) > 2 else " and ") + items[-1]


def gather(week_start: str, minutes: Dict[str, int], legend: Dict[str, str],
           blocks: int, days: int,
           objectives: Sequence[Tuple[str, str]] = ()) -> Optional[dict]:
    """Collect the plan of the week starting ``week_start``.

    ``minutes`` maps each code to its planned minutes, ``legend`` each code to
    its description, and ``objectives`` holds ``(code, text)`` already set
    for the week's blocks, in time order. Return ``None`` for an empty plan.
    """
    total = sum(minutes.values())
    if not total:
        return None
    projects = []
    for code, planned in minutes.items():
        name, due = split_deadline(legend.get(code, code))
        projects.append((code, name or code, planned, due))
    projects.sort(key=lambda p: (-p[2], p[0]))
    upcoming = [p for p in projects if p[3] and p[3] >= week_start]
    key = (min(upcoming, key=lambda p: (p[3], -p[2], p[0])) if upcoming
           else projects[0])
    objective = next((text for code, text in objectives if code == key[0]), None)
    return {"week_start": week_start, "total": total, "blocks": blocks, "days": days,
            "projects": [(c, n, m) for c, n, m, _d in projects],
            "key": {"code": key[0], "name": key[1], "minutes": key[2],
                    "deadline": key[3]},
            "objective": objective}


def facts(plan: dict) -> str:
    """Write the plan as the facts the model receives."""
    lines = [f"Week starting: {plan['week_start']}",
             f"Minutes planned: {plan['total']} ({_hours(plan['total'])})",
             f"Blocks planned: {plan['blocks']}",
             f"Days with writing: {plan['days']}"]
    for code, name, minutes in plan["projects"][:TOP_PROJECTS]:
        lines.append(f"Project: {code} {name}, {minutes} minutes ({_hours(minutes)})")
    key = plan["key"]
    line = f"Project that matters most: {key['code']} {key['name']}"
    if key["deadline"]:
        line += f", due {key['deadline']} ({_date_words(key['deadline'])})"
    lines.append(line)
    if plan["objective"]:
        lines.append(f"First objective for it: {plan['objective']}")
    return "\n".join(lines)


def plain(plan: dict) -> str:
    """Write the Monday message without a model, in the writer's own voice."""
    first = [f"This week I plan {_hours(plan['total'])} of writing in "
             f"{plan['blocks']} block{'' if plan['blocks'] == 1 else 's'} over "
             f"{plan['days']} day{'' if plan['days'] == 1 else 's'}."]
    named = [f"{name} ({_hours(minutes)})"
             for _c, name, minutes in plan["projects"][:TOP_PROJECTS]]
    if len(plan["projects"]) == 1:
        first.append(f"All of it goes to {named[0]}.")
    else:
        first.append(f"Most of it goes to {_series(named)}.")
    key = plan["key"]
    second = [f"The one that matters most is {key['name']}"
              + (f", due {_date_words(key['deadline'])}." if key["deadline"]
                 else ", which has the most time.")]
    if plan["objective"]:
        second.append(f'My first objective there is "{plan["objective"].rstrip(".")}".')
    second.append("I will send you how it went on Friday.")
    return " ".join(first) + "\n\n" + " ".join(second)
