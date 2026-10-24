"""The writer's energy through the day, and blocks that do not fit it.

Rule 2 of the Ten Simple Rules paper says to put generative work in the hours
when the writer thinks best. An energy profile records, for each activity and
each hour of the day, whether that hour is a high, medium, or low time for
that kind of writing. The writer sets it on the Energy tab, starting from a
default or from their own focus ratings.

A block fits when its activity's level over the block's hours is medium or
better. Two kinds of block do not fit. A generative or editing block that
falls mostly in low hours asks for focus when it is scarce. A support block
that falls in the writer's best generative hours spends them on email and
chores. A swap exchanges the work of two blocks of equal length on the same
day, so every project keeps its minutes, and is proposed only when it makes
the week fit better.

Nothing here imports Qt, and nothing here changes a file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

ACTIVITIES = ("generative", "editing", "support")
LEVELS = ("low", "medium", "high")
LOW, MEDIUM, HIGH = 0, 1, 2

#: A block fits its activity when the mean level of its hours reaches this.
FITS = 1.0
#: A support block in hours this high for generative work spends peak time.
PEAK = 1.5
#: Reviews needed in an hour before its mean focus can set a level.
MIN_REVIEWS = 3

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


def _levels(*spans: Tuple[int, int, int]) -> List[int]:
    """Return 24 levels, low everywhere except the ``(first, last, level)`` spans."""
    out = [LOW] * 24
    for first, last, level in spans:
        for hour in range(first, last):
            out[hour] = level
    return out


#: A common pattern: fresh mornings for new writing, late mornings and early
#: evenings for editing, and the afternoon dip for support tasks.
DEFAULT_PROFILE: Dict[str, List[int]] = {
    "generative": _levels((5, 10, HIGH), (10, 12, MEDIUM), (19, 21, MEDIUM)),
    "editing": _levels((5, 9, MEDIUM), (9, 12, HIGH), (13, 17, MEDIUM),
                       (17, 21, MEDIUM)),
    "support": _levels((7, 10, MEDIUM), (10, 13, MEDIUM), (13, 17, HIGH),
                       (17, 20, MEDIUM)),
}


def default_profile() -> Dict[str, List[int]]:
    return {activity: list(levels) for activity, levels in DEFAULT_PROFILE.items()}


def load(text: Optional[str]) -> Dict[str, List[int]]:
    """Read a profile saved as JSON, falling back to the default for anything bad."""
    profile = default_profile()
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return profile
    if not isinstance(data, dict):
        return profile
    for activity in ACTIVITIES:
        levels = data.get(activity)
        if (isinstance(levels, list) and len(levels) == 24
                and all(level in (LOW, MEDIUM, HIGH) for level in levels)):
            profile[activity] = list(levels)
    return profile


def dump(profile: Dict[str, List[int]]) -> str:
    return json.dumps({activity: profile[activity] for activity in ACTIVITIES},
                      separators=(",", ":"))


def _minute(clock: str) -> int:
    return int(clock[:2]) * 60 + int(clock[3:5])


def fit(profile: Dict[str, List[int]], activity: str, start: str, end: str) -> float:
    """Return the mean level, 0 to 2, of ``activity`` over the block's quarter hours."""
    levels = profile.get(activity) or profile["generative"]
    first, last = _minute(start), _minute(end)
    if last <= first:
        last += 24 * 60
    quarters = [levels[(m // 60) % 24] for m in range(first, last, 15)]
    return sum(quarters) / len(quarters) if quarters else float(MEDIUM)


def word(value: float) -> str:
    """Name a mean level the way a writer would say it."""
    if value >= 1.75:
        return "high"
    if value >= 1.25:
        return "mostly high"
    if value >= 0.75:
        return "medium"
    if value >= 0.25:
        return "mostly low"
    return "low"


@dataclass
class Slot:
    """One planned block of the open week, as the matcher sees it."""

    offset: int
    start: str
    end: str
    code: str
    category: str
    minutes: int
    row: int = -1
    column: int = -1

    def label(self) -> str:
        return f"{DAY_NAMES[self.offset]} {self.start}-{self.end}"


@dataclass
class Misfit:
    """A block whose hours do not suit its activity."""

    slot: Slot
    kind: str            # "low" for demanding work in low hours, "peak" for support in peak hours
    level: float         # the level of the block's own activity over its hours


@dataclass
class Swap:
    """Exchange the work of two blocks of equal length on one day."""

    first: Slot
    second: Slot
    before: float        # the two blocks' combined fit now
    after: float         # their combined fit after the swap


def misfits(profile: Dict[str, List[int]], slots: Sequence[Slot]) -> List[Misfit]:
    """Return the blocks that do not fit, in day and time order."""
    out = []
    for s in sorted(slots, key=lambda s: (s.offset, s.start)):
        own = fit(profile, s.category, s.start, s.end)
        if s.category in ("generative", "editing") and own < FITS:
            out.append(Misfit(s, "low", own))
        elif (s.category == "support"
              and fit(profile, "generative", s.start, s.end) >= PEAK):
            out.append(Misfit(s, "peak", own))
    return out


def _value(profile, s: Slot, start: str, end: str) -> float:
    """How well ``s``'s work fits the hours from ``start`` to ``end``.

    Support work earns nothing for sitting in good hours, because the point of
    a swap is to give those hours to work that needs them.
    """
    if s.category == "support":
        return -fit(profile, "generative", start, end) / 2
    return fit(profile, s.category, start, end)


def swaps(profile: Dict[str, List[int]], slots: Sequence[Slot],
          movable=lambda s: True) -> List[Swap]:
    """Propose swaps that make the misfits fit, best first, each block used once.

    Only blocks for which ``movable`` is true take part, so a swap never touches
    a block that has already passed. Both blocks must be on the same day and
    of the same length, so each project keeps its minutes and its day.
    """
    bad = {(m.slot.row, m.slot.column) for m in misfits(profile, slots)}
    pool = [s for s in slots if movable(s)]
    options = []
    for i, a in enumerate(pool):
        for b in pool[i + 1:]:
            if a.offset != b.offset or a.minutes != b.minutes:
                continue
            if (a.category, a.code) == (b.category, b.code):
                continue
            if (a.row, a.column) not in bad and (b.row, b.column) not in bad:
                continue
            before = _value(profile, a, a.start, a.end) + _value(profile, b, b.start, b.end)
            after = _value(profile, a, b.start, b.end) + _value(profile, b, a.start, a.end)
            if after - before > 0.25:
                options.append(Swap(a, b, before, after))
    options.sort(key=lambda w: (-(w.after - w.before), w.first.offset, w.first.start))
    used, out = set(), []
    for w in options:
        keys = {(w.first.row, w.first.column), (w.second.row, w.second.column)}
        if keys & used:
            continue
        used |= keys
        out.append(w)
    return out


def swap_line(w: Swap) -> str:
    """One checkable line for the dialog."""
    return (f"{DAY_NAMES[w.first.offset]}: swap {w.first.category} {w.first.code} "
            f"at {w.first.start}-{w.first.end} with {w.second.category} {w.second.code} "
            f"at {w.second.start}-{w.second.end}")


def misfit_line(profile, m: Misfit) -> str:
    s = m.slot
    if m.kind == "low":
        return (f"{s.label()}  {s.category} {s.code} falls in {word(m.level)} hours "
                f"for {s.category} work")
    return (f"{s.label()}  support {s.code} uses your "
            f"{word(fit(profile, 'generative', s.start, s.end))} hours for generative work")


def facts(profile, found: Sequence[Misfit], proposed: Sequence[Swap]) -> str:
    """Write the reading as the facts the model receives, in words and no scores."""
    lines = []
    for m in found:
        lines.append("Block that does not fit: " + misfit_line(profile, m))
    for w in proposed:
        a, b = w.first, w.second
        lines.append(f"Proposed swap: {swap_line(w)}. Afterwards {a.category} {a.code} "
                     f"sits in {word(fit(profile, a.category, b.start, b.end))} hours "
                     f"for {a.category} work and {b.category} {b.code} sits in "
                     f"{word(fit(profile, b.category, a.start, a.end))} hours for "
                     f"{b.category} work")
    if found and not proposed:
        lines.append("Proposed swap: none, because no block of the same length "
                     "on the same day would fit better")
    return "\n".join(lines)


def plain(profile, found: Sequence[Misfit], proposed: Sequence[Swap]) -> str:
    """Describe the reading without a model."""
    if not found:
        return "Every block of the week fits your energy profile."
    lines = [f"{len(found)} block{'' if len(found) == 1 else 's'} "
             f"{'does' if len(found) == 1 else 'do'} not fit your energy profile."]
    lines += ["  " + misfit_line(profile, m) for m in found]
    if proposed:
        lines.append("")
        lines.append("Swapping the work of these blocks keeps every project's "
                     "minutes and puts demanding work in better hours.")
    else:
        lines.append("")
        lines.append("No block of the same length on the same day would fit "
                     "better, so move these by hand or adjust the profile.")
    return "\n".join(lines)


# -- the profile from the writer's own focus ratings -------------------------------
def focus_by_hour(con) -> Dict[Tuple[str, int], List[int]]:
    """Return the focus ratings of reviewed blocks by activity and hour of day.

    A review is joined to its planned block for the activity and the end time,
    and its rating counts in every hour the block touches.
    """
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "session_review" not in have:
        return {}
    out: Dict[Tuple[str, int], List[int]] = {}
    rows = con.execute(
        "SELECT r.focus, b.start_time, b.end_time, c.name"
        " FROM session_review r"
        " JOIN project p ON p.code = r.code"
        " JOIN plan_block b ON b.day = r.day AND b.start_time = r.start_time"
        "  AND b.project_id = p.project_id"
        " JOIN category c USING(category_id)"
        " WHERE r.focus IS NOT NULL")
    for focus, start, end, activity in rows:
        first, last = _minute(start), _minute(end)
        if last <= first:
            last += 24 * 60
        for hour in sorted({(m // 60) % 24 for m in range(first, last, 15)}):
            out.setdefault((activity, hour), []).append(int(focus))
    return out


def level_for(mean_focus: float) -> int:
    """Map a mean focus rating, 1 to 5, to an energy level."""
    if mean_focus >= 4.0:
        return HIGH
    if mean_focus >= 3.0:
        return MEDIUM
    return LOW


@dataclass
class Change:
    activity: str
    hour: int
    old: int
    new: int
    mean: float
    reviews: int


def from_reviews(con, profile, min_reviews: int = MIN_REVIEWS):
    """Return ``(new profile, changes)`` from the writer's focus ratings.

    Only an hour with at least ``min_reviews`` ratings for an activity changes,
    so a single good or bad block does not rewrite the profile.
    """
    new = {activity: list(levels) for activity, levels in profile.items()}
    changes: List[Change] = []
    for (activity, hour), ratings in sorted(focus_by_hour(con).items()):
        if activity not in new or len(ratings) < min_reviews:
            continue
        mean = sum(ratings) / len(ratings)
        level = level_for(mean)
        if new[activity][hour] != level:
            changes.append(Change(activity, hour, new[activity][hour], level,
                                  round(mean, 1), len(ratings)))
            new[activity][hour] = level
    return new, changes
