"""Why each missed block was missed: one question each, answered by the writer.

Rule 6 asks the writer to record why each missed block was missed, because
the reasons are what the comparison of plan and practice cannot show. This
module lists the week's missed blocks, notes a block missed in the same slot
in earlier weeks too, and writes one short question for each, such as
``The Tuesday 05:00-06:30 block of A 1001grantR01 was missed for the second
week in a row. What took that slot?``. The writer answers in a sentence, and
the answer is kept in the ``block_miss`` table.

The coach only asks. A model may reword the questions, and it is never asked
for a reason, because only the writer knows it and a model left to explain a
missed block will guess. Nothing here imports Qt.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from . import review
from .name import split_deadline

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]
_ORDINALS = {2: "second", 3: "third", 4: "fourth", 5: "fifth"}
#: Earlier weeks read for a repeat in the same slot.
LOOK_BACK = 4


@dataclass
class Miss:
    """One missed block of the week, and the question about it."""

    day: str
    start: str
    end: str
    code: str
    project: str
    category: str
    streak: int = 1            # weeks in a row this slot was missed, this one included
    reason: str = ""           # the writer's answer, when one is saved

    @property
    def weekday(self) -> str:
        return DAY_NAMES[_dt.date.fromisoformat(self.day).weekday()]

    def label(self) -> str:
        return f"{self.weekday} {self.start}-{self.end} block of {self.code} {self.project}".rstrip()

    def question(self) -> str:
        """The plain question, with the streak when the slot keeps being missed."""
        if self.streak >= 2:
            times = (f" for the {_ORDINALS[self.streak]} week in a row"
                     if self.streak in _ORDINALS else
                     f" for {self.streak} weeks in a row")
        else:
            times = ""
        return f"The {self.label()} was missed{times}. What took that slot?"


def _slot_missed(outcomes: Sequence[dict], weekday: int, start: str, code: str) -> bool:
    return any(o["status"] == "missed" and o["start_time"] == start and o["code"] == code
               and _dt.date.fromisoformat(o["day"]).weekday() == weekday
               for o in outcomes)


def find(con, week_start: str, today: Optional[str] = None) -> List[Miss]:
    """Return the missed blocks of the week starting ``week_start``, in time order."""
    review.ensure(con)
    outcomes = review.block_outcomes(con, week_start, today)
    monday = _dt.date.fromisoformat(week_start)
    earlier = [review.block_outcomes(con, (monday - _dt.timedelta(weeks=n)).isoformat(),
                                     week_start)
               for n in range(1, LOOK_BACK + 1)]
    saved = {(r[0], r[1], r[2]): r[3] for r in con.execute(
        "SELECT day, start_time, code, reason FROM block_miss WHERE week_start = ?",
        (week_start,))}
    out = []
    for o in outcomes:
        if o["status"] != "missed":
            continue
        weekday = _dt.date.fromisoformat(o["day"]).weekday()
        streak = 1
        for week in earlier:
            if not _slot_missed(week, weekday, o["start_time"], o["code"]):
                break
            streak += 1
        out.append(Miss(o["day"], o["start_time"], o["end_time"], o["code"],
                        split_deadline(o["description"] or "")[0], o["category"],
                        streak, saved.get((o["day"], o["start_time"], o["code"]), "")))
    return out


def save(con, miss: Miss, question: str, reason: str) -> None:
    """Keep the writer's reason for a missed block, replacing an earlier one."""
    review.ensure(con)
    reason = reason.strip()
    if not reason:
        con.execute("DELETE FROM block_miss WHERE day = ? AND start_time = ? AND code = ?",
                    (miss.day, miss.start, miss.code))
    else:
        con.execute(
            "INSERT INTO block_miss(day, start_time, code, question, reason)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT(day, start_time, code)"
            " DO UPDATE SET question = excluded.question, reason = excluded.reason",
            (miss.day, miss.start, miss.code, question, reason))
    con.commit()


def facts(found: Sequence[Miss]) -> str:
    """Write the missed blocks as the facts the model receives, one per line."""
    lines = []
    for i, m in enumerate(found, 1):
        line = (f"Missed block {i}: {m.weekday} {m.start}-{m.end}, {m.category}, "
                f"{m.code} {m.project}").rstrip()
        if m.streak >= 2:
            line += f", missed in this slot {m.streak} weeks in a row"
        lines.append(line)
    return "\n".join(lines)


def plain(found: Sequence[Miss]) -> List[str]:
    return [m.question() for m in found]


def parse(reply, found: Sequence[Miss]) -> List[str]:
    """Read one question per missed block from a model's reply, or raise ``ValueError``.

    The reply must hold one question for each block, in order, each ending
    with a question mark.
    """
    lines = [re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", line).strip()
             for line in str(reply or "").splitlines()]
    lines = [line for line in lines if line]
    if len(lines) != len(found):
        raise ValueError(f"the reply held {len(lines)} questions for "
                         f"{len(found)} missed blocks")
    if not all(line.endswith("?") for line in lines):
        raise ValueError("a line of the reply was not a question")
    return lines


def intro(found: Sequence[Miss]) -> str:
    """The note above the questions."""
    if not found:
        return ("No block of this week has been missed so far, so there is "
                "nothing to ask about.")
    return (f"{len(found)} block{'' if len(found) == 1 else 's'} "
            f"{'was' if len(found) == 1 else 'were'} missed this week. Answer each "
            "question in a sentence. A missed block is information, and the "
            "reason is what the weekly comparison cannot show.")
