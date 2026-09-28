"""Load a weekly plan into plan_block using the real writing-schedule parser.

This module calls ``writing_schedule.parse_text``, the same parser the schedule
module uses, so the plan and the schedule can never drift into two dialects.
The writing-schedule dependency is imported lazily inside :func:`import_org`,
so the rest of the toolkit (initdb, track, compare) runs without it installed.

Risk tags. The base writing-schedule legend maps a code to a description, for
example ``A: DNPH1 docking``. To give the barbell view a class to group on,
add a risk tag at the end of the description in either the org-tag form
``:safe:`` or the parenthesis form ``(safe)``. The two risk classes are ``safe``
and ``speculative``. Support is an activity category, not a risk class, so a
legacy ``:support:`` tag is stripped but records no risk class. The tag is
stripped before the description is stored, so it never pollutes the project name.
"""

from __future__ import annotations

import re
import sys
from datetime import timedelta
from pathlib import Path

from .db import get_category_id, get_or_create_project, log_import

# writing-schedule section header -> our activity category.
SECTION_TO_CATEGORY = {
    "generative": "generative",
    "generating": "generative",
    "writing": "generative",     # the writing-schedule default section name
    "rewriting": "editing",
    "editing": "editing",
    "revising": "editing",
    "revision": "editing",
    "supporting": "support",
    "support": "support",
}

# A trailing risk tag in either :safe: or (safe) form. The regex still matches a
# legacy support tag so it can be stripped, but only safe and speculative name a
# risk class (see _split_risk).
RISK_TAG = re.compile(
    r"(?:\((?P<paren>safe|risky|support)\)"
    r"|:(?P<colon>safe|risky|support):)\s*$",
    re.IGNORECASE,
)

# The tag a writer types, and the risk class it names. The stored class keeps the
# name "speculative", which the schema and both dashboards use. Support is an
# activity category rather than a class, so it names nothing.
TAG_TO_RISK = {"safe": "safe", "risky": "speculative"}


def _split_risk(description: str | None) -> tuple[str | None, str | None]:
    """Return (clean_description, risk_class) from a legend description.

    The trailing risk tag is stripped from the description. Two tags name a
    class, namely safe and risky, and risky names the class the database calls
    speculative. A legacy support tag is stripped as well but names nothing,
    because support is an activity category.
    """
    if not description:
        return None, None
    m = RISK_TAG.search(description)
    if not m:
        return description.strip() or None, None
    tag = (m.group("paren") or m.group("colon")).lower()
    clean = RISK_TAG.sub("", description).strip()
    risk = TAG_TO_RISK.get(tag)
    return clean or None, risk


def _schedule_code(path: str) -> str:
    """Derive the schedule file-name code from a table PATH.

    Strips the directory and the ``.org`` extension, and an optional leading ISO
    date prefix, so ``2026-01-19_4gAAeAsA-gWW.org`` yields ``4gAAeAsA-gWW`` and a
    plain ``my-week.org`` yields ``my-week``.
    """
    stem = Path(path).stem
    m = re.match(r"^\d{4}-\d{2}-\d{2}[_-](.+)$", stem)
    return m.group(1) if m else stem


def _category_for(section: str, unknown: set[str]) -> str:
    name = SECTION_TO_CATEGORY.get(section.strip().lower())
    if name is None:
        unknown.add(section)
        return "generative"
    return name


def import_org(con, path: str, week: str) -> int:
    """Parse the weekly table at ``path`` for the week containing ``week``.

    Returns the number of plan_block rows for that week.
    """
    try:
        from writing_schedule import parse_text, week_monday
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on the dep
        raise SystemExit(
            "plan import needs the writing-schedule package. Install it from its "
            "checkout, for example: pip install -e "
            "/Users/blaine/6112MooersLabGitHubLabRepos/writing-schedule-py/writing_schedule"
        ) from exc

    text = Path(path).read_text(encoding="utf-8")
    parsed = parse_text(text)
    monday = week_monday(week)

    unknown_sections: set[str] = set()
    for ev in parsed.events:
        desc, risk = _split_risk(parsed.legend_lookup(ev.letter))
        pid = get_or_create_project(con, ev.letter, desc, risk)
        cat_id = get_category_id(con, _category_for(ev.section, unknown_sections))
        day = (monday + timedelta(days=ev.offset)).isoformat()
        con.execute(
            "INSERT OR IGNORE INTO plan_block"
            "(day, start_time, end_time, project_id, category_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (day, ev.start, ev.end, pid, cat_id),
        )
    # Record which schedule file produced this week, for the grouping dashboard.
    con.execute(
        "INSERT OR REPLACE INTO plan_week(week_start, schedule_code, table_path)"
        " VALUES (?, ?, ?)",
        (monday.isoformat(), _schedule_code(path), path),
    )
    con.commit()

    count = con.execute(
        "SELECT COUNT(*) AS n FROM plan_block WHERE week_start = ?",
        (monday.isoformat(),),
    ).fetchone()["n"]
    log_import(con, "org", path, len(parsed.events), count, note="plan import")

    if unknown_sections:
        print(
            "warning: sections mapped to generative by default: "
            + ", ".join(sorted(unknown_sections)),
            file=sys.stderr,
        )
    return count
