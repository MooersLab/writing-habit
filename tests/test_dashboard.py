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
