"""Roll-forward triage: keep, defer, or drop each carried-over project."""

import datetime as dt

from writing_habit import coach, db, triage
from writing_habit.project_lists import parse_entry

from test_coach import fake_model

TODAY = dt.date(2026, 10, 14)
END = dt.date(2026, 12, 18)


def entries(*cells):
    return [parse_entry(c) for c in cells]


def test_recent_work_keeps_a_project():
    d = triage.decide("1006AIrxOpt", None, {"2026-10-05": 45, "2026-09-28": 30},
                      TODAY, END)
    assert d.action == "keep" and d.recent == 75
    assert d.reason == "75 minutes were logged for it in the last 4 weeks, so it is alive"


def test_a_deadline_in_the_period_keeps_a_project():
    d = triage.decide("1452PHFSboXt", "2026-11-02", {}, TODAY, END)
    assert d.action == "keep" and "falls in this period" in d.reason


def test_a_later_deadline_defers_a_project():
    d = triage.decide("1002RNAediting", "2027-03-01", {"2026-09-07": 20}, TODAY, END,
                      "Spring 2027 projects")
    assert d.action == "defer"
    assert d.line() == "Defer 1002RNAediting to Spring 2027 projects"


def test_old_work_without_a_deadline_defers():
    d = triage.decide("2003reviewArticle", None, {"2026-08-31": 90}, TODAY, END)
    assert d.action == "defer" and d.last_week == "2026-08-31"
    assert "last worked the week of 2026-08-31" in d.reason


def test_a_passed_deadline_or_no_work_at_all_drops():
    gone = triage.decide("0900oldTalk", "2026-09-01", {}, TODAY, END)
    assert gone.action == "drop" and "Renegotiate" in gone.reason
    idle = triage.decide("0901idea", None, {}, TODAY, END)
    assert idle.action == "drop" and idle.line() == "Drop 0901idea from the lists"
    # Recent work outweighs a passed deadline.
    late = triage.decide("0902late", "2026-09-01", {"2026-10-12": 120}, TODAY, END)
    assert late.action == "keep"


def test_minutes_follow_the_project_number_when_a_code_changes(tmp_path):
    con = db.connect(str(tmp_path / "h.db"))
    db.init_db(con)
    a = db.get_or_create_project(con, "A", "1006AIrxOpt", "safe")
    q = db.get_or_create_project(con, "Q", "0900oldTalk", "safe")
    for day, pid, minutes in [("2026-10-06", a, 50), ("2026-10-07", a, 40),
                              ("2026-09-02", q, 30), ("2026-01-05", a, 99)]:
        con.execute("INSERT INTO session(day, actual_min, project_id, source) "
                    "VALUES (?, ?, ?, 'manual')", (day, minutes, pid))
    # This week code Q names 1006AIrxOpt, so Q's minutes count for 1006.
    found = triage.minutes_by_project(con, {"A": "1006AIrxOpt extra"}, "2026-06-01")
    assert found == {"1006": {"2026-10-05": 90}, "0900": {"2026-08-31": 30}}
    found = triage.minutes_by_project(con, {"Q": "1006AIrxOpt"}, "2026-06-01")
    assert found["1006"] == {"2026-10-05": 90, "2026-08-31": 30}
    con.close()


def test_triage_reads_each_entry_and_the_plain_note():
    rows = entries("- 1006AIrxOpt :safe:", "- 1002RNAediting 2027-03-01 :safe:",
                   "- 0901idea")
    history = {"1006": {"2026-10-05": 90}}
    found = triage.triage(rows, history, TODAY, END, "Spring 2027 projects")
    assert [d.action for d in found] == ["keep", "defer", "drop"]
    text = triage.plain(found)
    assert text.startswith("3 carried projects: keep 1, defer 1, drop 1.")
    assert "  Drop 0901idea, because no time was logged" in text
    assert triage.plain([]).startswith("Nothing is on the Carried over list")


def test_the_coach_wording_and_its_number_guard():
    found = triage.triage(entries("- 1006AIrxOpt", "- 0901idea"),
                          {"1006": {"2026-10-05": 90}}, TODAY, END)
    reply = "Keep 1006AIrxOpt, which got 90 minutes lately, and drop the idle idea."
    answer = coach.triage_projects(coach.Client("tiny", opener=fake_model(reply)),
                                   found, "Fall 2026")
    assert answer.data["note"] == reply
    bad = coach.triage_projects(coach.Client("tiny", opener=fake_model(
        "Keep all 7 of them.")), found, "Fall 2026")
    assert bad.data["note"] == triage.plain(found)
    empty = coach.triage_projects(None, [], "Fall 2026")
    assert empty.data["decisions"] == [] and empty.log_id is None
