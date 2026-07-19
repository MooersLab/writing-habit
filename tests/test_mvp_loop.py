"""End-to-end test: initdb, plan import, track import, then compare."""

from pathlib import Path

import pytest

pytest.importorskip("writing_schedule", reason="plan import needs the writing-schedule package")

from writing_habit import db
from writing_habit.compare import queries
from writing_habit.plan_import import import_org
from writing_habit.track import csv_actuals

ROOT = Path(__file__).resolve().parents[1]
WEEK = "2026-01-19"


@pytest.fixture()
def con(tmp_path):
    c = db.connect(str(tmp_path / "habit.db"))
    db.init_db(c)
    import_org(c, str(ROOT / "examples" / "my-week.org"), WEEK)
    csv_actuals.import_csv(c, str(ROOT / "examples" / "actuals.csv"))
    yield c
    c.close()


def test_plan_loaded(con):
    n = con.execute("SELECT COUNT(*) FROM plan_block").fetchone()[0]
    assert n > 0


def test_projects_have_risk_class(con):
    rows = {r["code"]: r["risk_class"] for r in con.execute("SELECT code, risk_class FROM project")}
    assert rows["A"] == "safe"
    assert rows["W"] == "speculative"


def test_adherence_for_project_A(con):
    row = next(r for r in queries.week_project(con, WEEK) if r["code"] == "A")
    # planned A: Mon 2 blocks, Wed 2 blocks = 4 x 90 = 360; but layout has A on
    # Mon(04:00,05:45), Wed(04:00,05:45), Tue(09:15), Thu(09:15) -> depends on table.
    assert row["planned_min"] > 0
    assert row["actual_min"] > 0
    assert row["adherence"] is not None


def test_speculative_slot_starved(con):
    row = next(r for r in queries.week_barbell(con, WEEK) if r["risk_class"] == "speculative")
    # The example actuals never touch project W, so speculative actual is zero.
    assert row["actual_min"] == 0
    assert row["planned_min"] > 0


def test_streak_is_three_days(con):
    assert queries.current_streak(con) == 3
