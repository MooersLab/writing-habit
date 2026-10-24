"""Quick capture: a stray thought in plain words becomes a grasscatcher task.

The grasscatcher works only when capturing is faster than remembering. The
writer types or dictates a thought, such as ``remember to email the reviewer
about figure 3 for the R01, priority A``, and it lands on the list as
``A: [#A] Email the reviewer about figure 3``.

The software does the parts that can be checked. It finds the project by a
lookup of what the words name: the project's legend code, its four-digit
number, its whole name, or a distinctive part of its name such as ``R01``. It
reads a priority only from a cookie such as ``[#A1]`` or from the words
``priority A``. A model, when one is used, only proposes the project and
rewords the task. Its project is kept only when the lookup finds that project
named in the words, and its task is kept only when it uses the writer's words
and adds no number of its own. Otherwise the plain reading stands.

Nothing here imports Qt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .name import split_deadline

_COOKIE = re.compile(r"\[#([A-Za-z]\d*|\d+)\]")
_PRIORITY_WORDS = re.compile(r"\b(?:with\s+)?priority\s+([A-Za-z]\d*|\d+)\b[,.;]?",
                             re.IGNORECASE)
_LEAD_CODE = re.compile(r"^\s*([A-Z]{1,2}|\d)\s*:\s*")
_PROJECT_CODE = re.compile(r"\bproject\s+([A-Z]{1,2}|\d)\b")
_OPENERS = re.compile(
    r"^\s*(?:(?:please\s+)?remember\s+to|remind\s+me\s+to|note\s+to\s+self[:,]?|"
    r"i\s+(?:need|have|want|ought)\s+to|i\s+should|don't\s+forget\s+to|"
    r"do\s+not\s+forget\s+to|todo[:,]?|to\s+do[:,]?|task[:,]?)\s+",
    re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z0-9]+")
_NUMBER = re.compile(r"\b\d+\b")
#: Parts of project names too common to name a project on their own.
_COMMON = {"the", "and", "for", "with", "paper", "note", "notes", "draft", "new",
           "data", "project", "review", "talk", "letter", "email"}


@dataclass
class Project:
    code: str
    name: str            # the project name without its deadline


@dataclass
class Captured:
    """A task ready for the grasscatcher, and how its project was found."""

    code: Optional[str]
    task: str
    cookie: Optional[str] = None     # the priority, such as A1, without [# ]
    how: str = ""                    # why the project was chosen, for the log

    def entry_text(self) -> str:
        """The task as the grasscatcher stores it, with any cookie in front."""
        return (f"[#{self.cookie}] " if self.cookie else "") + self.task


def projects_from(legend: Dict[str, str],
                  lists: Sequence[Tuple[Optional[str], str]] = ()) -> List[Project]:
    """Return the coded projects of the legend and the lists, the legend first."""
    out: Dict[str, Project] = {}
    for code, description in legend.items():
        out.setdefault(code, Project(code, split_deadline(description)[0]))
    for code, description in lists:
        if code and code not in out:
            out[code] = Project(code, split_deadline(description)[0])
    return list(out.values())


def _number(name: str) -> Optional[str]:
    m = re.match(r"\s*(\d{4})", name)
    return m.group(1) if m else None


def _parts(name: str) -> List[str]:
    """Split ``1001grantR01`` into ``grant`` and ``R01``, keeping distinctive parts."""
    rest = re.sub(r"^\s*\d{4}", "", name)
    pieces = re.findall(r"[A-Z]+\d+|[A-Z]?[a-z]+|[A-Z]{2,}(?![a-z])|\d+", rest)
    return [p for p in pieces if len(p) >= 3 and p.lower() not in _COMMON]


def evidence(text: str, project: Project) -> Tuple[int, str]:
    """Score how plainly ``text`` names ``project``, with the reason.

    A legend code given as ``A:`` at the start or as ``project A`` scores 5, the
    four-digit number 4, the whole name 3, and each distinctive part of the
    name 1. Zero means the words do not name the project.
    """
    lead = _LEAD_CODE.match(text)
    if (lead and lead.group(1) == project.code) or project.code in _PROJECT_CODE.findall(text):
        return 5, f"its code {project.code}"
    words = [w.lower() for w in _WORD.findall(text)]
    number = _number(project.name)
    if number and any(w.isdigit() and len(w) >= 2 and int(w) == int(number)
                      for w in words):
        return 4, f"its number {number}"
    bare = re.sub(r"^\s*\d{4}", "", project.name).lower()
    if (len(bare) >= 4 and bare not in _COMMON
            and bare in re.sub(r"[^a-z0-9]", "", text.lower())):
        return 3, f"its name {project.name}"
    hits = [p for p in _parts(project.name) if p.lower() in words]
    if hits:
        return len(hits), f"{', '.join(hits)} in its name"
    return 0, ""


def find_project(text: str, projects: Sequence[Project]) -> Tuple[Optional[Project], str]:
    """Return the one project the words name best, or ``None`` when none or a tie."""
    scored = sorted(((evidence(text, p), p) for p in projects),
                    key=lambda item: -item[0][0])
    if not scored or scored[0][0][0] == 0:
        return None, "no project named in your words"
    if len(scored) > 1 and scored[1][0][0] == scored[0][0][0]:
        return None, (f"your words fit both {scored[0][1].code} and "
                      f"{scored[1][1].code}")
    (score, reason), project = scored[0]
    return project, reason


def _tidy(task: str) -> str:
    task = re.sub(r"\s+", " ", task).strip(" ,;:-")
    task = task.rstrip(".")
    return task[:1].upper() + task[1:] if task else task


def priority(text: str) -> Optional[str]:
    """Return a priority the words state, as ``A`` or ``A1`` or ``2``, or ``None``."""
    m = _COOKIE.search(text) or _PRIORITY_WORDS.search(text)
    if not m:
        return None
    value = m.group(1)
    return value.upper() if value[:1].isalpha() else value


def plain(text: str, projects: Sequence[Project]) -> Captured:
    """Read the words without a model."""
    project, how = find_project(text, projects)
    task = _COOKIE.sub("", text)
    task = _PRIORITY_WORDS.sub("", task)
    task = _LEAD_CODE.sub("", task)
    task = _OPENERS.sub("", task)
    return Captured(project.code if project else None, _tidy(task), priority(text), how)


def _stem(word: str) -> str:
    return word.lower()[:5]


def confirm(reply, text: str, projects: Sequence[Project], fallback: Captured) -> Captured:
    """Keep what a model proposed only where the software can confirm it.

    The project must be one the lookup finds named in the words, and the task
    must use mostly the writer's words and add no number of its own. The
    priority always comes from the words.
    """
    if not isinstance(reply, dict):
        return fallback
    code = str(reply.get("code") or "").strip().rstrip(":")
    chosen = next((p for p in projects if p.code == code), None)
    score, reason = evidence(text, chosen) if chosen is not None else (0, "")
    if score:
        code, how = chosen.code, reason
    elif chosen is not None:
        code = fallback.code
        how = ("the model's project is not named in your words"
               + (f", so the lookup chose {fallback.code} by {fallback.how}"
                  if fallback.code else ""))
    else:
        code, how = fallback.code, fallback.how
    task = _tidy(str(reply.get("task") or ""))
    said = {_stem(w) for w in _WORD.findall(text)}
    words = [w for w in _WORD.findall(task) if len(w) >= 3]
    if (not words or sum(_stem(w) in said for w in words) < 0.6 * len(words)
            or not set(_NUMBER.findall(task)) <= set(_NUMBER.findall(text))):
        task = fallback.task
    return Captured(code or None, task, fallback.cookie, how)


def facts(text: str, projects: Sequence[Project]) -> str:
    """Write what the model may see: the project list and the captured words."""
    lines = ["Projects:"] + [f"  {p.code}: {p.name}" for p in projects]
    lines.append("Captured words: " + " ".join(text.split()))
    return "\n".join(lines)
