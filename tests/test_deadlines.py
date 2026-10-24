"""Deadline coverage: projects due soon with no block left this week."""

import datetime as dt

from writing_habit import coach, deadlines
from writing_habit.deadlines import Slot

from test_coach import fake_model

MONDAY = dt.date(2026, 10, 12)
WEDNESDAY = dt.date(2026, 10, 14)

LEGEND = {
    "A": "1006AIrxOpt 2026-10-30",          # due in 16 days, has no block ahead
    "B": "1002RNAediting 2026-10-23",       # due in 9 days, has a block ahead
    "C": "2003reviewArticle",                # no deadline, plenty of time
    "D": "0055talk 2027-03-01",              # due long after the horizon
    "E": "email",
}
LISTS = [
    ("current-semester-projects", None, "1452PHFSboXt 2026-11-02"),  # not in the legend
    ("current-semester-projects", "B", "1002RNAediting 2026-10-23"),  # also in the legend
    ("next-semester-projects", None, "9999later 2027-02-01"),
]


def _slots():
    return [
        Slot(0, "05:00", "07:00", "A", "generative", 120, 1, 1),   # Monday, passed
        Slot(2, "05:00", "06:30", "B", "generative", 90, 1, 3),
        Slot(3, "05:00", "06:30", "C", "generative", 90, 1, 4),
        Slot(4, "05:00", "06:30", "C", "generative", 90, 1, 5),
        Slot(3, "09:00", "10:00", "D", "editing", 60, 2, 4),
        Slot(4, "13:00", "13:45", "E", "support", 45, 3, 5),
    ]


def test_projects_due_takes_the_legend_first_and_skips_far_or_past_dates():
    due = deadlines.projects_due(LEGEND, LISTS, WEDNESDAY, 28)
    assert [(p.name, p.in_legend) for p in due] == [
        ("1002RNAediting", True), ("1006AIrxOpt", True), ("1452PHFSboXt", False)]
    past = deadlines.projects_due({"Z": "old 2026-10-01"}, [], WEDNESDAY, 28)
    assert past == []


def test_a_project_with_no_block_ahead_gets_a_block_from_one_without_a_deadline():
    result = deadlines.check(LEGEND, LISTS, _slots(), MONDAY, WEDNESDAY, 28)
    risks = {r.project.name: r for r in result.risks}
    assert set(risks) == {"1006AIrxOpt", "1452PHFSboXt"}
    a = risks["1006AIrxOpt"]
    assert a.planned_min == 120 and a.ahead_min == 0 and a.days_left == 16
    # C has no deadline and the most time ahead, so it gives its first block.
    assert (a.donor.code, a.donor.offset, a.donor_keeps) == ("C", 3, 90)
    other = risks["1452PHFSboXt"]
    assert (other.donor.code, other.donor.offset) == ("C", 4)
    assert [p.name for p, _spent, _left in result.covered] == ["1002RNAediting"]


def test_blocks_of_projects_due_soon_are_never_taken():
    slots = [Slot(3, "05:00", "06:30", "B", "generative", 90, 1, 4)]
    result = deadlines.check(LEGEND, [], slots, MONDAY, WEDNESDAY, 28)
    risk = next(r for r in result.risks if r.project.code == "A")
    assert risk.donor is None
    assert "Every block ahead belongs to a project that is due soon" in deadlines.plain(result)


def test_a_donor_with_a_deadline_keeps_one_block():
    legend = {"A": "1006AIrxOpt 2026-10-30", "D": "0055talk 2027-03-01"}
    one = [Slot(3, "09:00", "10:00", "D", "editing", 60, 2, 4)]
    assert deadlines.check(legend, [], one, MONDAY, WEDNESDAY, 28).risks[0].donor is None
    two = one + [Slot(4, "09:00", "10:00", "D", "editing", 60, 2, 5)]
    assert deadlines.check(legend, [], two, MONDAY, WEDNESDAY, 28).risks[0].donor.code == "D"


def test_support_blocks_give_last():
    legend = {"A": "1006AIrxOpt 2026-10-30", "C": "2003review", "E": "email"}
    slots = [Slot(3, "13:00", "13:45", "E", "support", 45, 3, 4),
             Slot(4, "05:00", "06:00", "C", "generative", 60, 1, 5)]
    risk = deadlines.check(legend, [], slots, MONDAY, WEDNESDAY, 28).risks[0]
    assert risk.donor.code == "C"


def test_the_plain_note_and_the_facts():
    result = deadlines.check(LEGEND, LISTS, _slots(), MONDAY, WEDNESDAY, 28)
    text = deadlines.plain(result)
    assert ("A 1006AIrxOpt is due 2026-10-30, in 16 days, and has no block left this "
            "week. Give it Thursday 05:00-06:30, now planned for C 2003reviewArticle, "
            "which has no deadline and keeps 1 h 30 min this week.") in text
    assert "It waits on the current-semester-projects list." in text
    assert "1 other project due soon has time left this week." in text
    facts = deadlines.facts(result)
    assert "Covered: B 1002RNAediting, due 2026-10-23, 90 minutes" in facts
    assert deadlines.proposal_line(result.risks[0]).startswith(
        "Give Thursday 05:00-06:30 (generative) to A 1006AIrxOpt")


def test_nothing_due_says_so():
    result = deadlines.check({"C": "2003review"}, [], _slots(), MONDAY, WEDNESDAY, 28)
    assert deadlines.plain(result).startswith("No project in the legend or the lists")


def test_the_coach_words_the_check_and_rejects_invented_numbers(tmp_path):
    from writing_habit import db
    con = db.connect(str(tmp_path / "habit.db"))
    db.init_db(con)
    result = deadlines.check(LEGEND, LISTS, _slots(), MONDAY, WEDNESDAY, 28)
    good = ("Your grant 1006AIrxOpt is due in 16 days with no block left, so "
            "Thursday's block from the review article would serve it better.")
    answer = coach.cover_deadlines(coach.Client("tiny", opener=fake_model(good)),
                                   result, con=con, week_start="2026-10-12")
    assert answer.data["note"] == good
    assert answer.source == "local model tiny"
    bad = "Give the grant 40 hours this week."
    answer = coach.cover_deadlines(coach.Client("tiny", opener=fake_model(bad)),
                                   result, con=con, week_start="2026-10-12")
    assert "not in the plan" in answer.source
    assert answer.data["note"] == deadlines.plain(result)
    assert con.execute("SELECT COUNT(*) FROM ai_log WHERE task = 'coverage'").fetchone()[0] == 2
    con.close()


def test_the_coach_is_not_asked_when_nothing_is_at_risk():
    result = deadlines.check({"C": "2003review"}, [], _slots(), MONDAY, WEDNESDAY, 28)
    answer = coach.cover_deadlines(coach.Client("tiny", opener=fake_model("x")), result)
    assert answer.source.startswith("plain summary")
