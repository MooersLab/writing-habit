"""Dashboard tests, including the byte-identical guard against the shared fixture.

The frozen render ``tests/fixtures/dashboard.html`` is the same file the Emacs
Lisp twin asserts against, so both ports render one identical dashboard from the
shared ``tests/fixtures/cross-port.db``.  Needs no third-party package.
"""

from pathlib import Path

from writing_habit import db
from writing_habit.dashboard import dashboard_html

ROOT = Path(__file__).resolve().parents[1]
XPORT_DB = ROOT / "tests" / "fixtures" / "cross-port.db"
XPORT_HTML = ROOT / "tests" / "fixtures" / "dashboard.html"
WEEK = "2026-01-19"


def test_matches_cross_port_fixture():
    """The dashboard is byte-identical to the committed cross-port render."""
    con = db.connect(str(XPORT_DB))
    try:
        html = dashboard_html(con, WEEK)
    finally:
        con.close()
    expected = XPORT_HTML.read_text(encoding="utf-8")
    assert html == expected


def test_structure_and_palette():
    con = db.connect(str(XPORT_DB))
    try:
        html = dashboard_html(con, WEEK)
    finally:
        con.close()
    assert html.startswith("<!DOCTYPE html>")
    assert html.endswith("</html>\n")
    assert "<title>Writing dashboard, week of 2026-01-19</title>" in html
    assert "<h2>Schedule</h2>" in html
    assert "Planned vs actual by project" in html
    assert "day writing streak" in html
    assert "--gen: #2a78d6;" in html
    assert 'class="cell gen"' in html
    # round-half-up: the 12.5% speculative share reads as 13, not 12
    assert "Speculative share: planned 13%, actual 0%." in html
    # build step 2: the overall-adherence trend section
    assert "<h2>Adherence over recent weeks</h2>" in html
    assert 'aria-label="Overall adherence over recent weeks"' in html


def test_escapes_text(tmp_path):
    con = db.connect(str(tmp_path / "esc.db"))
    db.init_db(con)
    db.get_or_create_project(con, "A", 'a<b> & "c"', "safe")
    from writing_habit.track import manual
    manual.add_session(con, day="2026-01-19", project_code="A", minutes=30, category="generative")
    html = dashboard_html(con, "2026-01-19")
    con.close()
    assert "a&lt;b&gt; &amp; &quot;c&quot;" in html
    assert 'a<b> & "c"' not in html


def test_trend_single_week_point():
    con = db.connect(str(XPORT_DB))
    try:
        html = dashboard_html(con, WEEK)
    finally:
        con.close()
    # one week in the fixture, so the point sits at the plot center (x=355),
    # at 26% adherence (y=123)
    assert '<circle cx="355" cy="123" r="3" fill="var(--planned)"/>' in html
    assert ">01-19</text>" in html


def test_trend_multi_week_geometry(tmp_path):
    from writing_habit.track import manual
    con = db.connect(str(tmp_path / "trend.db"))
    db.init_db(con)
    db.get_or_create_project(con, "A", "A project", "safe")
    for wk in ("2026-01-05", "2026-01-12", "2026-01-19"):
        con.execute(
            "INSERT INTO plan_block(day,start_time,end_time,project_id,category_id)"
            " VALUES (?, '04:00','05:40', 1, 1)", (wk,))
        manual.add_session(con, day=wk, project_code="A", minutes=60, category="generative")
    con.commit()
    html = dashboard_html(con, "2026-01-19")
    con.close()
    # three evenly spaced weeks -> x at the left edge, the center, and the right edge
    assert html.count('r="3" fill="var(--planned)"') == 3
    assert 'cx="42"' in html and 'cx="355"' in html and 'cx="668"' in html
    for label in (">01-05<", ">01-12<", ">01-19<"):
        assert label in html


def test_trend_geometry_helpers():
    from writing_habit import dashboard as d
    assert d._trend_y(0) == 146
    assert d._trend_y(100) == 58
    assert d._trend_y(150) == 14
    assert d._trend_x(0, 1) == 355  # single point centered
    assert (d._trend_x(0, 3), d._trend_x(1, 3), d._trend_x(2, 3)) == (42, 355, 668)
