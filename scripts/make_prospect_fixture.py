"""Write the cross-port risky-prospecting fixture: a database and its dashboard.

    PYTHONPATH=src python3 scripts/make_prospect_fixture.py tests/fixtures

writes ``prospect.db`` and ``prospect.html``. Copy both into the Emacs Lisp
twin's ``test/fixtures`` so the two ports assert against one render. The
database is built with plain inserts rather than a sync, so it holds no
machine-specific path.
"""

from __future__ import annotations

import sys
from pathlib import Path

from writing_habit import db
from writing_habit.dashboard import dashboard_html

WEEK = "2026-10-19"
TODAY = "2026-10-26"


def build(path: Path) -> None:
    if path.exists():
        path.unlink()
    con = db.connect(str(path))
    db.init_db(con)
    gen = db.get_category_id(con, "generative")
    edit = db.get_category_id(con, "editing")
    z = db.get_or_create_project(con, "Z", "1008ToolsForQCrOfRNA", "safe")
    x = db.get_or_create_project(con, "X", "0436mpQCr", "speculative")
    p = db.get_or_create_project(con, "1424AIseededPhasing", "1424AIseededPhasing")
    q = db.get_or_create_project(con, "3275emacsconf", "3275emacsconf & <talk>")
    con.execute("INSERT INTO plan_week(week_start, schedule_code) VALUES (?, ?)", (WEEK, "Oct19"))
    blocks = [("2026-10-19", "05:30", "07:00", z, gen), ("2026-10-20", "05:30", "07:00", z, edit),
              ("2026-10-21", "05:30", "06:30", x, gen)]
    con.executemany("INSERT INTO plan_block(day, start_time, end_time, project_id, category_id)"
                    " VALUES (?, ?, ?, ?, ?)", blocks)
    sessions = [
        ("2026-10-19", "05:30", "07:00", 90, z, gen, 0),
        ("2026-10-20", "05:30", "06:30", 60, z, edit, 0),
        ("2026-10-21", "05:30", "06:15", 45, x, gen, 0),
        # Prospecting on 1424 in three weeks running, so it reads as stale.
        ("2026-10-05", "08:00", "09:00", 60, p, None, 1),
        ("2026-10-13", "08:00", "08:30", 30, p, None, 1),
        ("2026-10-22", "08:00", "09:30", 90, p, gen, 1),
        ("2026-10-23", "08:00", "08:45", 45, p, None, 1),
        ("2026-10-24", "10:00", "10:40", 40, q, gen, 1),
    ]
    con.executemany(
        "INSERT INTO session(day, start_time, end_time, actual_min, project_id, category_id,"
        " source, prospecting) VALUES (?, ?, ?, ?, ?, ?, 'manual', ?)", sessions)
    con.commit()
    con.execute("VACUUM")
    con.close()


def main(out_dir: str) -> None:
    out = Path(out_dir)
    build(out / "prospect.db")
    con = db.connect(str(out / "prospect.db"))
    html = dashboard_html(con, WEEK, today=TODAY)
    con.close()
    (out / "prospect.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures")
