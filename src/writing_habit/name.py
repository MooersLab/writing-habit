"""Decode a schedule file-name code into the week it represents.

The code names a weekly table file, for example ``4gAAeAsA-gWW.org``. See
``docs/table-file-naming-rules.org`` for the full specification. The grammar:

    schedule = daygroup { "-" daygroup }
    daygroup = [count] pattern
    pattern  = "o" | run+
    run      = activity project+
    activity = g | e | s          (generative, editing, support)
    project  = A..Z               (single-letter code, one letter is one block)
    count    = digits             (consecutive days, >= 1, a leading 1 is omitted)

This module decodes a code to a list of days, encodes a week back into its
canonical code, and checks the project letters against a weekly table legend.
It uses the standard library only.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ACT = {"g": "generative", "e": "editing", "s": "support"}

_GROUP = re.compile(r"(\d*)([A-Za-z]+)")
_LEGEND = re.compile(r"^([A-Z][A-Z0-9]{0,3})\s*:\s*(.*?)\s*$")
_RISK = re.compile(
    r"(?:\((safe|risky|support)\)|:(safe|risky|support):)\s*$", re.IGNORECASE
)
# The tag a writer types, and the risk class it names. The stored class keeps the
# name "speculative", which the schema and both dashboards use, while the tag in
# the table reads :risky:. Support is an activity category rather than a class,
# so a legacy support tag is stripped and names nothing.
TAG_TO_RISK = {"safe": "safe", "risky": "speculative"}


def decode(code: str):
    """Return a list of (day_name, [(activity, project), ...]) for the week."""
    days: list[list[tuple[str, str]]] = []
    for grp in code.split("-"):
        m = _GROUP.fullmatch(grp)
        if not m:
            raise ValueError(f"invalid day-group {grp!r}")
        n = int(m.group(1) or 1)
        pat = m.group(2)
        if pat == "o":
            blocks: list[tuple[str, str]] = []
        else:
            blocks, act = [], None
            for ch in pat:
                if ch in ACT:
                    act = ch
                elif ch.isupper():
                    if act is None:
                        raise ValueError(f"project {ch!r} before any activity in {grp!r}")
                    blocks.append((ACT[act], ch))
                else:
                    raise ValueError(f"invalid character {ch!r} in {grp!r}")
        days += [blocks] * n
    if not days:
        raise ValueError("empty schedule code")
    if len(days) > 7:
        raise ValueError(f"schedule covers {len(days)} days, more than a week")
    return [(DAYS[i], b) for i, b in enumerate(days)]


def format_week(decoded) -> str:
    lines = []
    for day, blocks in decoded:
        if not blocks:
            lines.append(f"  {day}  open")
        else:
            lines.append(f"  {day}  " + ", ".join(f"{a} {p}" for a, p in blocks))
    return "\n".join(lines)


_ACT_CODE = {full: short for short, full in ACT.items()}


def encode_day(blocks) -> str:
    """Return the day-pattern for one day, for example ``gAAeAsA`` or ``o``.

    ``blocks`` is a sequence of ``(activity, project)`` pairs in the order the
    blocks occur across the day, which by convention runs from generative
    through editing to support. The activity is either a full name such as
    ``generative`` or its letter ``g``.

    A run covers consecutive blocks that share both the activity and the
    project, so three support blocks on project B give ``sBBB``. A change of
    project opens a new run and repeats the activity letter, so support work on
    B, then C, then D reads ``sBBBsCCCsD`` rather than ``sBBBCCCD``. The
    decoder accepts both spellings, and the repeated activity letter is the
    canonical one because it keeps each project visible in the file name.
    """
    if not blocks:
        return "o"
    out: list[str] = []
    current = None
    for block in blocks:
        try:
            activity, project = block
        except (TypeError, ValueError):
            raise ValueError(f"invalid block {block!r}") from None
        short = _ACT_CODE.get(activity, activity if activity in ACT else None)
        if short is None:
            raise ValueError(f"unknown activity {activity!r}")
        if not (isinstance(project, str) and len(project) == 1 and "A" <= project <= "Z"):
            raise ValueError(f"project must be one uppercase letter, got {project!r}")
        if (short, project) != current:
            out.append(short)
            current = (short, project)
        out.append(project)
    return "".join(out)


def encode(week) -> str:
    """Return the canonical schedule code for ``week``.

    ``week`` is either the list of ``(day_name, blocks)`` pairs that
    :func:`decode` returns or a bare sequence of block lists, one per day,
    filled from Monday. Each day is spelled by :func:`encode_day`, so a change
    of project repeats the activity letter. The rest of the canonical spelling
    follows
    ``docs/table-file-naming-rules.org``. Every maximal run of identical
    consecutive days collapses into one group carrying the day count, a count
    of one is omitted, and trailing open days are dropped because they are
    implied. Days that share a pattern without being adjacent are written out
    again, so a Monday, Wednesday, Friday week reads ``gA-o-gA-o-gA``.

    The function is the inverse of :func:`decode` for every canonical code, so
    ``encode(decode(code)) == code`` holds whenever ``code`` is canonical.
    """
    days = list(week)
    if not days:
        raise ValueError("empty week")
    if len(days) > 7:
        raise ValueError(f"week covers {len(days)} days, more than a week")

    patterns: list[str] = []
    for day in days:
        blocks = day
        if isinstance(day, tuple) and len(day) == 2 and isinstance(day[0], str):
            blocks = day[1]
        patterns.append(encode_day(blocks))

    while patterns and patterns[-1] == "o":   # trailing open days are implied
        patterns.pop()
    if not patterns:                          # a week with no blocks at all
        return "o"

    groups: list[str] = []
    run = 1
    for i, pattern in enumerate(patterns):
        if i + 1 < len(patterns) and patterns[i + 1] == pattern:
            run += 1
            continue
        groups.append(f"{run}{pattern}" if run > 1 else pattern)
        run = 1
    return "-".join(groups)


def summary(decoded):
    """Return (total_blocks, activity_counts, project_counts)."""
    act, proj = Counter(), Counter()
    for _, blocks in decoded:
        for a, p in blocks:
            act[a] += 1
            proj[p] += 1
    return sum(act.values()), act, proj


def parse_legend_cell(cell: str):
    """Return ``(code, description, risk_class)`` for a legend cell, or ``None``.

    A legend row carries the code and the description in its first cell, for
    example ``| A: DNPH1 docking :safe: | | | |``. A trailing risk tag in either
    the ``:safe:`` or the ``(safe)`` form is stripped from the description. Two
    tags name a class, namely ``safe`` and ``risky``, and ``risky`` names the
    class the database calls ``speculative``. A legacy ``support`` tag is
    stripped and names nothing, because support is an activity.

    Callers that hold the table in memory, such as the graphical editor, use
    this rather than re-implementing the pattern, so one rule governs both.
    """
    m = _LEGEND.match(cell.strip())
    if not m:
        return None
    code, desc = m.group(1), m.group(2)
    risk = None
    tag_match = _RISK.search(desc)
    if tag_match:
        tag = (tag_match.group(1) or tag_match.group(2)).lower()
        desc = _RISK.sub("", desc).strip()
        risk = TAG_TO_RISK.get(tag)
    return code, desc, risk


def read_legend(table_path: str) -> dict:
    """Return {code: (description, risk_class or None)} from a weekly org table.

    A code defined twice keeps its first definition, which is what the plan
    importer sees, because the scheduler's ``legend_lookup`` returns the first
    matching entry in the manner of elisp ``assoc``. Reading the last definition
    here would let one table give two different descriptions for one project,
    depending on which command read it.
    """
    legend: dict = {}
    for raw in Path(table_path).read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s.startswith("|") or set(s) <= set("|-+ "):  # skip non-rows and rules
            continue
        first = s.strip("|").split("|")[0].strip()
        parsed = parse_legend_cell(first)
        if parsed is None:
            continue
        code, desc, risk = parsed
        legend.setdefault(code, (desc, risk))
    return legend


def check_against_legend(decoded, legend):
    """Match each project letter to a legend entry.

    Returns (rows, problems). Each row is
    (letter, matched_code, description, risk, status) where status is one of
    ``exact``, ``alias``, ``ambiguous``, or ``unknown``. ``problems`` lists the
    letters that did not resolve to exactly one legend entry.
    """
    letters = []
    for _, blocks in decoded:
        for _, p in blocks:
            if p not in letters:
                letters.append(p)
    rows, problems = [], []
    for letter in letters:
        if letter in legend:
            desc, risk = legend[letter]
            rows.append((letter, letter, desc, risk, "exact"))
            continue
        prefix = [c for c in legend if c and c[0] == letter]
        if len(prefix) == 1:
            desc, risk = legend[prefix[0]]
            rows.append((letter, prefix[0], desc, risk, "alias"))
        elif len(prefix) > 1:
            rows.append((letter, "/".join(sorted(prefix)), "", None, "ambiguous"))
            problems.append(letter)
        else:
            rows.append((letter, "-", "", None, "unknown"))
            problems.append(letter)
    return rows, problems
