"""Semester review: the semester's record as a narrative for an annual report."""

from writing_habit import coach, db, semester

from test_coach import fake_model


def build(path):
    con = db.connect(str(path))
    db.init_db(con)
    ids = {r[1]: r[0] for r in con.execute("SELECT category_id, name FROM category")}
    a = db.get_or_create_project(con, "A", "1001grantR01 2026-10-30", "safe")
    b = db.get_or_create_project(con, "B", "0142RETKinase", "safe")
    # Two September weeks and one October week of 300 planned minutes each.
    for day in ("2026-09-07", "2026-09-14", "2026-10-05"):
        con.execute("INSERT INTO plan_block(day, start_time, end_time, project_id,"
                    " category_id) VALUES (?, '05:00', '10:00', ?, ?)",
                    (day, a, ids["generative"]))
    for day, pid, minutes in [("2026-09-07", a, 240), ("2026-09-14", b, 120),
                              ("2026-10-05", a, 60), ("2026-06-01", b, 500)]:
        con.execute("INSERT INTO session(day, actual_min, project_id, source)"
                    " VALUES (?, ?, ?, 'manual')", (day, minutes, pid))
    for day, text, done in [("2026-09-07", "Draft aim 1", 1),
                            ("2026-09-07", "Find three citations", 0),
                            ("2026-09-14", "Revise figure 2.", 1)]:
        con.execute("INSERT INTO block_objective(day, start_time, code, text, done)"
                    " VALUES (?, '05:00', 'A', ?, ?)", (day, text, done))
    con.commit()
    return con


def test_gather_counts_the_semester_only(tmp_path):
    con = build(tmp_path / "h.db")
    s = semester.gather(con, "Fall 2026", "2026-08-17", "2026-12-18",
                        ["0131RETKinase2018BrP 2026-09-30"])
    assert (s.planned, s.actual, s.weeks, s.weeks_written) == (900, 420, 3, 3)
    assert s.kept_pct == 47
    assert s.months == [("2026-09", 600, 360), ("2026-10", 300, 60)]
    assert s.projects == [("1001grantR01", 300), ("0142RETKinase", 120)]
    assert s.completed == ["0131RETKinase2018BrP"]
    assert (s.committed, s.met) == (3, 2)
    assert s.done == ["Draft aim 1", "Revise figure 2."]
    assert semester.gather(con, "Spring 2026", "2026-01-05", "2026-05-08") is None


def test_the_plain_narrative(tmp_path):
    con = build(tmp_path / "h.db")
    s = semester.gather(con, "Fall 2026", "2026-08-17", "2026-12-18",
                        ["0131RETKinase2018BrP"])
    text = semester.plain(s)
    assert text.startswith("During Fall 2026, I planned 15 h 00 min of writing over "
                           "3 weeks and wrote 7 h 00 min, which is 47% of the plan.")
    assert "highest in September, at 60%, and lowest in October, at 20%." in text
    assert ("Most of the time went to 1001grantR01 (5 h 00 min) and "
            "0142RETKinase (2 h 00 min).") in text
    assert "I completed 0131RETKinase2018BrP." in text
    assert "I met 2 of the 3 block objectives I committed to." in text
    assert 'Objectives I met include "Draft aim 1" and "Revise figure 2".' in text
    assert "\n\n" in text


def test_the_coach_draft_and_its_guards(tmp_path):
    con = build(tmp_path / "h.db")
    s = semester.gather(con, "Fall 2026", "2026-08-17", "2026-12-18")
    reply = ("I finished drafting aim 1 and revised figure 2.\n\n"
             "I wrote 7 h 00 min of the 15 h 00 min I planned, 47% of the plan.")
    answer = coach.semester_review(coach.Client("tiny", opener=fake_model(reply)), s)
    assert answer.data["text"] == reply
    invented = coach.semester_review(coach.Client("tiny", opener=fake_model(
        "I published 4 papers and kept 47% of the plan.")), s)
    assert invented.data["text"] == semester.plain(s)
    assert "number that is not in your record" in invented.source
    missing = coach.semester_review(coach.Client("tiny", opener=fake_model(
        "A good semester of writing.")), s)
    assert "left out the share" in missing.source
    assert "No project was marked completed" in semester.plain(s)
