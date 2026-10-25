"""Project numbering help: a free number near related projects.

Each writing project carries a four-digit number, as in ``0142RETKinase...``,
and related projects read best with nearby numbers. Choosing a number by hand
means remembering hundreds of them. This module gathers the numbers already in
use, from the project folders and from the week's legend and lists, finds the
projects whose names share distinctive words with the new one, and suggests a
free number inside or just beside their range.

It also flags a project that may be forming inside another: several tasks of
one project, on the grasscatcher or as block objectives, that share a word the
project's own name does not hold.

Everything here only suggests. Nothing renames or moves a project or a folder.
Nothing here imports Qt.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

_FOLDER = re.compile(r"^(\d{4})([A-Za-z].*)$")
#: Words too common in project names, or in tasks, to relate two projects.
_COMMON = {"the", "and", "for", "with", "from", "into", "paper", "note", "notes",
           "draft", "new", "data", "project", "review", "talk", "letter", "email",
           "write", "read", "make", "find", "check", "update", "about", "this",
           "that", "send", "edit", "fix", "add", "tidy", "figure", "figures",
           "section", "table", "tables", "methods", "results", "intro", "first",
           "second", "third", "next", "last", "more", "reviewer", "reviewers",
           "article", "manuscript", "chapter"}
#: Tasks that must share a word before a project counts as forming inside another.
FORMING = 3


def words(name: str) -> List[str]:
    """Split a project name into lowercase words, as ``RETKinaseCovalent`` gives
    ``ret``, ``kinase``, and ``covalent``."""
    name = re.sub(r"^\s*\d{4}", "", name or "")
    pieces = [p.lower() for p in re.findall(
        r"[A-Z]+\d*(?=[A-Z][a-z]|\b|_|\d|$)|[A-Z]?[a-z]+\d*|[A-Z]+\d*|\d+", name)]
    # A piece of one or two letters merges with the next, so PyMOL gives
    # pymol as PYMOL does, and QCr gives qcr.
    merged, i = [], 0
    while i < len(pieces):
        if len(pieces[i]) <= 2 and i + 1 < len(pieces):
            merged.append(pieces[i] + pieces[i + 1])
            i += 2
        else:
            merged.append(pieces[i])
            i += 1
    return merged


def _stem(word: str) -> str:
    return word[:5]


def distinctive(name: str) -> List[str]:
    return [w for w in words(name) if len(w) >= 3 and w not in _COMMON
            and not w.isdigit()]


def folder_projects(root: Path) -> Dict[str, str]:
    """Return ``{number: name}`` for the project folders directly under ``root``."""
    found: Dict[str, str] = {}
    try:
        children = sorted(Path(root).expanduser().iterdir())
    except OSError:
        return found
    for child in children:
        m = _FOLDER.match(child.name)
        if m and child.is_dir():
            found.setdefault(m.group(1), m.group(1) + m.group(2))
    return found


def known_projects(*sources: Iterable[str]) -> Dict[str, str]:
    """Return ``{number: name}`` from project names such as ``0142RETKinase``."""
    found: Dict[str, str] = {}
    for source in sources:
        for name in source:
            m = re.match(r"\s*(\d{4})(\S*)", name or "")
            if m:
                found.setdefault(m.group(1), m.group(1) + m.group(2))
    return found


@dataclass
class Suggestion:
    """Free numbers for a new project, best first, and the projects they sit near."""

    name: str
    numbers: List[str]
    related: List[Tuple[str, str, List[str]]] = field(default_factory=list)
    reason: str = ""

    def line(self, number: str) -> str:
        near = ", ".join(n for n, _name, _w in self.related[:3])
        where = f", near {near}" if near else ""
        return f"Use {number}{camel(self.name)}{where}"


def camel(name: str) -> str:
    """Write a working name as a project name, ``RET kinase PROTAC`` as ``RETKinasePROTAC``."""
    parts = re.findall(r"[A-Za-z0-9]+", name or "")
    return "".join(p[:1].upper() + p[1:] for p in parts)


def _shares(word: str, other: str, tokens: set) -> bool:
    """Whether project name ``other`` holds ``word``.

    A word counts when it is one of the name's words, when it is four letters
    or more and appears anywhere in the name, as protac does in RETprotac, or
    when it starts the name, as ret does there.
    """
    low = other.lower()
    return (word in tokens or (len(word) >= 4 and word in low)
            or re.sub(r"^\d{4}", "", low).startswith(word))


def related(name: str, known: Dict[str, str], top: int = 6):
    """Return ``(number, name, shared words)`` of the projects most like ``name``.

    A shared word counts more the fewer projects hold it, so ``protac`` in two
    names says more than ``kinase`` in twenty, and the first word of the new
    name, usually its topic, counts double. Projects within three quarters of
    the best score are returned, best first.
    """
    mine = list(dict.fromkeys(distinctive(name)))
    if not mine or not known:
        return []
    tokens = {number: set(distinctive(other)) for number, other in known.items()}
    held = {w: sum(_shares(w, known[n], tokens[n]) for n in known) for w in mine}
    weight = {w: math.log((len(known) + 1) / (held[w] + 0.5)) for w in mine}
    weight[mine[0]] *= 2
    scored = []
    for number, other in known.items():
        shared = [w for w in mine if _shares(w, other, tokens[number])]
        if shared:
            scored.append((sum(weight[w] for w in shared), number, other, shared))
    if not scored:
        return []
    scored.sort(key=lambda s: (-s[0], s[1]))
    best = scored[0][0]
    return [(n, o, w) for score, n, o, w in scored if score >= 0.75 * best][:top]


def suggest(name: str, known: Dict[str, str], count: int = 3,
            active: Sequence[str] = ()) -> Suggestion:
    """Suggest free numbers for a new project called ``name``.

    With related projects, the free numbers inside their range come first,
    nearest the middle, then those just above it, then just below. Without
    any, the next free numbers after the highest number among the ``active``
    projects of the week, or among all known projects when none is given.
    """
    used = {int(n) for n in known} | {int(n) for n in active}
    near = related(name, known)
    if near:
        numbers = sorted(int(n) for n, _o, _w in near)
        low, high = numbers[0], numbers[-1]
        middle = numbers[len(numbers) // 2]
        inside = sorted((n for n in range(low, high + 1) if n not in used),
                        key=lambda n: (abs(n - middle), n))
        above = [n for n in range(high + 1, min(high + 60, 10000)) if n not in used]
        below = [n for n in range(low - 1, max(low - 60, -1), -1) if n not in used]
        choices = (inside + above + below)[:count]
        shared = list(dict.fromkeys(w for _n, _o, ws in near for w in ws))
        reason = (f"{len(near)} project{' shares' if len(near) == 1 else 's share'} "
                  f"{', '.join(shared)} with the new name")
    else:
        pool = [int(n) for n in active] or sorted(used)
        start = (max(pool) + 1) if pool else 1
        choices = [n for n in range(start, 10000) if n not in used][:count]
        reason = ("no project shares a distinctive word with the new name, so it "
                  "follows the highest number of this week's projects" if active else
                  "no project shares a distinctive word with the new name")
    return Suggestion(name, [f"{n:04d}" for n in choices], near, reason)


@dataclass
class Forming:
    """A word several tasks of one project share that its name does not hold."""

    code: str
    project: str
    word: str
    tasks: List[str]

    def sentence(self) -> str:
        examples = "; ".join(f"“{t}”" for t in self.tasks[:3])
        return (f"{len(self.tasks)} tasks of {self.code} {self.project} mention "
                f"“{self.word}”, which its name does not: {examples}. It may be "
                "a project of its own.")


def forming(tasks: Dict[str, Sequence[str]], projects: Dict[str, str],
            least: int = FORMING) -> List[Forming]:
    """Find projects with a cluster of tasks around a word the name lacks.

    ``tasks`` maps a code to the texts of its tasks and objectives, and
    ``projects`` maps a code to its project name.
    """
    out = []
    for code, texts in tasks.items():
        own = {_stem(w) for w in words(projects.get(code, ""))}
        counts: Dict[str, List[str]] = {}
        for text in dict.fromkeys(texts):
            seen = set()
            for w in re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", text):
                key = _stem(w.lower())
                if w.lower() in _COMMON or key in own or key in seen:
                    continue
                seen.add(key)
                counts.setdefault(w.lower(), []).append(text)
        best = sorted(((len(v), k) for k, v in counts.items() if len(v) >= least),
                      key=lambda x: (-x[0], x[1]))
        if best:
            word = best[0][1]
            out.append(Forming(code, projects.get(code, ""), word, counts[word]))
    return out


def facts(suggestion: Suggestion, found: Sequence[Forming]) -> str:
    lines = [f"New project: {suggestion.name}",
             f"Suggested numbers, best first: {', '.join(suggestion.numbers)}",
             f"Why: {suggestion.reason}"]
    lines += [f"Related project: {n} {o}, sharing {', '.join(w)}"
              for n, o, w in suggestion.related]
    lines += [f"Possible project forming: {f.sentence()}" for f in found]
    return "\n".join(lines)


def plain(suggestion: Suggestion, found: Sequence[Forming]) -> str:
    out = []
    if suggestion.related:
        near = ", ".join(o for _n, o, _w in suggestion.related)
        out.append(f"{suggestion.numbers[0]} is free and sits with the related "
                   f"projects {near}, because {suggestion.reason}.")
    elif suggestion.numbers:
        out.append(f"{suggestion.numbers[0]} is the next free number, because "
                   f"{suggestion.reason}.")
    out += [f.sentence() for f in found]
    return "\n\n".join(out)
