"""Import actual sessions from an ICS calendar of real work blocks.

Convention: keep actuals in their own calendar so plan and actual never mix.
Put the legend code in the event summary in brackets, for example
``[A] DNPH1 docking``, and put the activity in the CATEGORIES field, for
example ``generative``. DTSTART and DTEND give the real minutes.

This reader needs the optional ``icalendar`` dependency. Install it with
``pip install writing-habit[ics]``.
"""

from __future__ import annotations

import re

from ..db import get_category_id, get_or_create_project, log_import

_CODE_IN_SUMMARY = re.compile(r"\[([A-Z][A-Z0-9]{0,3})\]")


def import_ics(con, path: str) -> int:
    try:
        from icalendar import Calendar
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on extra
        raise SystemExit(
            "ICS import needs the optional dependency. Run: pip install 'writing-habit[ics]'"
        ) from exc

    with open(path, "rb") as fh:
        cal = Calendar.from_ical(fh.read())

    rows_read = 0
    inserted = 0
    for comp in cal.walk("VEVENT"):
        rows_read += 1
        summary = str(comp.get("summary", ""))
        m = _CODE_IN_SUMMARY.search(summary)
        if not m:
            continue
        code = m.group(1)
        start = comp.get("dtstart").dt
        end = comp.get("dtend").dt
        actual = int((end - start).total_seconds() // 60)
        cats = comp.get("categories")
        category = None
        if cats is not None:
            first = str(cats.to_ical().decode() if hasattr(cats, "to_ical") else cats)
            category = first.split(",")[0].strip().lower() or None
        cat_id = get_category_id(con, category)
        pid = get_or_create_project(con, code)
        con.execute(
            "INSERT INTO session(day, start_time, end_time, actual_min,"
            " project_id, category_id, source, source_ref, note)"
            " VALUES (?, ?, ?, ?, ?, ?, 'ics', ?, ?)",
            (
                start.date().isoformat(),
                start.strftime("%H:%M"),
                end.strftime("%H:%M"),
                actual,
                pid,
                cat_id,
                str(comp.get("uid", "")),
                summary,
            ),
        )
        inserted += 1
    con.commit()
    log_import(con, "ics", path, rows_read, inserted, note="track import")
    return inserted
