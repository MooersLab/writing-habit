"""The stuck-project detector and the stuck hint for Suggest."""

import pytest

from writing_habit import coach, db, review, stuck
from writing_habit.review import BlockKey


@pytest.fixture()
def con(tmp_path):
    c = db.connect(str(tmp_path / "habit.db"))
    db.init_db(c)
    review.ensure(c)
    db.get_or_create_project(c, "A", "1001grantR01", "safe")
    yield c
    c.close()


def _block(con, day, objectives, code="A", start="05:00"):
    key = BlockKey(day, start, code)
    for text, done in objectives:
        review.mark(con, review.add_objective(con, key, text), done)


def test_the_same_objective_unmet_twice_is_repeated(con):
    _block(con, "2026-10-05", [("Draft aim 2", False), ("Find citations", True)])
    _block(con, "2026-10-06", [("draft aim 2.", False)])
    _block(con, "2026-10-07", [("Fix figure 1", True)])
    found = stuck.check(con, "A")
    assert (found.kind, found.task, found.times, found.blocks) == (
        "repeated", "draft aim 2.", 2, 3)
    assert found.sentence() == ("“draft aim 2.” has gone unmet in 2 of the last 3 "
                                "blocks of A 1001grantR01.")


def test_a_low_share_met_over_three_blocks(con):
    _block(con, "2026-10-05", [("Outline", True), ("Draft intro", False), ("Edit", False)])
    _block(con, "2026-10-06", [("Draft methods", False)])
    _block(con, "2026-10-07", [("Draft results", False)])
    found = stuck.check(con, "A")
    assert (found.kind, found.met, found.committed, found.task) == (
        "low", 1, 5, "Draft results")


def test_a_repeated_next_step(con):
    for day in ("2026-10-05", "2026-10-06"):
        review.save_review(con, BlockKey(day, "05:00", "A"),
                           review.Review(next_step="Start the budget justification"))
    found = stuck.check(con, "A")
    assert (found.kind, found.task) == ("same_step", "Start the budget justification")


def test_a_project_that_meets_its_objectives_is_not_stuck(con):
    for n, day in enumerate(("2026-10-05", "2026-10-06", "2026-10-07")):
        _block(con, day, [("Write one paragraph", True), (f"Check refs of part {n}", False)])
    assert stuck.check(con, "A") is None
    assert "No project shows a sign of being stuck" in stuck.report([])


def test_a_block_does_not_judge_itself_or_the_future(con):
    _block(con, "2026-10-05", [("Draft aim 2", False)])
    _block(con, "2026-10-06", [("Draft aim 2", False)])
    assert stuck.check(con, "A", before=("2026-10-06", "05:00")) is None
    assert stuck.check(con, "A", today="2026-10-05") is None
    assert stuck.check(con, "A", before=("2026-10-07", "05:00")).kind == "repeated"


def test_find_and_report(con):
    _block(con, "2026-10-05", [("Draft aim 2", False)])
    _block(con, "2026-10-06", [("Draft aim 2", False)])
    found = stuck.find(con, ["A", "B"])
    assert [s.code for s in found] == ["A"]
    assert "Suggest breaks it into smaller objectives" in stuck.report(found)


def test_the_stuck_sentence_reaches_the_suggest_facts():
    facts = coach.objective_facts("Draft aim 2", "1001grantR01", 90,
                                  stuck="“Draft aim 2” has gone unmet in 2 of the "
                                        "last 3 blocks of A 1001grantR01.")
    assert "Stuck: “Draft aim 2” has gone unmet" in facts
    assert facts.endswith("Break the task into smaller steps.")
    prompts = coach.load_prompts()
    assert "When the facts say the task is stuck" in prompts["tasks"]["objectives"]["system"]
