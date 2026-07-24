"""Cross-week adherence tracker tests (build step 1): views, series, and plots.

The fixture builds three weeks directly, without the writing-schedule package,
so it runs anywhere. Planned minutes come from block times, actual minutes are
stored directly on the sessions.
"""

import pytest

from writing_habit import db
from writing_habit.compare import history, queries

CAT_ID = {"generative": 1, "editing": 2, "support": 3}
SLOT = {"generative": 0, "editing": 1, "support": 2}
WEEKS = ["2026-01-05", "2026-01-12", "2026-01-19"]
RISK = {"A": "safe", "B": "safe", "W": "speculative", "EM": None}

# (week_index, code, category, planned, actual)
DATA = [
    (0, "A", "generative", 100, 80),
    (0, "A", "editing", 100, 100),
    (0, "B", "generative", 100, 40),
    (0, "W", "generative", 100, 0),
    (0, "EM", "support", 100, 50),
    (1, "A", "generative", 100, 90),
    (1, "A", "editing", 100, 90),
    (1, "B", "generative", 100, 100),
    (1, "W", "generative", 100, 50),
    (1, "EM", "support", 100, 100),
    (2, "A", "generative", 100, 60),
    (2, "A", "editing", 100, 60),
    (2, "B", "generative", 100, 40),
    (2, "W", "generative", 100, 0),
    (2, "EM", "support", 100, 80),
]


def _hhmm(total_min: int) -> str:
    return f"{total_min // 60:02d}:{total_min % 60:02d}"


@pytest.fixture()
def con(tmp_path):
    c = db.connect(str(tmp_path / "hist.db"))
    db.init_db(c)
    for code, risk in RISK.items():
        db.get_or_create_project(c, code, f"{code} project", risk)
    pid = {r["code"]: r["project_id"] for r in c.execute("SELECT code, project_id FROM project")}
    for wk, code, cat, planned, actual in DATA:
        monday = WEEKS[wk]
        start = (4 + SLOT[cat] * 3) * 60
        c.execute(
            "INSERT INTO plan_block(day,start_time,end_time,project_id,category_id)"
            " VALUES (?,?,?,?,?)",
            (monday, _hhmm(start), _hhmm(start + planned), pid[code], CAT_ID[cat]),
        )
        c.execute(
            "INSERT INTO session(day,actual_min,project_id,category_id,source)"
            " VALUES (?,?,?,?, 'manual')",
            (monday, actual, pid[code], CAT_ID[cat]),
        )
    c.commit()
    yield c
    c.close()


def _by_week(rows, key):
    return {r["week_start"]: r[key] for r in rows}


def test_overall_series(con):
    got = _by_week(queries.overall_series(con), "adherence")
    assert got == pytest.approx(
        {"2026-01-05": 0.54, "2026-01-12": 0.86, "2026-01-19": 0.48}, abs=0.005
    )


def test_project_mean_series(con):
    got = _by_week(queries.project_mean_series(con), "mean_adherence")
    assert got == pytest.approx(
        {"2026-01-05": 0.45, "2026-01-12": 0.85, "2026-01-19": 0.45}, abs=0.005
    )


def test_overall_differs_from_project_mean(con):
    # The two headline definitions diverge when project sizes differ.
    overall = _by_week(queries.overall_series(con), "adherence")
    mean = _by_week(queries.project_mean_series(con), "mean_adherence")
    assert overall["2026-01-05"] != mean["2026-01-05"]


def test_category_mean_series(con):
    gen = _by_week(queries.category_mean_series(con, "generative"), "mean_adherence")
    edit = _by_week(queries.category_mean_series(con, "editing"), "mean_adherence")
    sup = _by_week(queries.category_mean_series(con, "support"), "mean_adherence")
    assert gen == pytest.approx({"2026-01-05": 0.40, "2026-01-12": 0.80, "2026-01-19": 0.33}, abs=0.005)
    assert edit == pytest.approx({"2026-01-05": 1.00, "2026-01-12": 0.90, "2026-01-19": 0.60}, abs=0.005)
    assert sup == pytest.approx({"2026-01-05": 0.50, "2026-01-12": 1.00, "2026-01-19": 0.80}, abs=0.005)


def test_range_filter(con):
    weeks = [r["week_start"] for r in queries.overall_series(con, start="2026-01-12", end="2026-01-19")]
    assert weeks == ["2026-01-12", "2026-01-19"]


def test_render_text_lists_every_week(con):
    text = history.render_text(con)
    assert "Weekly adherence history" in text
    for w in WEEKS:
        assert w in text


def test_write_plots_creates_file(con, tmp_path):
    pytest.importorskip("matplotlib")
    out = tmp_path / "trend.png"
    history.write_plots(con, str(out))
    assert out.exists() and out.stat().st_size > 0
