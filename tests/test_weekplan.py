"""The Monday message: the week's plan for an accountability partner."""

from writing_habit import coach, weekplan

from test_coach import fake_model

LEGEND = {"A": "1006AIrxOpt 2026-10-30", "B": "1002RNAediting 2027-03-01",
          "C": "2003reviewArticle", "E": "email"}
MINUTES = {"A": 90, "B": 180, "C": 270, "E": 135}


def test_the_nearest_deadline_matters_most():
    plan = weekplan.gather("2026-10-12", MINUTES, LEGEND, 8, 5,
                           [("C", "Outline the review"), ("A", "Draft aim 1.")])
    assert plan["key"]["code"] == "A"
    assert plan["objective"] == "Draft aim 1."
    text = weekplan.plain(plan)
    assert text == ("This week I plan 11 h 15 min of writing in 8 blocks over 5 days. "
                    "Most of it goes to 2003reviewArticle (4 h 30 min), 1002RNAediting "
                    "(3 h 00 min), and email (2 h 15 min).\n\n"
                    "The one that matters most is 1006AIrxOpt, due October 30. My first "
                    'objective there is "Draft aim 1". I will send you how it went on '
                    "Friday.")
    assert "Project that matters most: A 1006AIrxOpt, due 2026-10-30 (October 30)" in \
        weekplan.facts(plan)


def test_without_deadlines_the_largest_project_matters_most():
    plan = weekplan.gather("2026-10-12", {"C": 120}, {"C": "2003reviewArticle"}, 1, 1)
    assert weekplan.plain(plan).startswith(
        "This week I plan 2 h 00 min of writing in 1 block over 1 day. All of it goes "
        "to 2003reviewArticle (2 h 00 min).\n\nThe one that matters most is "
        "2003reviewArticle, which has the most time.")
    assert weekplan.gather("2026-10-12", {}, {}, 0, 0) is None


def test_a_past_deadline_does_not_count():
    plan = weekplan.gather("2026-10-12", {"A": 60, "C": 90},
                           {"A": "old 2026-09-01", "C": "2003review"}, 2, 2)
    assert plan["key"]["code"] == "C"


def test_the_coach_draft_keeps_only_numbers_from_the_plan():
    plan = weekplan.gather("2026-10-12", MINUTES, LEGEND, 8, 5)
    good = ("This week I have 11 h 15 min planned across 8 blocks, mostly on the "
            "review article.\n\nThe grant, due October 30, comes first.")
    answer = coach.plan_message(coach.Client("tiny", opener=fake_model(good)), plan)
    assert answer.data["text"] == good
    bad = coach.plan_message(coach.Client("tiny", opener=fake_model(
        "I will write 20 hours this week.")), plan)
    assert bad.data["text"] == weekplan.plain(plan)
    assert "not in your plan" in bad.source
