"""The dashboard subcommand writes the same HTML the library renders.

The graphical front end calls ``dashboard.write_dashboard`` directly, so the
command line needs the matching subcommand for the two front ends to offer the
same actions.
"""

import shutil
from pathlib import Path

from writing_habit import cli, db
from writing_habit.dashboard import dashboard_html

ROOT = Path(__file__).resolve().parents[1]
XPORT_DB = ROOT / "tests" / "fixtures" / "cross-port.db"
WEEK = "2026-01-19"


def test_dashboard_subcommand_writes_the_library_render(tmp_path, capsys):
    dbpath = tmp_path / "habit.db"
    shutil.copy(XPORT_DB, dbpath)
    out = tmp_path / "week.html"

    rc = cli.main(["dashboard", "--week", WEEK, "--out", str(out), "--db", str(dbpath)])
    assert rc == 0
    assert f"Wrote dashboard to {out}" in capsys.readouterr().out

    con = db.connect(str(dbpath))
    try:
        expected = dashboard_html(con, WEEK)
    finally:
        con.close()
    assert out.read_text(encoding="utf-8") == expected


def test_dashboard_is_in_the_parser():
    parser = cli.build_parser()
    args = parser.parse_args(["dashboard", "--week", WEEK, "--out", "x.html", "--db", "d.db"])
    assert args.command == "dashboard" and args.out == "x.html"
