"""The energy profile, blocks that do not fit it, swaps, and focus ratings."""

from writing_habit import coach, db, energy, review
from writing_habit.energy import HIGH, LOW, MEDIUM, Slot

from test_coach import fake_model


def test_the_default_profile_and_a_bad_saved_profile():
    profile = energy.default_profile()
    assert set(profile) == set(energy.ACTIVITIES)
    assert profile["generative"][6] == HIGH and profile["generative"][15] == LOW
    assert profile["support"][14] == HIGH
    assert energy.load("not json") == energy.default_profile()
    broken = '{"generative": [9, 9], "editing": "x"}'
    assert energy.load(broken) == energy.default_profile()
    profile["editing"][3] = HIGH
    assert energy.load(energy.dump(profile))["editing"][3] == HIGH


def test_fit_averages_the_quarter_hours_and_crosses_midnight():
    profile = energy.default_profile()
    assert energy.fit(profile, "generative", "05:00", "07:00") == 2.0
    # 09:30-10:30 is half high, half medium for generative work.
    assert energy.fit(profile, "generative", "09:30", "10:30") == 1.5
    assert energy.fit(profile, "generative", "23:00", "01:00") == 0.0
    assert energy.word(1.5) == "mostly high" and energy.word(0.0) == "low"


def _week():
    return [
        Slot(0, "05:00", "06:30", "E", "support", 90, 1, 1),      # support in peak hours
        Slot(0, "14:00", "15:30", "A", "generative", 90, 2, 1),   # generative after lunch
        Slot(0, "09:00", "10:00", "B", "editing", 60, 3, 1),      # fits
        Slot(1, "05:00", "07:00", "A", "generative", 120, 1, 2),  # fits
    ]


def test_misfits_find_both_kinds():
    profile = energy.default_profile()
    found = energy.misfits(profile, _week())
    assert [(m.slot.code, m.kind) for m in found] == [("E", "peak"), ("A", "low")]
    assert "support E uses your high hours for generative work" in energy.misfit_line(
        profile, found[0])
    assert "generative A falls in low hours" in energy.misfit_line(profile, found[1])


def test_a_swap_exchanges_equal_blocks_on_one_day():
    profile = energy.default_profile()
    proposed = energy.swaps(profile, _week())
    assert len(proposed) == 1
    w = proposed[0]
    assert {w.first.code, w.second.code} == {"E", "A"}
    assert w.after > w.before
    assert energy.swap_line(w) == ("Monday: swap support E at 05:00-06:30 with "
                                   "generative A at 14:00-15:30")


def test_no_swap_across_days_lengths_or_passed_blocks():
    profile = energy.default_profile()
    week = _week()
    week[1] = Slot(1, "14:00", "15:30", "A", "generative", 90, 2, 2)     # another day
    assert energy.swaps(profile, week) == []
    week = _week()
    week[1] = Slot(0, "14:00", "15:00", "A", "generative", 60, 2, 1)     # shorter
    # The 90-minute support block can no longer pair with A, but the 60-minute
    # editing block can, because the two are the same length.
    pairs = [{w.first.code, w.second.code} for w in energy.swaps(profile, week)]
    assert pairs == [{"A", "B"}]
    assert energy.swaps(profile, _week(), movable=lambda s: s.offset > 0) == []


def test_plain_and_facts_use_words_not_scores():
    profile = energy.default_profile()
    found = energy.misfits(profile, _week())
    proposed = energy.swaps(profile, _week())
    text = energy.plain(profile, found, proposed)
    assert text.startswith("2 blocks do not fit your energy profile.")
    assert "keeps every project's minutes" in text
    facts = energy.facts(profile, found, proposed)
    assert "generative A sits in high hours for generative work" in facts
    assert "1.5" not in facts and "2.0" not in facts
    assert energy.plain(profile, [], []) == "Every block of the week fits your energy profile."


def test_the_coach_words_the_reading(tmp_path):
    profile = energy.default_profile()
    found = energy.misfits(profile, _week())
    proposed = energy.swaps(profile, _week())
    reply = ("Your Monday email block sits in your best writing hours, while the "
             "grant waits until the afternoon dip. Swapping them gives the grant "
             "your fresh morning.")
    answer = coach.match_energy(coach.Client("tiny", opener=fake_model(reply)),
                                profile, found, proposed)
    assert answer.data["note"] == reply
    assert answer.data["swaps"] == proposed
    bad = coach.match_energy(coach.Client("tiny", opener=fake_model("Write 3 hours.")),
                             profile, found, proposed)
    assert bad.data["note"] == energy.plain(profile, found, proposed)


def _reviewed(con, day, start, end, code, category_id, focus):
    pid = db.get_or_create_project(con, code, f"project {code}", "safe")
    con.execute("INSERT INTO plan_block(day, start_time, end_time, project_id, category_id)"
                " VALUES (?, ?, ?, ?, ?)", (day, start, end, pid, category_id))
    review.save_review(con, review.BlockKey(day, start, code),
                       review.Review(focus=focus))


def test_the_profile_follows_three_or_more_focus_ratings(tmp_path):
    con = db.connect(str(tmp_path / "habit.db"))
    db.init_db(con)
    review.ensure(con)
    generative = con.execute("SELECT category_id FROM category WHERE name = 'generative'"
                             ).fetchone()[0]
    # Three afternoons of absorbed generative writing at 14:00, and one at 20:00.
    for day in ("2026-10-05", "2026-10-06", "2026-10-07"):
        _reviewed(con, day, "14:00", "15:00", "A", generative, 5)
    _reviewed(con, "2026-10-08", "20:00", "21:00", "A", generative, 1)
    con.commit()
    profile = energy.default_profile()
    new, changes = energy.from_reviews(con, profile)
    assert [(c.activity, c.hour, c.old, c.new, c.reviews) for c in changes] == [
        ("generative", 14, LOW, HIGH, 3)]
    assert new["generative"][14] == HIGH
    assert new["generative"][20] == MEDIUM          # one rating is not enough
    assert profile["generative"][14] == LOW         # the old profile is untouched
    con.close()


def test_no_reviews_change_nothing(tmp_path):
    con = db.connect(str(tmp_path / "habit.db"))
    db.init_db(con)
    new, changes = energy.from_reviews(con, energy.default_profile())
    assert changes == [] and new == energy.default_profile()
    con.close()
