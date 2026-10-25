"""Why each missed block was missed: questions, streaks, and saved reasons."""

from writing_habit import coach, db, misses

from test_coach import fake_model


def build(path):
    con = db.connect(str(path))
    db.init_db(con)
    ids = {r[1]: r[0] for r in con.execute("SELECT category_id, name FROM category")}
    a = db.get_or_create_project(con, "A", "1001grantR01 2026-10-30", "safe")
    e = db.get_or_create_project(con, "E", "email", None)
    # Tuesday's grant block is missed this week and last week; Monday's email is
    # missed only this week; Wednesday's grant block is kept.
    for day, pid, category, start in [
            ("2026-10-06", a, "generative", "05:00"),
            ("2026-10-13", a, "generative", "05:00"),
            ("2026-10-12", e, "support", "13:00"),
            ("2026-10-14", a, "generative", "07:00")]:
        con.execute("INSERT INTO plan_block(day, start_time, end_time, project_id,"
                    " category_id) VALUES (?, ?, strftime('%H:%M', ?, '+90 minutes'), ?, ?)",
                    (day, start, start, pid, ids[category]))
    con.execute("INSERT INTO session(day, start_time, end_time, actual_min, project_id,"
                " source) VALUES ('2026-10-14', '07:00', '08:30', 90, ?, 'manual')", (a,))
    con.commit()
    return con


def test_missed_blocks_with_their_streaks(tmp_path):
    con = build(tmp_path / "h.db")
    found = misses.find(con, "2026-10-12", "2026-10-16")
    assert [(m.day, m.code, m.streak) for m in found] == [
        ("2026-10-12", "E", 1), ("2026-10-13", "A", 2)]
    assert found[1].question() == ("The Tuesday 05:00-06:30 block of A 1001grantR01 "
                                   "was missed for the second week in a row. What "
                                   "took that slot?")
    assert found[0].question() == ("The Monday 13:00-14:30 block of E email was "
                                   "missed. What took that slot?")
    assert misses.facts(found).splitlines()[1] == (
        "Missed block 2: Tuesday 05:00-06:30, generative, A 1001grantR01, missed in "
        "this slot 2 weeks in a row")


def test_reasons_are_saved_replaced_and_removed(tmp_path):
    con = build(tmp_path / "h.db")
    found = misses.find(con, "2026-10-12", "2026-10-16")
    misses.save(con, found[1], found[1].question(), "Committee meeting moved")
    misses.save(con, found[1], found[1].question(), "  The committee met at 5  ")
    assert misses.find(con, "2026-10-12", "2026-10-16")[1].reason == "The committee met at 5"
    misses.save(con, found[1], found[1].question(), "")
    assert con.execute("SELECT COUNT(*) FROM block_miss").fetchone()[0] == 0


def test_the_model_only_rewords_the_questions(tmp_path):
    con = build(tmp_path / "h.db")
    found = misses.find(con, "2026-10-12", "2026-10-16")
    good = ("1. What pulled you away from email on Monday at 13:00?\n"
            "2. Tuesday's 05:00 grant block slipped two weeks running. What took it?")
    answer = coach.ask_misses(coach.Client("tiny", opener=fake_model(good)), found)
    assert answer.data["questions"][1].startswith("Tuesday's 05:00 grant block")
    for bad, why in [("What happened?", "questions for 2 missed blocks"),
                     ("Was it email?\nYou were tired.", "not a question"),
                     ("What took it on day 9?\nWhat took Tuesday?", "number")]:
        answer = coach.ask_misses(coach.Client("tiny", opener=fake_model(bad)), found)
        assert answer.data["questions"] == misses.plain(found)
        assert why in answer.source
    assert coach.ask_misses(None, []).data["questions"] == []
