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

_GROUP = re.compile(r"(\d*)([A-Za-z][A-Za-z0-9]*)")

#: A project code: a capital followed by up to three capitals or digits, or a
#: single digit 0-9. The digits add ten one-character codes, which a table file
#: name can carry, so a legend can name 36 projects that fit a file name.
CODE_PATTERN = r"(?:[A-Z][A-Z0-9]{0,3}|[0-9])"
_LEGEND = re.compile(r"^(" + CODE_PATTERN + r")\s*:\s*(.*?)\s*$")
_TIME = re.compile(r"\d{1,2}:\s*\d{2}\s*-+\s*\d{1,2}:\s*\d{2}")


def _legend_match(cell: str):
    """Match a legend cell, but never a time such as ``5:00-06:30``."""
    m = _LEGEND.match((cell or "").strip())
    if m and m.group(1).isdigit() and _TIME.search(cell):
        return None
    return m
_RISK = re.compile(
    r"(?:\((safe|risky|support)\)|:(safe|risky|support):)\s*$", re.IGNORECASE
)
# The tag a writer types, and the risk class it names. The stored class keeps the
# name "speculative", which the schema and both dashboards use, while the tag in
# the table reads :risky:. Support is an activity category rather than a class,
# so a legacy support tag is stripped and names nothing.
TAG_TO_RISK = {"safe": "safe", "risky": "speculative"}

# A default activity in a legend description, as in "E: email @support". The
# scheduler reads the same tag, so a bare code in a cell takes this activity
# when the cell carries no activity letter of its own.
_ACTIVITY = re.compile(r"(?:^|\s)@(generative|editing|support)\b", re.IGNORECASE)


def split_legend_activity(desc: str):
    """Return ``(description without the tag, activity or None)``.

    The tag is a word such as ``@support`` anywhere in the description. Only
    the first tag counts, and the activity is returned in lowercase, so it is
    one of ``generative``, ``editing``, and ``support``.
    """
    m = _ACTIVITY.search(desc or "")
    if not m:
        return desc, None
    rest = (desc[:m.start()] + desc[m.end():]).strip()
    return re.sub(r"[ \t]{2,}", " ", rest), m.group(1).lower()


def legend_activity(cell: str):
    """Return the default activity named in a legend cell, or ``None``."""
    m = _legend_match(cell)
    if not m:
        return None
    return split_legend_activity(m.group(2))[1]


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
                elif ch.isupper() or ch.isdigit():
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
        if not (isinstance(project, str) and len(project) == 1
                and ("A" <= project <= "Z" or "0" <= project <= "9")):
            raise ValueError(
                f"project must be one uppercase letter or one digit, got {project!r}")
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
    stripped and names nothing, because support is an activity. A default
    activity tag such as ``@support`` is stripped too; read it with
    :func:`legend_activity`.

    Callers that hold the table in memory, such as the graphical editor, use
    this rather than re-implementing the pattern, so one rule governs both.
    """
    m = _legend_match(cell)
    if not m:
        return None
    code, desc = m.group(1), m.group(2)
    # The activity tag goes first, so a risk tag written after it, as in
    # "email @support :safe:", is still at the end when the risk is read.
    desc, _activity = split_legend_activity(desc)
    risk = None
    tag_match = _RISK.search(desc)
    if tag_match:
        tag = (tag_match.group(1) or tag_match.group(2)).lower()
        desc = _RISK.sub("", desc).strip()
        risk = TAG_TO_RISK.get(tag)
    return code, desc, risk


def read_legend(table_path: str) -> dict:
    """Return {code: (description, risk_class or None)} from a weekly org table.

    Only the first org table of the file is read, which is the week itself.

    A code defined twice keeps its first definition, which is what the plan
    importer sees, because the scheduler's ``legend_lookup`` returns the first
    matching entry in the manner of elisp ``assoc``. Reading the last definition
    here would let one table give two different descriptions for one project,
    depending on which command read it.
    """
    legend: dict = {}
    seen_table = False
    for raw in Path(table_path).read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s.startswith("|"):
            # Only the first table is the week, as the scheduler reads it. The
            # semester project lists that may follow are not its legend.
            if seen_table:
                break
            continue
        seen_table = True
        if set(s) <= set("|-+ "):  # skip rules
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


# -- project name and deadline ---------------------------------------------
#
# A legend description holds the project name and, optionally, a deadline as
# an ISO date at its end, as in ``Z: 1008ToolsForQCrOfRNA 2026-10-05 :safe:``.
# The scheduler and the Emacs port read the description as free text, so the
# date travels with it unchanged, and only this package splits it in two.

_ISO_TAIL = re.compile(r"(?:,\s*|\s+)(\d{4}-\d{2}-\d{2})\s*$")
_PROJECT_TOKEN = re.compile(r"(?<![0-9A-Za-z])[0-9]{4}[A-Za-z][\w\-]*")
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oc": 10, "nov": 11, "dec": 12,
}
_LOOSE_DATE = re.compile(
    r"(?P<lead>(?:submitted|sent)\s+)?(?:(?:due|by|before)\s*:?\s*)?"
    r"(?:(?P<iso>\d{4}-\d{2}-\d{2})"
    r"|(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oc|nov|dec)[a-z]*\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(?P<year>\d{4})(?![0-9A-Za-z]))?"
    r"|(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{2,4}))?)",
    re.IGNORECASE)


def split_deadline(description: str):
    """Return ``(project, deadline or None)`` for a legend description.

    The deadline is an ISO date ``YYYY-MM-DD`` at the end of the description.
    Text in any other shape stays in the project name, so nothing is lost.
    """
    text = (description or "").strip()
    match = _ISO_TAIL.search(text)
    if match:
        return text[:match.start()].rstrip(" ,"), match.group(1)
    return text.rstrip(" ,"), None


def join_deadline(project: str, deadline) -> str:
    """Return the description that :func:`split_deadline` splits back apart."""
    project = (project or "").strip().rstrip(" ,")
    deadline = (deadline or "").strip()
    return f"{project} {deadline}".strip() if deadline else project


def valid_deadline(text: str) -> bool:
    """Whether ``text`` is empty or a real calendar date as ``YYYY-MM-DD``."""
    from datetime import date

    text = (text or "").strip()
    if not text:
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _resolve(match, reference):
    """Turn a loose date match into a date, guessing the year from ``reference``.

    A month and day with no year takes the reference year, unless that puts it
    more than about two months before the reference, in which case it is read
    as next year. So in October, ``March 1`` means next March and
    ``Sep 16`` means last month.
    """
    from datetime import date, timedelta

    if match.group("iso"):
        try:
            return date.fromisoformat(match.group("iso"))
        except ValueError:
            return None
    if match.group("mon"):
        month = _MONTHS[match.group("mon").lower()[:3] if match.group("mon").lower()[:2] != "oc"
                        else "oc"]
        day, year = int(match.group("day")), match.group("year")
    else:
        month, day, year = int(match.group("m")), int(match.group("d")), match.group("y")
        if year and len(year) == 2:
            year = "20" + year
    try:
        if year:
            return date(int(year), month, day)
        guess = date(reference.year, month, day)
    except ValueError:
        return None
    if guess < reference - timedelta(days=62):
        try:
            guess = date(reference.year + 1, month, day)
        except ValueError:
            return None
    return guess


def tidy_description(description: str, reference=None):
    """Propose ``(project, deadline, dropped)`` for a free-text description.

    The project is every project directory name in the text, such as
    ``1008ToolsForQCrOfRNA``, joined with ``, `` when there are two. A
    description that names none keeps its text before the first comma. The
    deadline is the last date in the text, written as ``YYYY-MM-DD``. A date
    led by ``submitted`` or ``sent`` records something done, not a deadline,
    so it is not used. ``dropped`` is the text that fits neither part, returned
    so a writer can see what the change would remove.
    """
    from datetime import date

    reference = reference or date.today()
    text = (description or "").strip()
    already = split_deadline(text)
    if already[1] and not _LOOSE_DATE.search(already[0]) and (
            _PROJECT_TOKEN.fullmatch(already[0]) or "," not in already[0]):
        return already[0], already[1], ""

    deadline = None
    chosen = None
    rest = text
    for match in _LOOSE_DATE.finditer(text):
        if match.group("lead"):
            continue
        found = _resolve(match, reference)
        if found is not None:
            deadline, chosen = found.isoformat(), match
    projects = _PROJECT_TOKEN.findall(text)
    if projects:
        project = ", ".join(dict.fromkeys(projects))
        for token in projects:
            rest = rest.replace(token, " ")
    else:
        head = text.split(",")[0]
        cut = _LOOSE_DATE.search(head)
        project = (head[:cut.start()] if cut else head).strip()
        rest = rest[len(project):]
    if chosen is not None:
        rest = rest.replace(chosen.group(0), " ")
    dropped = re.sub(r"\s+", " ", re.sub(r"(?:\s*,\s*)+", ", ", rest)).strip(" ,")
    return project, deadline, dropped
