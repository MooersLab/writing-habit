"""Import actual sessions from the tracking CSV template.

Columns: date, start, end, minutes, project_code, category, note.
Enter either a start and end time, or a minutes value. When only minutes are
present, which is the paper-then-transcribe path, the times stay empty.
This importer uses the standard library only, so Excel and Google Sheets are
supported through their CSV export without any extra dependency.
"""

from __future__ import annotations

import csv

from ..db import get_category_id, get_or_create_project, log_import, minutes_between


def import_csv(con, path: str) -> int:
    """Insert one session per data row. Returns the number inserted."""
    rows_read = 0
    inserted = 0
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for line_no, row in enumerate(reader, start=2):  # header is line 1
            day = (row.get("date") or "").strip()
            if not day:
                continue
            rows_read += 1
            start = (row.get("start") or "").strip() or None
            end = (row.get("end") or "").strip() or None
            minutes = (row.get("minutes") or "").strip()
            code = (row.get("project_code") or "").strip()
            category = (row.get("category") or "").strip() or None
            note = (row.get("note") or "").strip() or None

            if not code:
                raise ValueError(f"{path} row {line_no}: project_code is required")
            if minutes:
                actual = int(minutes)
            elif start and end:
                actual = minutes_between(start, end)
            else:
                raise ValueError(
                    f"{path} row {line_no}: give minutes, or both start and end"
                )

            cat_id = get_category_id(con, category)
            if category and cat_id is None:
                raise ValueError(f"{path} row {line_no}: unknown category {category!r}")
            pid = get_or_create_project(con, code)
            con.execute(
                "INSERT INTO session(day, start_time, end_time, actual_min,"
                " project_id, category_id, source, source_ref, note)"
                " VALUES (?, ?, ?, ?, ?, ?, 'csv', ?, ?)",
                (day, start, end, actual, pid, cat_id, f"{path}:{line_no}", note),
            )
            inserted += 1
    con.commit()
    log_import(con, "csv", path, rows_read, inserted, note="track import")
    return inserted
