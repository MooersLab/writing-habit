"""Block objectives, session reviews, and what the dashboard reads from them."""

from __future__ import annotations

import sqlite3

import pytest

from writing_habit import db, review
from writing_habit.review import BlockKey, Review
from writing_habit.track import manual, mytime_sync

KEY = BlockKey("2026-10-05", "05:30", "Z")


@pytest.fixture()
def con(tmp_path):
    c = db.connect(str(tmp_path / "habit.db"))
    db.init_db(c)
    yield c
    c.close()


def _plan(con, day, start, end, code, category="generative"):
    pid = db.get_or_create_project(con, code, f"project {code}", "safe")
    con.execute("INSERT INTO plan_block(day, start_time, end_time, project_id, category_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (day, start, end, pid, db.get_category_id(con, category)))
    con.commit()


# -- objectives -------------------------------------------------------------------
def test_objectives_keep_their_order_and_count(con):
    first = review.add_objective(con, KEY, "Draft aim 2")
    review.add_objective(con, KEY, "Find three citations", origin="grasscatcher")
    review.mark(con, first, True)
    items = review.objectives(con, KEY)
    assert [o.text for o in items] == ["Draft aim 2", "Find three citations"]
    assert [o.done for o in items] == [True, False]
    assert items[1].origin == "grasscatcher"
    assert review.counts(con, KEY) == (2, 1)


def test_an_empty_objective_is_refused(con):
    with pytest.raises(ValueError):
        review.add_objective(con, KEY, "   ")


def test_removing_an_objective_returns_it(con):
    oid = review.add_objective(con, KEY, "Tidy figure 3")
    gone = review.remove_objective(con, oid)
    assert gone.text == "Tidy figure 3"
    assert review.objectives(con, KEY) == []


# -- reviews ----------------------------------------------------------------------
def test_a_review_round_trips_and_takes_its_counts_from_the_objectives(con):
    review.mark(con, review.add_objective(con, KEY, "one"), True)
    review.add_objective(con, KEY, "two")
    stored = review.save_review(con, KEY, Review(objectives_met=0, focus=4,
                                                 interruptions=2,
                                                 next_step="Start at section 3"))
    assert (stored.objectives_committed, stored.objectives_met) == (2, 1)
    assert review.review(con, KEY).focus == 4
    assert review.review(con, KEY).next_step == "Start at section 3"


def test_a_review_without_objectives_keeps_the_typed_counts(con):
    review.save_review(con, KEY, Review(objectives_committed=3, objectives_met=2))
    stored = review.review(con, KEY)
    assert (stored.objectives_committed, stored.objectives_met) == (3, 2)


@pytest.mark.parametrize("bad", [Review(focus=6), Review(focus=0),
                                 Review(interruptions=-1),
                                 Review(objectives_committed=1, objectives_met=2)])
def test_bad_values_are_refused(con, bad):
    with pytest.raises(ValueError):
        review.save_review(con, KEY, bad)


def test_saving_again_replaces_and_a_blank_review_deletes(con):
    review.save_review(con, KEY, Review(focus=2))
    review.save_review(con, KEY, Review(focus=5))
    assert con.execute("SELECT COUNT(*) FROM session_review").fetchone()[0] == 1
    assert review.review(con, KEY).focus == 5
    review.save_review(con, KEY, Review())
    assert review.review(con, KEY).is_blank()


def test_the_database_refuses_a_focus_outside_one_to_five(con):
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO session_review(day, start_time, code, focus)"
                    " VALUES ('2026-10-05', '05:30', 'Z', 9)")


def test_rekey_moves_both_records_with_a_shifted_block(con):
    review.add_objective(con, KEY, "one")
    review.save_review(con, KEY, Review(focus=3))
    new = BlockKey(KEY.day, "06:30", KEY.code)
    assert review.rekey(con, KEY, new) == 2
    assert review.objectives(con, KEY) == []
    assert review.review(con, new).focus == 3


def test_rekey_never_merges_two_reviews(con):
    other = BlockKey(KEY.day, "06:30", KEY.code)
    review.save_review(con, KEY, Review(focus=1))
    review.save_review(con, other, Review(focus=5))
    review.rekey(con, KEY, other)
    assert review.review(con, other).focus == 5


def test_the_last_next_step_comes_from_an_earlier_block(con):
    review.save_review(con, BlockKey("2026-10-01", "05:00", "Z"),
                       Review(next_step="older"))
    review.save_review(con, BlockKey("2026-10-02", "05:00", "Z"),
                       Review(next_step="newer"))
    review.save_review(con, BlockKey("2026-10-09", "05:00", "Z"),
                       Review(next_step="later, not shown"))
    assert review.last_next_step(con, "Z", KEY) == "newer"


def test_ensure_upgrades_a_database_made_before_the_tables(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(str(path))
    old.execute("CREATE TABLE project (project_id INTEGER PRIMARY KEY, code TEXT)")
    old.close()
    con = db.connect(str(path))
    review.ensure(con)
    review.add_objective(con, KEY, "works")
    con.close()


# -- track sync cannot overwrite --------------------------------------------------
def test_track_sync_reruns_leave_reviews_and_objectives_alone(con, tmp_path):
    source = tmp_path / "mytime.db"
    src = sqlite3.connect(str(source))
    src.execute('CREATE TABLE zTimeSpent (id INTEGER PRIMARY KEY, DateDashed DATE,'
                ' Start TIME, "End" TIME, ProjectID INT, ProjectDirectory TEXT,'
                ' Description TEXT, Activity TEXT DEFAULT none)')
    src.execute("INSERT INTO zTimeSpent VALUES (1, '2026-10-05', '05:30', '07:00',"
                " 1008, '1008ToolsForQCrOfRNA', 'grant text', 'g')")
    src.commit()
    table = tmp_path / "Oct5.org"
    table.write_text("| Time | M |\n|---+---|\n| 05:30-07:00 | gZ |\n|---+---|\n"
                     "| Z: 1008ToolsForQCrOfRNA :safe: | |\n", encoding="utf-8")
    con.execute("INSERT INTO plan_week(week_start, schedule_code, table_path)"
                " VALUES ('2026-10-05', 'Oct5', ?)", (str(table),))
    _plan(con, "2026-10-05", "05:30", "07:00", "Z")
    review.mark(con, review.add_objective(con, KEY, "Draft aim 2"), True)
    review.save_review(con, KEY, Review(focus=4, interruptions=1, note="good"))
    before = (review.objectives(con, KEY), review.review(con, KEY))
    for _ in range(2):
        mytime_sync.sync_mytime(con, str(source), since="2026-10-01",
                                scope="all")
    src.execute("UPDATE zTimeSpent SET \"End\" = '07:15' WHERE id = 1")
    src.commit()
    mytime_sync.sync_mytime(con, str(source), since="2026-10-01", scope="all")
    src.close()
    assert con.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1
    assert (review.objectives(con, KEY), review.review(con, KEY)) == before


# -- the dashboard's readings -----------------------------------------------------
def test_block_outcomes_grade_kept_partial_missed_and_ahead(con):
    _plan(con, "2026-10-05", "05:00", "06:00", "A")
    _plan(con, "2026-10-05", "08:00", "10:00", "A")
    _plan(con, "2026-10-06", "05:00", "06:00", "B")
    _plan(con, "2026-10-09", "05:00", "06:00", "B")
    manual.add_session(con, day="2026-10-05", project_code="A", minutes=60,
                       start="05:00", end="06:00", category="generative")
    manual.add_session(con, day="2026-10-05", project_code="A", minutes=30,
                       start="08:00", end="08:30", category="generative")
    rows = review.block_outcomes(con, "2026-10-05", today="2026-10-07")
    assert [(r["start_time"], r["code"], r["status"]) for r in rows] == [
        ("05:00", "A", "kept"), ("08:00", "A", "partial"),
        ("05:00", "B", "missed"), ("05:00", "B", "ahead")]
    assert rows[1]["actual_min"] == 30


def test_an_untimed_session_counts_once(con):
    _plan(con, "2026-10-05", "05:00", "06:00", "A")
    _plan(con, "2026-10-05", "07:00", "08:00", "A")
    manual.add_session(con, day="2026-10-05", project_code="A", minutes=45,
                       category="generative")
    rows = review.block_outcomes(con, "2026-10-05", today="2026-10-30")
    assert [r["actual_min"] for r in rows] == [45, 0]


def test_done_list_and_has_records(con):
    assert not review.has_records(con, "2026-10-05")
    review.mark(con, review.add_objective(con, KEY, "Draft aim 2"), True)
    review.add_objective(con, KEY, "not done")
    assert review.has_records(con, "2026-10-05")
    assert [d["text"] for d in review.done_list(con, "2026-10-05")] == ["Draft aim 2"]


def test_personal_bests_flag_the_week_that_holds_them(con):
    for week, planned, actual in (("2026-09-28", 60, 30), ("2026-10-05", 60, 60)):
        _plan(con, week, "05:00", "06:00", "A")
        manual.add_session(con, day=week, project_code="A", minutes=actual,
                           category="generative")
    review.save_review(con, KEY, Review(objectives_committed=2, objectives_met=2))
    bests = {b.label: b for b in review.personal_bests(con, "2026-10-05")}
    assert bests["Most of the plan kept"].value == "100%"
    assert bests["Most of the plan kept"].this_week
    assert bests["Most minutes written"].week == "2026-10-05"
    assert bests["Longest run of writing days"].value == "1 day"
    assert bests["Most objectives met"].value == "2"
    assert review.planned_weeks(con, "2026-10-05") == 2
