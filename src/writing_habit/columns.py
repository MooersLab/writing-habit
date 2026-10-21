"""The column layout of the project tables, read and written.

A weekly table file may keep its legend and its project lists as tables with
one column per field, the layout the editor shows::

    #+NAME: This week
    | Code | Project Number | Project Name    | Deadline   | Risk tag | Default activity |
    |------+----------------+-----------------+------------+----------+------------------|
    | B:   | 1006           | AIrxOpt         | 2026-12-15 | :safe:   |                  |
    | -    | 1452           | PHFSboXt        | 2027-03-01 | :safe:   | editing          |

The grasscatcher has its own columns::

    #+NAME: grasscatcher
    | Code | Project Number | Project Name                | Priority | Task          |
    |------+----------------+-----------------------------+----------+---------------|
    | 1:   | 0142           | RETKinaseCovalentInhibitors | [#A1]    | Read reviews. |

The rest of the package works on the older one-cell form of a row, such as
``B: 1006AIrxOpt 2026-12-15 :safe:``. This module turns a row of columns into
that cell and back, so the editor, the lists, and the readers keep one model
whichever layout the file uses. Nothing here imports Qt.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

PROJECT_COLUMNS = ["Code", "Project Number", "Project Name", "Deadline",
                   "Risk tag", "Default activity"]
TASK_COLUMNS = ["Code", "Project Number", "Project Name", "Priority", "Task"]

#: The name of the table that holds the week's legend in the column layout.
LEGEND_NAME = "This week"

_RULE = re.compile(r"^\s*\|[-+]")
_CODE = re.compile(r"^([A-Za-z0-9]{1,2})\s*:?$")
_NUMBER = re.compile(r"^(\d{4})(.*)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COOKIE = re.compile(r"^\[#([A-Za-z]\d*|\d+)\]$")
_RISK = {"safe": "safe", "risky": "risky", "speculative": "risky"}
_ACTIVITY = {"generative": "generative", "editing": "editing", "support": "support",
             "g": "generative", "e": "editing", "s": "support"}


def cells(line: str) -> List[str]:
    """Return the stripped cells of an org table line."""
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def is_header(row: List[str]) -> bool:
    """Whether a row is the column header of a project or task table."""
    return bool(row) and row[0].strip().lower().startswith("code") and len(row) >= 3


def is_task_header(row: List[str]) -> bool:
    return is_header(row) and any(c.strip().lower() == "task" for c in row)


def split_project(project: str) -> Tuple[str, str]:
    """Split ``1006AIrxOpt`` into ``("1006", "AIrxOpt")``; no number gives ``("", name)``."""
    m = _NUMBER.match((project or "").strip())
    return (m.group(1), m.group(2).strip()) if m else ("", (project or "").strip())


# -- columns to the one-cell form ---------------------------------------------
def _code_head(code: str) -> Optional[str]:
    code = (code or "").strip()
    if code in ("", "-"):
        return "-"
    m = _CODE.match(code)
    return f"{m.group(1).upper()}:" if m else None


def project_cell(row: List[str]) -> Optional[str]:
    """Return the one-cell form of a project row, or ``None`` when it is empty."""
    row = (row + [""] * 6)[:6]
    code, number, name, deadline, risk, activity = (c.strip() for c in row)
    if not (number or name):
        return None
    head = _code_head(code)
    if head is None:
        return None
    text = f"{head} {number}{name}".rstrip()
    deadline = re.sub(r"\s+", "", deadline)
    if deadline:
        text += f" {deadline}"
    word = _ACTIVITY.get(activity.lstrip("@").strip().lower())
    if word:
        text += f" @{word}"
    tag = _RISK.get(risk.strip(":() ").lower())
    if tag:
        text += f" :{tag}:"
    return text


def task_cell(row: List[str]) -> Optional[str]:
    """Return the one-cell form of a grasscatcher row, or ``None`` when it is empty."""
    row = (row + [""] * 5)[:5]
    code, _number, _name, priority, task = (c.strip() for c in row)
    if not task:
        return None
    head = _code_head(code)
    if head is None:
        return None
    priority = priority.strip()
    if priority and not _COOKIE.match(priority):
        priority = f"[#{priority.strip('[]#')}]"
    return f"{head} {priority + ' ' if priority else ''}{task}".strip()


# -- the one-cell form to columns ----------------------------------------------
def project_columns(cell: str) -> List[str]:
    """Return the six columns of a project row given in the one-cell form."""
    from .name import legend_activity, parse_legend_cell, split_deadline
    from .project_lists import parse_entry

    entry = parse_entry(cell)
    if entry is None:
        return [cell.strip(), "", "", "", "", ""]
    project, deadline = split_deadline(entry.description)
    number, name = split_project(project)
    risk = {"safe": ":safe:", "speculative": ":risky:"}.get(entry.risk or "", "")
    return [f"{entry.code}:" if entry.code else "-", number, name, deadline or "",
            risk, entry.activity or ""]


def task_columns(cell: str, projects: Dict[str, Tuple[str, str]]) -> List[str]:
    """Return the five columns of a grasscatcher row given in the one-cell form.

    ``projects`` maps a code to ``(number, name)``, so the row names the
    project its task belongs to.
    """
    from .project_lists import parse_entry
    from .todo_sync import split_priority

    entry = parse_entry(cell)
    if entry is None:
        return ["-", "", "", "", cell.strip()]
    priority, task = split_priority(entry.description)
    number, name = projects.get(entry.code or "", ("", ""))
    return [f"{entry.code}:" if entry.code else "-", number, name,
            f"[#{priority}]" if priority else "", task]


def render(header: List[str], rows: List[List[str]]) -> List[str]:
    """Return an aligned org table, as org-mode's own alignment writes it."""
    table = [header] + rows
    widths = [max(len(r[i]) for r in table) for i in range(len(header))]
    line = lambda r: "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(r)) + " |"
    rule = "|" + "+".join("-" * (w + 2) for w in widths) + "|"
    return [line(header), rule] + [line(r) for r in rows]


# -- whole tables ----------------------------------------------------------------
def read_table(lines: List[str]) -> Tuple[bool, List[str]]:
    """Read the lines of one table.  Return ``(in columns, one-cell rows)``.

    A table whose first row is a ``Code`` header is read by its columns, and
    any other table by its first cell, so both layouts give the same rows.
    """
    rows = [cells(line) for line in lines
            if line.lstrip().startswith("|") and not _RULE.match(line)]
    if not rows or not is_header(rows[0]):
        return False, [r[0] for r in rows if r and r[0]]
    convert = task_cell if is_task_header(rows[0]) else project_cell
    out = []
    for row in rows[1:]:
        cell = convert(row)
        if cell:
            out.append(cell)
    return True, out


def task_projects(lines: List[str]) -> Dict[str, Tuple[str, str]]:
    """Return ``{code: (number, name)}`` as a grasscatcher table in columns names them."""
    rows = [cells(line) for line in lines
            if line.lstrip().startswith("|") and not _RULE.match(line)]
    if not rows or not is_task_header(rows[0]):
        return {}
    out: Dict[str, Tuple[str, str]] = {}
    for row in rows[1:]:
        row = (row + [""] * 5)[:5]
        head = _code_head(row[0])
        if head and head != "-":
            out.setdefault(head[:-1], (row[1], row[2]))
    return out


#: Stands in the lines after the week for the place of the This week table.
LEGEND_SLOT = "\x00this-week-legend"


def to_one_cell(lines: List[str]):
    """Read every table of ``lines`` in columns into the one-cell form.

    Return ``(lines, legend, tasks, found)``. ``lines`` has each named table
    in columns rewritten as one-cell rows, and the This week table replaced by
    :data:`LEGEND_SLOT`. ``legend`` holds that table's rows in the one-cell
    form, or ``None`` when the file has none in columns. ``tasks`` maps a code
    to ``(number, name)`` from the grasscatcher, and ``found`` says whether any
    table was in columns.
    """
    from .project_lists import _NAME_LINE, normalize_title

    out: List[str] = []
    legend: Optional[List[str]] = None
    tasks: Dict[str, Tuple[str, str]] = {}
    found = False
    index = 0
    while index < len(lines):
        line = lines[index]
        m = _NAME_LINE.match(line)
        if not m:
            out.append(line)
            index += 1
            continue
        start = index + 1
        while start < len(lines) and lines[start].lstrip().startswith("#+") \
                and not _NAME_LINE.match(lines[start]):
            start += 1
        end = start
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1
        block = lines[start:end]
        columnar, rows = read_table(block)
        if not columnar:
            out.extend(lines[index:end])
            index = end
            continue
        found = True
        if normalize_title(m.group(1)) == normalize_title(LEGEND_NAME) and legend is None:
            legend = rows
            out.append(LEGEND_SLOT)
        else:
            tasks.update(task_projects(block))
            out.extend(lines[index:start])
            out.extend(f"| {row} |" for row in rows)
        index = end
    return out, legend, tasks, found


def to_columns(lines: List[str], legend: List[str], titles: Dict[str, str],
               projects: Dict[str, Tuple[str, str]]) -> List[str]:
    """Write ``lines`` with every project list in columns and the legend restored.

    ``legend`` is the week's legend in the one-cell form, written as the This
    week table at :data:`LEGEND_SLOT`, or at the top when the slot is missing.
    ``titles`` maps a list name to the title shown above it as a caption.
    ``projects`` maps a code to ``(number, name)`` for the grasscatcher rows.
    """
    from .project_lists import GRASSCATCHER, NAMES, _NAME_LINE, normalize_title

    legend_table = [f"#+NAME: {LEGEND_NAME}"] + render(
        PROJECT_COLUMNS, [project_columns(c) for c in legend])
    out: List[str] = []
    placed = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if line == LEGEND_SLOT:
            out.extend(legend_table)
            placed = True
            index += 1
            continue
        m = _NAME_LINE.match(line)
        name = normalize_title(m.group(1)) if m else None
        if name not in NAMES:
            out.append(line)
            index += 1
            continue
        start = index + 1
        while start < len(lines) and lines[start].lstrip().startswith("#+") \
                and not _NAME_LINE.match(lines[start]):
            start += 1
        end = start
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1
        keep = [x for x in lines[index + 1:start]
                if not x.lstrip().upper().startswith("#+CAPTION:")]
        rows = [cells(x)[0] for x in lines[start:end]
                if not _RULE.match(x) and cells(x) and cells(x)[0]]
        out.append(f"#+NAME: {name}")
        title = titles.get(name)
        if title:
            out.append(f"#+CAPTION: {title}")
        out.extend(keep)
        if name == GRASSCATCHER:
            out.extend(render(TASK_COLUMNS, [task_columns(r, projects) for r in rows]))
        else:
            out.extend(render(PROJECT_COLUMNS, [project_columns(r) for r in rows]))
        index = end
    if not placed and legend:
        rest = out[1:] if out and not out[0].strip() else out
        out = [""] + legend_table + ([""] + rest if rest else [])
    return out
