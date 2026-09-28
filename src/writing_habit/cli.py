"""Command-line interface tying the three modules together.

    writing-habit initdb   --db habit.db
    writing-habit plan      import my-week.org --week 2026-01-19 --db habit.db
    writing-habit track     import actuals.csv --format csv        --db habit.db
    writing-habit track     add --day 2026-01-19 --project A --minutes 75 --category generative --db habit.db
    writing-habit compare   --week 2026-01-19 --db habit.db [--plot out.png]
    writing-habit dashboard --week 2026-01-19 --out week.html --db habit.db
    writing-habit history   --db habit.db [--from 2026-01-01] [--to 2026-06-30] [--plot trend.png]
    writing-habit context   set --week 2026-03-16 --tag teaching --db habit.db
    writing-habit seasons   --out seasons.html --db habit.db
    writing-habit name      4gAAeAsA-gWW [--table my-week.org]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, db
from . import name as namecmd
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

    p_dash = sub.add_parser(
        "dashboard", help="write the single-week HTML dashboard"
    )
    p_dash.add_argument("--week", required=True, help="any date in the target week")
    p_dash.add_argument("--out", required=True, help="output HTML path")
    _add_db(p_dash)

    p_hist = sub.add_parser(
        "history", help="cross-week adherence tracker: text series and optional plots"
    )
    p_hist.add_argument("--from", dest="start", help="earliest week, any date in it (optional)")
    p_hist.add_argument("--to", dest="end", help="latest week, any date in it (optional)")
    p_hist.add_argument(
        "--plot", help="also write the five weekly adherence plots to this PNG path"
    )
    _add_db(p_hist)

    p_ctx = sub.add_parser("context", help="tag a week with an event context")
    ctx_sub = p_ctx.add_subparsers(dest="context_command", required=True)
    p_ctx_set = ctx_sub.add_parser("set", help="attach a tag to a week")
    p_ctx_set.add_argument("--week", required=True, help="any date in the target week")
    p_ctx_set.add_argument("--tag", required=True, help="for example teaching, meeting, data-collection")
    p_ctx_set.add_argument("--note")
    _add_db(p_ctx_set)
    p_ctx_clear = ctx_sub.add_parser("clear", help="remove a tag, or all tags, from a week")
    p_ctx_clear.add_argument("--week", required=True)
    p_ctx_clear.add_argument("--tag", help="omit to clear every tag on the week")
    _add_db(p_ctx_clear)
    p_ctx_list = ctx_sub.add_parser("list", help="list context tags")
    p_ctx_list.add_argument("--week", help="omit to list every week")
    _add_db(p_ctx_list)

    p_seasons = sub.add_parser(
        "seasons",
        help="write the grouped-adherence dashboard, by month, context, and schedule",
    )
    p_seasons.add_argument("--out", required=True, help="output HTML path")
    _add_db(p_seasons)

    p_name = sub.add_parser(
        "name", help="decode a schedule file-name code and check it against a table legend"
    )
    p_name.add_argument("code", help="schedule code, for example 4gAAeAsA-gWW")
    p_name.add_argument(
        "--table",
        help="weekly org table whose legend the project letters are checked against; "
        "defaults to <code>.org in the current directory when present",
    )

    return parser


def _run_name(args) -> int:
    try:
        decoded = namecmd.decode(args.code)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Schedule {args.code}")
    print(namecmd.format_week(decoded))

    total, act, proj = namecmd.summary(decoded)
    order = [namecmd.ACT[k] for k in ("g", "e", "s")]
    by_act = ", ".join(f"{act.get(a, 0)} {a}" for a in order)
    by_proj = ", ".join(f"{p} ({proj[p]})" for p in sorted(proj))
    print(f"\n{total} blocks over {len(decoded)} days: {by_act}")
    if by_proj:
        print(f"projects used: {by_proj}")

    table = args.table
    if table is None:
        guess = Path(f"{args.code}.org")
        if guess.exists():
            table = str(guess)
    if table is None:
        return 0

    legend = namecmd.read_legend(table)
    rows, problems = namecmd.check_against_legend(decoded, legend)
    print(f"\nLegend check against {table}:")
    for letter, code, desc, risk, status in rows:
        rk = f" [{risk}]" if risk else ""
        detail = f"{code}  {desc}{rk}".rstrip()
        print(f"  {letter} -> {detail:<40} {status}")
    if problems:
        print(
            f"\n{len(problems)} project letter(s) not resolved to a legend entry: "
            + ", ".join(problems),
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "name":       # needs no database
        return _run_name(args)

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

    if args.command == "dashboard":
        from . import dashboard
        dashboard.write_dashboard(con, args.week, args.out)
        print(f"Wrote dashboard to {args.out}")
        return 0

    if args.command == "history":
        from .compare import history
        print(history.render_text(con, args.start, args.end))
        if args.plot:
            history.write_plots(con, args.plot, args.start, args.end)
            print(f"\nWrote plots to {args.plot}")
        return 0

    if args.command == "context":
        from . import context as ctxmod
        if args.context_command == "set":
            ctxmod.set_tag(con, args.week, args.tag, args.note)
            print(f"Tagged the week of {args.week} with {args.tag}")
        elif args.context_command == "clear":
            n = ctxmod.clear_tag(con, args.week, args.tag)
            print(f"Cleared {n} tag(s) from the week of {args.week}")
        elif args.context_command == "list":
            for r in ctxmod.list_tags(con, args.week):
                note = f"  {r['note']}" if r["note"] else ""
                print(f"{r['week_start']}  {r['tag']}{note}")
        return 0

    if args.command == "seasons":
        from . import seasons
        seasons.write_seasons(con, args.out)
        print(f"Wrote seasons dashboard to {args.out}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
