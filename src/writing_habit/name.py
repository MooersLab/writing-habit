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

This module decodes a code to a list of days and checks the project letters
against a weekly table legend. It uses the standard library only.
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
    r"(?:\((safe|speculative|support)\)|:(safe|speculative|support):)\s*$", re.IGNORECASE
)


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


def summary(decoded):
    """Return (total_blocks, activity_counts, project_counts)."""
    act, proj = Counter(), Counter()
    for _, blocks in decoded:
        for a, p in blocks:
            act[a] += 1
            proj[p] += 1
    return sum(act.values()), act, proj


def read_legend(table_path: str) -> dict:
    """Return {code: (description, risk_class or None)} from a weekly org table.

    A legend row has the code and description in its first cell, for example
    ``| A: DNPH1 docking :safe: | | | |``. A trailing risk tag is stripped.
    """
    legend: dict = {}
    for raw in Path(table_path).read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s.startswith("|") or set(s) <= set("|-+ "):  # skip non-rows and rules
            continue
        first = s.strip("|").split("|")[0].strip()
        m = _LEGEND.match(first)
        if not m:
            continue
        code, desc = m.group(1), m.group(2)
        risk = None
        rt = _RISK.search(desc)
        if rt:
            risk = (rt.group(1) or rt.group(2)).lower()
            desc = _RISK.sub("", desc).strip()
        legend[code] = (desc, risk)
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
