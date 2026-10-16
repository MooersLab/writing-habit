"""Block objectives and session reviews, the work-intensity records, with no Qt.

A planned block answers when the writer meant to write. Two small records
answer what the block was for and how it went:

``block_objective``
    One to three objectives committed to the block before it starts, each
    checked off when met. Measuring completion only over these, rather than
    over a long to-do list, keeps the ratio from punishing an ambitious list.
    Items that do not make the cut wait on the grasscatcher list in the weekly
    table file.

``session_review``
    The thirty-second review written when the block ends: objectives met of
    those committed, a focus rating from 1 to 5, a tally of interruptions, an
    optional measure of output, and a next-step note for the next session.

Both are keyed by the planned block, as its day, start time, and project code,
and never by a row of the ``session`` table. ``track sync`` inserts and
updates session rows only, so rerunning it cannot overwrite a review. When the
editor shifts a block, :func:`rekey` moves its records with it.

The module also computes what the dashboard shows from these records: the done
list, the outcome of each planned block, and the personal bests.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from . import db

#: The number of objectives a block should carry at most. More are allowed,
#: but the editor warns, because a long list is the failure the cap prevents.
OBJECTIVE_LIMIT = 3

#: The share of a planned block's minutes that counts it as kept.
KEPT_SHARE = 0.5

#: The fields of a review the writer types, in the order the editor shows them.
REVIEW_FIELDS = ("objectives_committed", "objectives_met", "focus",
                 "interruptions", "output_units", "next_step", "note", "debrief",
                 "source_ref")


@dataclass(frozen=True)
class BlockKey:
    """The planned block a record belongs to."""

    day: str          # ISO date
    start: str        # HH:MM
    code: str         # legend code, without an activity letter

    @classmethod
    def for_block(cls, monday: _dt.date, block) -> "BlockKey":
        """Return the key of a :class:`~writing_habit.gui.weekly_table.Block`."""
        day = monday + _dt.timedelta(days=block.offset)
        return cls(day.isoformat(), block.start, block.letter)


@dataclass
class Objective:
    objective_id: int
    text: str
    done: bool
    origin: str = "typed"
    position: int = 0


@dataclass
class Review:
    """A session review.  ``None`` means the field was left blank."""

    objectives_committed: Optional[int] = None
    objectives_met: Optional[int] = None
    focus: Optional[int] = None
    interruptions: Optional[int] = None
    output_units: Optional[str] = None
    next_step: Optional[str] = None
    note: Optional[str] = None
    debrief: Optional[str] = None
    source_ref: Optional[str] = None
    updated_at: Optional[str] = None

    def is_blank(self) -> bool:
        return all(getattr(self, name) in (None, "") for name in REVIEW_FIELDS)


def ensure(con: sqlite3.Connection) -> None:
    """Create the work-intensity tables in an older database.  Safe to repeat."""
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    if not {"block_objective", "session_review", "v_week_review"} <= have:
        db.init_db(con)


# -- objectives ----------------------------------------------------------------
def objectives(con, key: BlockKey) -> List[Objective]:
    rows = con.execute(
        "SELECT objective_id, text, done, origin, position FROM block_objective"
        " WHERE day = ? AND start_time = ? AND code = ?"
        " ORDER BY position, objective_id",
        (key.day, key.start, key.code))
    return [Objective(r[0], r[1], bool(r[2]), r[3], r[4]) for r in rows]


def add_objective(con, key: BlockKey, text: str, origin: str = "typed") -> int:
    """Add one objective at the end of the block's list.  Return its id."""
    text = (text or "").strip()
    if not text:
        raise ValueError("an objective needs some text")
    position = con.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM block_objective"
        " WHERE day = ? AND start_time = ? AND code = ?",
        (key.day, key.start, key.code)).fetchone()[0]
    cur = con.execute(
        "INSERT INTO block_objective(day, start_time, code, position, text, origin)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (key.day, key.start, key.code, position, text, origin))
    con.commit()
    return int(cur.lastrowid)


def mark(con, objective_id: int, done: bool) -> None:
    con.execute(
        "UPDATE block_objective SET done = ?,"
        " done_at = CASE WHEN ? THEN datetime('now') END WHERE objective_id = ?",
        (int(bool(done)), int(bool(done)), objective_id))
    con.commit()


def edit_objective(con, objective_id: int, text: str) -> None:
    text = (text or "").strip()
    if not text:
        raise ValueError("an objective needs some text")
    con.execute("UPDATE block_objective SET text = ? WHERE objective_id = ?",
                (text, objective_id))
    con.commit()


def remove_objective(con, objective_id: int) -> Optional[Objective]:
    """Delete one objective and return it, so it can go back to the grasscatcher."""
    row = con.execute(
        "SELECT objective_id, text, done, origin, position FROM block_objective"
        " WHERE objective_id = ?", (objective_id,)).fetchone()
    if row is None:
        return None
    con.execute("DELETE FROM block_objective WHERE objective_id = ?", (objective_id,))
    con.commit()
    return Objective(row[0], row[1], bool(row[2]), row[3], row[4])


def counts(con, key: BlockKey) -> tuple:
    """Return ``(committed, met)`` for the block's objectives."""
    items = objectives(con, key)
    return len(items), sum(1 for o in items if o.done)


# -- reviews -------------------------------------------------------------------
def review(con, key: BlockKey) -> Review:
    """Return the block's review, or a blank one."""
    row = con.execute(
        "SELECT * FROM session_review WHERE day = ? AND start_time = ? AND code = ?",
        (key.day, key.start, key.code)).fetchone()
    if row is None:
        return Review()
    names = row.keys() if hasattr(row, "keys") else None
    if names is None:                                   # pragma: no cover
        raise TypeError("connect with writing_habit.db.connect for named rows")
    return Review(**{k: row[k] for k in (*REVIEW_FIELDS, "updated_at")})


def _check(value: Review) -> None:
    if value.focus is not None and not 1 <= int(value.focus) <= 5:
        raise ValueError("focus is a rating from 1 to 5")
    for name in ("objectives_committed", "objectives_met", "interruptions"):
        number = getattr(value, name)
        if number is not None and int(number) < 0:
            raise ValueError(f"{name.replace('_', ' ')} cannot be negative")
    if (value.objectives_committed is not None and value.objectives_met is not None
            and value.objectives_met > value.objectives_committed):
        raise ValueError("more objectives met than were committed")


def save_review(con, key: BlockKey, value: Review) -> Review:
    """Write the block's review, replacing any earlier one.  Return what was stored.

    When the block has objectives, the committed and met counts come from them,
    so the two places cannot disagree. A review with every field blank deletes
    the stored one.
    """
    committed, met = counts(con, key)
    if committed:
        value.objectives_committed, value.objectives_met = committed, met
    _check(value)
    if value.is_blank():
        con.execute("DELETE FROM session_review WHERE day = ? AND start_time = ?"
                    " AND code = ?", (key.day, key.start, key.code))
        con.commit()
        return value
    fields = {name: getattr(value, name) for name in REVIEW_FIELDS}
    columns = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{name} = excluded.{name}" for name in fields)
    con.execute(
        f"INSERT INTO session_review(day, start_time, code, {columns})"
        f" VALUES (?, ?, ?, {marks})"
        f" ON CONFLICT(day, start_time, code) DO UPDATE SET {updates},"
        " updated_at = datetime('now')",
        (key.day, key.start, key.code, *fields.values()))
    con.commit()
    return review(con, key)


def rekey(con, old: BlockKey, new: BlockKey) -> int:
    """Move a block's objectives and review to its new start.  Return rows moved.

    A review already stored under the new key wins, so a shift onto a slot that
    once held another reviewed block never merges two reviews.
    """
    if old == new:
        return 0
    moved = con.execute(
        "UPDATE block_objective SET day = ?, start_time = ?, code = ?"
        " WHERE day = ? AND start_time = ? AND code = ?",
        (new.day, new.start, new.code, old.day, old.start, old.code)).rowcount
    clash = con.execute(
        "SELECT 1 FROM session_review WHERE day = ? AND start_time = ? AND code = ?",
        (new.day, new.start, new.code)).fetchone()
    if clash is None:
        moved += con.execute(
            "UPDATE session_review SET day = ?, start_time = ?, code = ?"
            " WHERE day = ? AND start_time = ? AND code = ?",
            (new.day, new.start, new.code, old.day, old.start, old.code)).rowcount
    con.commit()
    return moved


def last_next_step(con, code: str, before: BlockKey) -> Optional[str]:
    """Return the most recent next-step note for ``code`` before ``before``."""
    row = con.execute(
        "SELECT next_step FROM session_review WHERE code = ?"
        " AND next_step IS NOT NULL AND next_step != ''"
        " AND (day < ? OR (day = ? AND start_time < ?))"
        " ORDER BY day DESC, start_time DESC LIMIT 1",
        (code, before.day, before.day, before.start)).fetchone()
    return row[0] if row else None


# -- what the dashboard reads ----------------------------------------------------
def has_records(con, week_start: str) -> bool:
    """Say whether the week holds any objective or review."""
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not {"block_objective", "session_review"} <= have:
        return False
    for table in ("block_objective", "session_review"):
        if con.execute(f"SELECT 1 FROM {table} WHERE week_start = ? LIMIT 1",
                       (week_start,)).fetchone():
            return True
    return False


def done_list(con, week_start: str) -> List[dict]:
    """Return the objectives met in the week, in day and time order."""
    rows = con.execute(
        "SELECT o.day, o.start_time, o.code, o.text, p.description"
        " FROM block_objective o LEFT JOIN project p ON p.code = o.code"
        " WHERE o.week_start = ? AND o.done = 1"
        " ORDER BY o.day, o.start_time, o.position, o.objective_id",
        (week_start,))
    return [dict(day=r[0], start=r[1], code=r[2], text=r[3], project=r[4])
            for r in rows]


def _minutes(clock: Optional[str]) -> Optional[int]:
    if not clock:
        return None
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def block_outcomes(con, week_start: str, today: Optional[str] = None) -> List[dict]:
    """Return each planned block of the week with what happened to it.

    A block's actual minutes are the minutes of the same project's sessions
    that day that fall inside the block's window. A session tracked as a
    duration only counts toward the first of that project's blocks that day.
    The status is ``kept`` at half the planned minutes or more, ``partial``
    below that, ``missed`` at none, and ``ahead`` for a block after ``today``.
    """
    today = today or _dt.date.today().isoformat()
    blocks = [dict(r) for r in con.execute(
        "SELECT b.day, b.start_time, b.end_time, b.planned_min, p.code,"
        " p.description, c.name AS category"
        " FROM plan_block b JOIN project p USING(project_id)"
        " JOIN category c USING(category_id)"
        " WHERE b.week_start = ? ORDER BY b.day, b.start_time, p.code",
        (week_start,))]
    sessions = [dict(r) for r in con.execute(
        "SELECT s.day, s.start_time, s.end_time, s.actual_min, p.code"
        " FROM session s JOIN project p USING(project_id) WHERE s.week_start = ?",
        (week_start,))]
    used_untimed: set = set()
    reviewed = {}
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "session_review" in have:
        for r in con.execute(
                "SELECT day, start_time, code, focus, objectives_committed,"
                " objectives_met FROM session_review WHERE week_start = ?",
                (week_start,)):
            reviewed[(r[0], r[1], r[2])] = dict(focus=r[3], committed=r[4], met=r[5])
    out = []
    for block in blocks:
        first, last = _minutes(block["start_time"]), _minutes(block["end_time"])
        actual = 0
        for index, s in enumerate(sessions):
            if s["day"] != block["day"] or s["code"] != block["code"]:
                continue
            s_first, s_last = _minutes(s["start_time"]), _minutes(s["end_time"])
            if s_first is None or s_last is None:
                key = (block["day"], block["code"], index)
                if key not in used_untimed:
                    used_untimed.add(key)
                    actual += min(int(s["actual_min"]), block["planned_min"])
                continue
            if s_last <= s_first:
                s_last += 24 * 60
            actual += max(0, min(last, s_last) - max(first, s_first))
        actual = min(actual, block["planned_min"])
        if block["day"] > today:
            status = "ahead"
        elif actual == 0:
            status = "missed"
        elif actual >= KEPT_SHARE * block["planned_min"]:
            status = "kept"
        else:
            status = "partial"
        block.update(actual_min=actual, status=status,
                     review=reviewed.get((block["day"], block["start_time"],
                                          block["code"])))
        out.append(block)
    return out


@dataclass
class Best:
    """One personal best: a label, the value as text, and the week it came from."""

    label: str
    value: str
    week: str
    this_week: bool = False


def personal_bests(con, week_start: str) -> List[Best]:
    """Return the writer's bests over every week up to ``week_start``.

    Only weeks with a plan count toward the adherence best, so an unplanned
    week of extra writing does not set an unreachable mark. A best that the
    week itself holds is flagged, so the dashboard can say so.
    """
    out: List[Best] = []
    weeks = [dict(r) for r in con.execute(
        "SELECT week_start, planned_min, actual_min, adherence FROM v_week_overall"
        " WHERE week_start <= ? ORDER BY week_start", (week_start,))]
    planned = [w for w in weeks if w["planned_min"] and w["adherence"] is not None]
    if planned:
        best = max(planned, key=lambda w: (min(w["adherence"], 1.0), w["actual_min"]))
        out.append(Best("Most of the plan kept",
                        f"{round(min(best['adherence'], 1.0) * 100)}%",
                        best["week_start"], best["week_start"] == week_start))
    if weeks:
        best = max(weeks, key=lambda w: w["actual_min"])
        if best["actual_min"]:
            hours, minutes = divmod(int(best["actual_min"]), 60)
            out.append(Best("Most minutes written",
                            f"{hours} h {minutes:02d} min",
                            best["week_start"], best["week_start"] == week_start))
    run, longest, longest_end, previous = 0, 0, None, None
    for r in con.execute("SELECT day FROM v_day_actual WHERE worked = 1"
                         " AND week_start <= ? ORDER BY day", (week_start,)):
        day = _dt.date.fromisoformat(r[0])
        run = run + 1 if previous and (day - previous).days == 1 else 1
        if run > longest:
            longest, longest_end = run, day
        previous = day
    if longest:
        end_week = (longest_end - _dt.timedelta(days=longest_end.weekday())).isoformat()
        out.append(Best("Longest run of writing days", f"{longest} day{'' if longest == 1 else 's'}",
                        end_week, end_week == week_start))
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'view'")}
    if "v_week_review" in have:
        rows = [dict(r) for r in con.execute(
            "SELECT week_start, met, mean_focus, reviews FROM v_week_review"
            " WHERE week_start <= ?", (week_start,))]
        met = [r for r in rows if r["met"]]
        if met:
            best = max(met, key=lambda r: r["met"])
            out.append(Best("Most objectives met", str(best["met"]),
                            best["week_start"], best["week_start"] == week_start))
        focused = [r for r in rows if r["mean_focus"] is not None and r["reviews"] >= 3]
        if focused:
            best = max(focused, key=lambda r: r["mean_focus"])
            out.append(Best("Most focused week", f"{best['mean_focus']:.1f} of 5",
                            best["week_start"], best["week_start"] == week_start))
    return out


def planned_weeks(con, week_start: str) -> int:
    """Return how many weeks up to ``week_start`` carry a plan."""
    return con.execute(
        "SELECT COUNT(*) FROM v_week_overall WHERE planned_min > 0 AND week_start <= ?",
        (week_start,)).fetchone()[0]
