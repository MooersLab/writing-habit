"""Missed-block rescue: which blocks to make up, where, and which to let go."""

import datetime as dt

from writing_habit import coach, energy, rescue
from writing_habit.energy import Slot

from test_coach import fake_model

MONDAY = dt.date(2026, 10, 12)
TUESDAY_NOON = dt.datetime(2026, 10, 13, 12, 0)
LEGEND = {"A": "1001grantR01 2026-10-30", "B": "2002review 2027-03-01", "E": "email"}

WEEK = [
    Slot(0, "05:00", "06:30", "A", "generative", 90, 1, 1),    # Monday, missed
    Slot(0, "13:00", "13:45", "E", "support", 45, 2, 1),       # Monday, missed
    Slot(1, "05:00", "07:00", "B", "generative", 120, 3, 2),   # Tuesday, kept
    Slot(1, "14:00", "15:30", "B", "generative", 90, 4, 2),    # Tuesday, still ahead
    Slot(2, "05:00", "07:00", "B", "generative", 120, 3, 3),   # Wednesday
]
OUTCOMES = [
    {"day": "2026-10-12", "start_time": "05:00", "code": "A", "status": "missed"},
    {"day": "2026-10-12", "start_time": "13:00", "code": "E", "status": "missed"},
    {"day": "2026-10-13", "start_time": "05:00", "code": "B", "status": "kept"},
    {"day": "2026-10-13", "start_time": "14:00", "code": "B", "status": "missed"},
]
DAYS = [0, 1, 2, 3, 4]


def test_only_passed_blocks_with_nothing_tracked_are_missed():
    missed = rescue.missed_blocks(WEEK, OUTCOMES, MONDAY, TUESDAY_NOON)
    # Tuesday's 14:00 block is marked missed by the database but has not ended.
    assert [(s.offset, s.start, s.code) for s in missed] == [(0, "05:00", "A"),
                                                            (0, "13:00", "E")]


def test_a_missed_block_moves_to_the_best_hours_that_keep_a_break():
    profile = energy.default_profile()
    missed = rescue.missed_blocks(WEEK, OUTCOMES, MONDAY, TUESDAY_NOON)
    found = rescue.plan(WEEK, missed, profile, DAYS, MONDAY, TUESDAY_NOON, LEGEND)
    a = next(r for r in found if r.missed.code == "A")
    # Wednesday 05:00-07:00 is taken, and 07:00 would make a run of three and a
    # half hours, so the first high-energy slot is 07:15-08:45.
    assert (a.offset, a.start, a.end) == (2, "07:15", "08:45")
    assert a.line() == ("Make up generative A from Monday 05:00-06:30 on "
                        "Wednesday 07:15-08:45")
    e = next(r for r in found if r.missed.code == "E")
    assert not e.rescued and "support work" in e.reason


def test_the_same_day_later_is_used_when_it_is_best():
    profile = {a: [energy.LOW] * 24 for a in energy.ACTIVITIES}
    profile["generative"][19] = profile["generative"][20] = energy.HIGH
    slot = rescue.find_slot(WEEK[0], WEEK, profile, DAYS, MONDAY,
                            dt.datetime(2026, 10, 12, 9, 7))
    assert slot[:3] == (0, "19:00", "20:30")


def test_today_starts_at_the_next_quarter_hour_after_now():
    profile = {a: [energy.HIGH] * 24 for a in energy.ACTIVITIES}
    slot = rescue.find_slot(WEEK[0], WEEK, profile, [0], MONDAY,
                            dt.datetime(2026, 10, 12, 9, 7))
    assert slot[:3] == (0, "09:15", "10:45")


def test_at_most_two_rescues_a_week():
    slots = [Slot(0, f"{h:02d}:00", f"{h:02d}:30", "A", "generative", 30, h, 1)
             for h in (5, 7, 9)]
    outcomes = [{"day": "2026-10-12", "start_time": s.start, "code": "A",
                 "status": "missed"} for s in slots]
    profile = {a: [energy.HIGH] * 24 for a in energy.ACTIVITIES}
    missed = rescue.missed_blocks(slots, outcomes, MONDAY, TUESDAY_NOON)
    found = rescue.plan(slots, missed, profile, DAYS, MONDAY, TUESDAY_NOON, LEGEND)
    assert sum(r.rescued for r in found) == 2
    assert "2 blocks are already being made up" in next(
        r for r in found if not r.rescued).reason


def test_no_slot_in_suitable_hours_lets_it_go():
    profile = {a: [energy.LOW] * 24 for a in energy.ACTIVITIES}
    missed = rescue.missed_blocks(WEEK, OUTCOMES, MONDAY, TUESDAY_NOON)
    found = rescue.plan(WEEK, missed, profile, DAYS, MONDAY, TUESDAY_NOON, LEGEND)
    a = next(r for r in found if r.missed.code == "A")
    assert not a.rescued and "no free time of that length" in a.reason


def test_the_plain_note_and_the_coach_wording():
    profile = energy.default_profile()
    missed = rescue.missed_blocks(WEEK, OUTCOMES, MONDAY, TUESDAY_NOON)
    found = rescue.plan(WEEK, missed, profile, DAYS, MONDAY, TUESDAY_NOON, LEGEND)
    text = rescue.plain(found)
    assert text.startswith("2 blocks passed with nothing tracked. A missed block is "
                           "information, not a failure.")
    assert "Generative A from Monday 05:00-06:30 can be made up on Wednesday 07:15-08:45." in text
    assert "Let support E from Monday 13:00-13:45 go" in text
    facts = rescue.facts(found, profile)
    reply = "Monday's grant block can move to Wednesday morning, and the email can go."
    answer = coach.rescue_missed(coach.Client("tiny", opener=fake_model(reply)),
                                 found, profile)
    assert answer.data["note"] == reply
    assert "in high hours for generative work" in facts
    assert rescue.plain([]).startswith("No block of this week has been missed")
