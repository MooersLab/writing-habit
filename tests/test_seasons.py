"""Tests for the second dashboard (build step 3): grouping views, context, seasons HTML."""

from pathlib import Path

import pytest

from writing_habit import context, db, seasons
from writing_habit.compare import queries

# (monday, planned, actual, schedule_code)
WEEKS = [
    ("2026-01-05", 100, 80, "4gA-gW"),
    ("2026-01-12", 100, 60, "4gA-gW"),
    ("2026-02-02", 100, 40, "2gAeA-gW"),
    ("2026-02-09", 100, 20, "2gAeA-gW"),
    ("2026-03-02", 100, 90, "4gA-gW"),
]


def _hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


@pytest.fixture()
def con(tmp_path):
    c = db.connect(str(tmp_path / "seasons.db"))
    db.init_db(c)
    db.get_or_create_project(c, "A", "A project", "safe")
    pid = c.execute("SELECT project_id FROM project WHERE code='A'").fetchone()["project_id"]
    for monday, planned, actual, code in WEEKS:
        c.execute(
            "INSERT INTO plan_block(day,start_time,end_time,project_id,category_id) VALUES (?,?,?,?,1)",
            (monday, "04:00", _hhmm(4 * 60 + planned), pid))
        c.execute(
            "INSERT INTO session(day,actual_min,project_id,category_id,source) VALUES (?,?,?,1,'manual')",
            (monday, actual, pid))
        c.execute(
            "INSERT INTO plan_week(week_start,schedule_code,table_path) VALUES (?,?,?)",
            (monday, code, f"{monday}_{code}.org"))
    context.set_tag(c, "2026-02-02", "teaching")
    context.set_tag(c, "2026-02-09", "teaching")
    context.set_tag(c, "2026-01-05", "meeting", "annual conference")
    c.commit()
    yield c
    c.close()


def test_month_overall(con):
    rows = {r["month"]: (r["weeks"], r["adherence"]) for r in queries.month_overall(con)}
    assert rows["2026-01"] == (2, pytest.approx(0.70, abs=0.005))   # (80+60)/200
    assert rows["2026-02"] == (2, pytest.approx(0.30, abs=0.005))   # (40+20)/200
    assert rows["2026-03"] == (1, pytest.approx(0.90, abs=0.005))   # 90/100


def test_context_overall(con):
    rows = {r["tag"]: (r["weeks"], r["adherence"]) for r in queries.context_overall(con)}
    assert rows["teaching"] == (2, pytest.approx(0.30, abs=0.005))  # (40+20)/200
    assert rows["meeting"] == (1, pytest.approx(0.80, abs=0.005))   # 80/100


def test_schedule_overall(con):
    rows = {r["schedule_code"]: (r["weeks"], r["adherence"]) for r in queries.schedule_overall(con)}
    assert rows["4gA-gW"][0] == 3                                   # Jan 5, Jan 12, Mar 2
    assert rows["4gA-gW"][1] == pytest.approx(0.77, abs=0.01)       # (80+60+90)/300
    assert rows["2gAeA-gW"] == (2, pytest.approx(0.30, abs=0.005))  # (40+20)/200


def test_context_set_and_clear(con):
    context.set_tag(con, "2026-03-02", "travel")
    assert any(r["tag"] == "travel" for r in context.list_tags(con, "2026-03-02"))
    assert context.clear_tag(con, "2026-03-02", "travel") == 1
    assert not any(r["tag"] == "travel" for r in context.list_tags(con, "2026-03-02"))


def test_matches_seasons_fixture():
    """The seasons dashboard is byte-identical to the committed 20-week render.

    The Emacs Lisp twin asserts against this same golden from the shared
    tests/fixtures/seasons.db, so the two ports render one identical file.
    """
    root = Path(__file__).resolve().parents[1]
    dbp = root / "tests" / "fixtures" / "seasons.db"
    htmlp = root / "tests" / "fixtures" / "seasons.html"
    con = db.connect(str(dbp))
    try:
        html = seasons.seasons_html(con)
    finally:
        con.close()
    assert html == htmlp.read_text(encoding="utf-8")


def test_seasons_html_structure(con):
    html = seasons.seasons_html(con)
    assert html.startswith("<!DOCTYPE html>")
    assert html.endswith("</html>\n")
    assert "<title>Writing seasons: grouped adherence</title>" in html
    assert "<h2>By month</h2>" in html
    assert "<h2>By event context</h2>" in html
    assert "<h2>By schedule</h2>" in html
    assert "2026-01" in html and "teaching" in html and "4gA-gW" in html


def test_seasons_empty_sections(tmp_path):
    c = db.connect(str(tmp_path / "empty.db"))
    db.init_db(c)
    html = seasons.seasons_html(c)
    c.close()
    assert "No weeks recorded yet." in html
    assert "No context tags recorded" in html
    assert "No schedule codes recorded" in html


def test_schedule_code_helper():
    from writing_habit.plan_import import _schedule_code
    assert _schedule_code("/x/2026-01-19_4gAAeAsA-gWW.org") == "4gAAeAsA-gWW"
    assert _schedule_code("my-week.org") == "my-week"


def test_plan_import_records_schedule(tmp_path):
    pytest.importorskip("writing_schedule")
    from writing_habit.plan_import import import_org
    root = Path(__file__).resolve().parents[1]
    c = db.connect(str(tmp_path / "imp.db"))
    db.init_db(c)
    import_org(c, str(root / "examples" / "my-week.org"), "2026-01-19")
    row = c.execute(
        "SELECT schedule_code, table_path FROM plan_week WHERE week_start='2026-01-19'"
    ).fetchone()
    c.close()
    assert row is not None
    assert row["schedule_code"] == "my-week"
