"""Keep the grasscatcher list in step with the to-dos of each project's log file.

A project's log, such as ``~/0142RETKinaseCovalentInhibitors/log0142.org``,
lists its to-dos as headings under a top-level ``* Project TODOS`` heading::

    * Project TODOS
    ** TODO [#A1] Read the key review articles on covalent docking.
    ** DONE [#B] Measure the cysteine distances in 7JU6

The grasscatcher list of a weekly table holds the same tasks, one per row,
with the project's legend code, written as ``1: [#A1] Read the key review
articles on covalent docking.``. A priority cookie may be a letter (``[#A]``),
a number (``[#1]``), or a letter and a number (``[#A1]``).

A sync compares the two, task by task, matched by their text without the
cookie, case, or a final full stop:

- an open to-do of the log that the grasscatcher lacks is added to it;
- a grasscatcher task that the log lacks is added to the log as a TODO;
- a grasscatcher task that the log marks done is taken off the grasscatcher;
- when both hold a task with different cookies, the log's cookie wins.

The log is changed only by adding lines at the end of its Project TODOS
section, so every other line stays as it was. Nothing here imports Qt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: The heading the to-dos live under, matched without regard to case.
SECTION_RE = re.compile(r"^\*\s+Project\s+TODOS?\s*$", re.IGNORECASE)
HEADING_RE = re.compile(r"^(\*+)\s+(.*?)\s*$")
#: A priority cookie: a letter, a number, or a letter and a number.
COOKIE_RE = re.compile(r"\[#([A-Za-z]\d*|\d+)\]")
LEADING_COOKIE_RE = re.compile(r"^\s*\[#([A-Za-z]\d*|\d+)\]\s*")
TAGS_RE = re.compile(r"\s+(:[\w@#%:]+:)\s*$")
#: Keywords that close a to-do.
DONE_WORDS = {"DONE", "CANCELED", "CANCELLED"}
OPEN_WORDS = {"TODO", "NEXT", "WAITING", "HOLD", "STARTED"}
KEYWORDS = DONE_WORDS | OPEN_WORDS
_NUMBER = re.compile(r"^\s*(\d{4})")


@dataclass
class LogTodo:
    """One to-do heading of a log."""

    keyword: str
    priority: Optional[str]
    title: str
    line: int

    @property
    def done(self) -> bool:
        return self.keyword in DONE_WORDS

    @property
    def key(self) -> str:
        return task_key(self.title)

    def task_text(self) -> str:
        """Return the task as the grasscatcher writes it: cookie, then title."""
        return join_priority(self.priority, self.title)


def task_key(text: str) -> str:
    """Return the text a task is matched by: no cookie, no case, no full stop."""
    text = COOKIE_RE.sub(" ", text or "")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text.rstrip(".").strip()


def split_priority(text: str) -> Tuple[Optional[str], str]:
    """Split ``[#A1] Read the review`` into ``("A1", "Read the review")``."""
    m = LEADING_COOKIE_RE.match(text or "")
    if not m:
        return None, (text or "").strip()
    return m.group(1).upper(), text[m.end():].strip()


def join_priority(priority: Optional[str], title: str) -> str:
    return f"[#{priority}] {title.strip()}" if priority else title.strip()


def priority_key(priority: Optional[str]):
    """Sort key for a cookie: letters first by letter then number; none last.

    ``[#A]`` sorts before ``[#A1]``, which sorts before ``[#A2]`` and ``[#B]``.
    A number alone sorts after every letter, and a task with no cookie last.
    """
    if not priority:
        return (2, "", 0)
    m = re.match(r"^([A-Za-z]?)(\d*)$", priority)
    letter, number = (m.group(1).upper(), m.group(2)) if m else ("", "")
    if letter:
        return (0, letter, int(number) if number else -1)
    return (1, "", int(number) if number else 0)


# -- reading a log ---------------------------------------------------------------
def section_span(lines: List[str]) -> Optional[Tuple[int, int]]:
    """Return ``(heading line, end)`` of the Project TODOS section, or ``None``.

    ``end`` is the index of the next top-level heading, or the line count.
    """
    for index, line in enumerate(lines):
        if SECTION_RE.match(line):
            end = index + 1
            while end < len(lines) and not re.match(r"^\*\s", lines[end]):
                end += 1
            return index, end
    return None


def read_todos(text: str) -> List[LogTodo]:
    """Return the to-do headings under ``* Project TODOS``, in file order."""
    lines = text.splitlines()
    span = section_span(lines)
    if span is None:
        return []
    out: List[LogTodo] = []
    for index in range(span[0] + 1, span[1]):
        m = HEADING_RE.match(lines[index])
        if not m or len(m.group(1)) < 2:
            continue
        rest = m.group(2)
        word, _space, tail = rest.partition(" ")
        if word not in KEYWORDS:
            continue
        tail = TAGS_RE.sub("", tail)
        priority, title = split_priority(tail)
        if title:
            out.append(LogTodo(word, priority, title, index))
    return out


# -- finding a project's log -------------------------------------------------------
def project_number(project: str) -> Optional[str]:
    m = _NUMBER.match(project or "")
    return m.group(1) if m else None


def find_log(project: str, root: Path) -> Tuple[Optional[Path], List[Path]]:
    """Return ``(log, candidates)`` for a project name such as ``0142RETKinase...``.

    The folder named exactly like the project wins. Otherwise a single folder
    under ``root`` whose name starts with the project's number and holds
    ``logNNNN.org`` is used. Several such folders give no log and the list of
    candidates, so the writer can choose.
    """
    number = project_number(project)
    if number is None:
        return None, []
    root = Path(root).expanduser()
    name = f"log{number}.org"
    exact = root / project.strip() / name
    if exact.is_file():
        return exact, [exact]
    try:
        found = sorted(p / name for p in root.glob(f"{number}*")
                       if p.is_dir() and (p / name).is_file())
    except OSError:
        found = []
    if len(found) == 1:
        return found[0], found
    return None, found


def editor_lock(log: Path) -> Optional[Path]:
    """Return the Emacs lock or autosave file of ``log`` if one exists.

    Its presence means the log may be open with unsaved changes, and saving
    that buffer later would overwrite what the sync added.
    """
    for candidate in (log.with_name(f".#{log.name}"), log.with_name(f"#{log.name}#")):
        if candidate.exists() or candidate.is_symlink():
            return candidate
    return None


# -- planning a sync -----------------------------------------------------------------
@dataclass
class ProjectSync:
    """What one sync will change for one project."""

    code: str
    project: str
    log: Optional[Path]
    #: Open log to-dos to add to the grasscatcher, as task texts.
    to_grasscatcher: List[str] = field(default_factory=list)
    #: Grasscatcher tasks to add to the log, as task texts.
    to_log: List[str] = field(default_factory=list)
    #: Grasscatcher positions of tasks the log marks done.
    done: List[int] = field(default_factory=list)
    #: ``(grasscatcher position, new task text)`` where the log's cookie wins.
    reprioritize: List[Tuple[int, str]] = field(default_factory=list)
    #: Why nothing can be synced, when ``log`` is ``None``.
    problem: Optional[str] = None
    #: An Emacs lock or autosave file beside the log.
    lock: Optional[Path] = None

    @property
    def changes(self) -> int:
        return (len(self.to_grasscatcher) + len(self.to_log) + len(self.done)
                + len(self.reprioritize))


def plan_project(code: str, project: str, log: Optional[Path],
                 grasscatcher: List[Tuple[int, Optional[str], str]],
                 candidates: Optional[List[Path]] = None) -> ProjectSync:
    """Compare one project's log with its grasscatcher tasks.

    ``grasscatcher`` holds ``(position, code, task text)`` for every row of the
    list; only the rows whose code is ``code`` take part.
    """
    plan = ProjectSync(code, project, log)
    if log is None:
        if candidates:
            plan.problem = ("several logs match: "
                            + ", ".join(str(c) for c in candidates))
        else:
            plan.problem = "no log file found"
        return plan
    try:
        todos = read_todos(Path(log).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        plan.log = None
        plan.problem = f"could not read {log}: {exc}"
        return plan
    plan.lock = editor_lock(Path(log))
    by_key: Dict[str, LogTodo] = {}
    for todo in todos:
        by_key.setdefault(todo.key, todo)
    mine = [(pos, text) for pos, c, text in grasscatcher if c == code]
    have = set()
    for position, text in mine:
        key = task_key(text)
        have.add(key)
        todo = by_key.get(key)
        if todo is None:
            plan.to_log.append(text)
        elif todo.done:
            plan.done.append(position)
        else:
            priority, title = split_priority(text)
            if todo.priority != priority:
                plan.reprioritize.append((position, join_priority(todo.priority, title)))
    for todo in todos:
        if not todo.done and todo.key not in have:
            plan.to_grasscatcher.append(todo.task_text())
            have.add(todo.key)
    return plan


# -- writing a log -----------------------------------------------------------------------
def add_to_log(text: str, tasks: List[str]) -> str:
    """Return ``text`` with ``** TODO`` headings for ``tasks`` added.

    The headings go at the end of the Project TODOS section, before the blank
    lines that lead to the next top-level heading. A log without the section
    gets one at its end. No other line changes.
    """
    if not tasks:
        return text
    lines = text.splitlines()
    new = []
    for task in tasks:
        priority, title = split_priority(task)
        new.append("** TODO " + join_priority(priority, title))
    span = section_span(lines)
    if span is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "* Project TODOS", ""] + new
    else:
        at = span[1]
        while at > span[0] + 1 and not lines[at - 1].strip():
            at -= 1
        lines[at:at] = new
    return "\n".join(lines) + "\n"


def write_log(log: Path, tasks: List[str]) -> int:
    """Add ``tasks`` to the log at ``log``, keeping a ``~`` copy.  Return the count."""
    if not tasks:
        return 0
    log = Path(log)
    old = log.read_text(encoding="utf-8")
    log.with_name(log.name + "~").write_text(old, encoding="utf-8")
    log.write_text(add_to_log(old, tasks), encoding="utf-8")
    return len(tasks)


# -- the grasscatcher side ------------------------------------------------------------------
def grasscatcher_rows(lists) -> List[Tuple[int, Optional[str], str]]:
    """Return ``(position, code, task text)`` for every grasscatcher row."""
    from .project_lists import GRASSCATCHER
    return [(i, e.code, e.description) for i, e in enumerate(lists.entries(GRASSCATCHER))]


def apply_to_lists(lists, plans: List[ProjectSync]) -> int:
    """Make the grasscatcher changes of ``plans``.  Return how many rows changed."""
    from .project_lists import GRASSCATCHER, Entry
    changed = 0
    entries = lists.entries(GRASSCATCHER)
    for plan in plans:
        for position, text in plan.reprioritize:
            entry = entries[position]
            entry.description = text
            if lists.set_entry(GRASSCATCHER, position, entry):
                changed += 1
    gone = sorted({p for plan in plans for p in plan.done}, reverse=True)
    for position in gone:
        lists.remove(GRASSCATCHER, position)
        changed += 1
    for plan in plans:
        for text in plan.to_grasscatcher:
            lists.insert(GRASSCATCHER, None, Entry(plan.code, text))
            changed += 1
    return changed


def sort_by_priority(lists) -> bool:
    """Order the grasscatcher by cookie, keeping the order of equal cookies."""
    from .project_lists import GRASSCATCHER
    rows = lists.row_indexes(GRASSCATCHER)
    texts = [lists.lines[i] for i in rows]
    entries = lists.entries(GRASSCATCHER)
    order = sorted(range(len(rows)),
                   key=lambda n: priority_key(split_priority(entries[n].description)[0]))
    ordered = [texts[n] for n in order]
    if ordered == texts:
        return False
    for index, line in zip(rows, ordered):
        lists.lines[index] = line
    return True
