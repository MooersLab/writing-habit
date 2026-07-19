"""Command-line interface tying the three modules together.

    writing-habit initdb   --db habit.db
    writing-habit plan      import my-week.org --week 2026-01-19 --db habit.db
    writing-habit track     import actuals.csv --format csv        --db habit.db
    writing-habit track     add --day 2026-01-19 --project A --minutes 75 --category generative --db habit.db
    writing-habit compare   --week 2026-01-19 --db habit.db [--plot out.png]
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, db
from .compare import report
from .plan_import import import_org
from .track import csv_actuals, manual


def _add_db(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", required=True, help="path to the SQLite database")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="writing-habit", description=__doc__)
    parser.add_argument("--version", action="version", version=f"writing-habit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("initdb", help="create the schema and seed activities")
    _add_db(p_init)

    p_plan = sub.add_parser("plan", help="planning operations")
    plan_sub = p_plan.add_subparsers(dest="plan_command", required=True)
    p_plan_import = plan_sub.add_parser("import", help="load a weekly org table")
    p_plan_import.add_argument("path", help="the weekly org table")
    p_plan_import.add_argument("--week", required=True, help="any date in the target week")
    _add_db(p_plan_import)

    p_track = sub.add_parser("track", help="tracking operations")
    track_sub = p_track.add_subparsers(dest="track_command", required=True)
    p_track_import = track_sub.add_parser("import", help="load actual sessions")
    p_track_import.add_argument("path", help="the actuals file")
    p_track_import.add_argument("--format", choices=["csv", "ics"], default="csv")
    _add_db(p_track_import)
    p_track_add = track_sub.add_parser("add", help="add one session by hand")
    p_track_add.add_argument("--day", required=True)
    p_track_add.add_argument("--project", required=True)
    p_track_add.add_argument("--minutes", type=int)
    p_track_add.add_argument("--category")
    p_track_add.add_argument("--start")
    p_track_add.add_argument("--end")
    p_track_add.add_argument("--note")
    _add_db(p_track_add)

    p_cmp = sub.add_parser("compare", help="print the planned versus actual report")
    p_cmp.add_argument("--week", required=True, help="any date in the target week")
    p_cmp.add_argument("--plot", help="also write a bar chart to this path")
    _add_db(p_cmp)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    con = db.connect(args.db)

    if args.command == "initdb":
        db.init_db(con)
        print(f"Initialized {args.db}")
        return 0

    if args.command == "plan" and args.plan_command == "import":
        n = import_org(con, args.path, args.week)
        print(f"Imported {n} planned blocks from {args.path}")
        return 0

    if args.command == "track" and args.track_command == "import":
        if args.format == "csv":
            n = csv_actuals.import_csv(con, args.path)
        else:
            from .track import ics_actuals
            n = ics_actuals.import_ics(con, args.path)
        print(f"Imported {n} sessions from {args.path}")
        return 0

    if args.command == "track" and args.track_command == "add":
        sid = manual.add_session(
            con,
            day=args.day,
            project_code=args.project,
            minutes=args.minutes,
            category=args.category,
            start=args.start,
            end=args.end,
            note=args.note,
        )
        print(f"Added session {sid}")
        return 0

    if args.command == "compare":
        print(report.render_week(con, args.week))
        if args.plot:
            report.write_plot(con, args.week, args.plot)
            print(f"\nWrote plot to {args.plot}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
