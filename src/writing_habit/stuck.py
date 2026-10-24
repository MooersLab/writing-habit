"""Stuck projects: work that keeps missing its objectives.

A weekly loop can hide a quiet failure. A project gets its blocks and the
writer shows up, yet the same objective goes unmet block after block. This
module looks at a project's recent blocks with objectives and its reviews and
names three signs, in this order:

``repeated``
    One objective, written the same way, has gone unmet in two or more of the
    project's last few blocks. It is usually too big for a block.
``low``
    Over the project's last three blocks with objectives, at most a third of
    the objectives were met.
``same_step``
    The next-step note of the project's last two reviews reads the same, so
    the session keeps starting at the same place.

The remedy is to break the task into smaller objectives, which is what the
coach's Suggest does. The review panel shows the sign when a block of a stuck
project is opened and puts the stuck task in the Suggest box. Nothing here
imports Qt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

#: How many of a project's most recent blocks with objectives are read.
RECENT = 3
#: Met objectives at or below this share of those committed signal a stuck project.
LOW_SHARE = 1 / 3


@dataclass
class Stuck:
    """One project that shows a sign of being stuck."""

    code: str
    project: str
    kind: str              # "repeated", "low", or "same_step"
    task: str              # the work to break into smaller steps
    blocks: int            # the recent blocks read
    times: int = 0         # blocks in which the task went unmet, or reviews that repeat it
    met: int = 0
    committed: int = 0

    def sentence(self) -> str:
        """Say what was found, plainly."""
        who = f"{self.code} {self.project}".strip()
        if self.kind == "repeated":
            return (f"“{self.task}” has gone unmet in {self.times} of the last "
                    f"{self.blocks} blocks of {who}.")
        if self.kind == "low":
            return (f"{who} met {self.met} of {self.committed} objectives over its "
                    f"last {self.blocks} blocks.")
        return (f"The next step for {who} has read “{self.task}” in its last "
                f"{self.times} reviews.")

    def advice(self) -> str:
        return ("Break it into smaller objectives that can each be finished in "
                "one block. Press Suggest to have the coach draft them.")


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", (text or "").lower())).strip()


def _before(day: str, start: str, before: Optional[Tuple[str, str]]) -> bool:
    return before is None or (day, start) < before


def check(con, code: str, before: Optional[Tuple[str, str]] = None,
          today: Optional[str] = None) -> Optional[Stuck]:
    """Return the first sign that project ``code`` is stuck, or ``None``.

    Only blocks that start before ``before``, a ``(day, start)`` pair, and on
    or before ``today`` are read, so a block does not judge itself.
    """
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "block_objective" not in have:
        return None
    row = con.execute("SELECT description FROM project WHERE code = ?", (code,)).fetchone()
    project = (row[0] or "") if row else ""
    blocks: Dict[Tuple[str, str], List[Tuple[str, int]]] = {}
    for day, start, text, done in con.execute(
            "SELECT day, start_time, text, done FROM block_objective WHERE code = ?"
            " ORDER BY day, start_time, position, objective_id", (code,)):
        if _before(day, start, before) and (today is None or day <= today):
            blocks.setdefault((day, start), []).append((text, int(done)))
    recent = sorted(blocks)[-RECENT:]
    if recent:
        unmet: Dict[str, List[str]] = {}
        for key in recent:
            for text, done in blocks[key]:
                if not done:
                    unmet.setdefault(normalize(text), []).append(text)
        repeated = [(len(texts), texts[-1]) for texts in unmet.values() if len(texts) >= 2]
        if repeated:
            times, task = max(repeated)
            return Stuck(code, project, "repeated", task, len(recent), times=times)
        committed = sum(len(blocks[k]) for k in recent)
        met = sum(done for k in recent for _t, done in blocks[k])
        if len(recent) >= RECENT and met <= LOW_SHARE * committed:
            last_unmet = next((t for k in reversed(recent) for t, d in blocks[k] if not d),
                              blocks[recent[-1]][0][0])
            return Stuck(code, project, "low", last_unmet, len(recent),
                         met=met, committed=committed)
    if "session_review" in have:
        steps = [(day, start, step) for day, start, step in con.execute(
            "SELECT day, start_time, next_step FROM session_review WHERE code = ?"
            " AND next_step IS NOT NULL AND TRIM(next_step) != ''"
            " ORDER BY day, start_time", (code,))
                 if _before(day, start, before) and (today is None or day <= today)]
        if len(steps) >= 2 and normalize(steps[-1][2]) == normalize(steps[-2][2]):
            return Stuck(code, project, "same_step", steps[-1][2].strip(),
                         len(recent), times=2)
    return None


def find(con, codes, today: Optional[str] = None) -> List[Stuck]:
    """Return the stuck projects among ``codes``, in the order given."""
    out = []
    for code in codes:
        found = check(con, code, today=today)
        if found is not None:
            out.append(found)
    return out


def report(found: List[Stuck]) -> str:
    """Describe the stuck projects, or say there are none."""
    if not found:
        return ("No project shows a sign of being stuck. Every recent block met "
                "enough of its objectives, and no next step repeats.")
    lines = [s.sentence() for s in found]
    lines.append("")
    lines.append("Open the next block of each project in the hour view. Its "
                 "review panel puts the stuck task in the objective box, and "
                 "Suggest breaks it into smaller objectives.")
    return "\n".join(lines)
