#!/usr/bin/env python3
"""Generate weekly writing-schedule org tables from schedule-code file names.

Each argument is a schedule code or a <code>.org file name, following the
naming spec in docs/table-file-naming-rules.org. For each one this writes a
writing-schedule table whose time blocks match the code exactly.

Layout rules:
  - The day starts at 07:00 on weekdays and 08:00 on the weekend, because a
    Saturday morning usually starts later.
  - Each day begins with its generative blocks, then editing, then support.
  - Blocks are 90 minutes with a 15-minute break, and a 60-minute lunch after
    the first block that ends at or after noon.
  - The number of rows in each section is the largest count of that activity on
    any one day, so a lighter day simply leaves the later rows empty.
  - Weekday blocks and weekend blocks never share a row, because their start
    times differ, so a Saturday gets its own rows.

Standard library only. Usage:
    python make_tables.py 2gA-2gB-gW.org 2gAeA-2gBeB-gW.org
    python make_tables.py --outdir tables 5gA 4gAeA-gW
"""

from __future__ import annotations

import argparse
import os
import re

DAY_ABBREV = ["M", "Tu", "W", "Th", "F", "Sa", "Su"]
SECTIONS = [("g", "Generative"), ("e", "Rewriting"), ("s", "Supporting")]
ACT = {"g": "generative", "e": "editing", "s": "support"}

# Project descriptions and risk classes for the legend. Edit to taste; any
# project not listed defaults to a safe placeholder.
PROJECTS = {
    "A": ("main project", "safe"),
    "B": ("second project", "safe"),
    "W": ("exploratory idea", "speculative"),
}

WEEKDAY_START = "07:00"
WEEKEND_START = "08:00"
BLOCK_MIN = 90
BREAK_MIN = 15
LUNCH_MIN = 60


def decode(code):
    """Return a list over days of ordered [(activity_letter, project), ...]."""
    days = []
    for grp in code.split("-"):
        m = re.fullmatch(r"(\d*)([A-Za-z]+)", grp)
        if not m:
            raise ValueError(f"invalid day-group {grp!r} in {code!r}")
        n = int(m.group(1) or 1)
        pat = m.group(2)
        if pat == "o":
            blocks = []
        else:
            blocks, act = [], None
            for ch in pat:
                if ch in ACT:
                    act = ch
                elif ch.isupper():
                    if act is None:
                        raise ValueError(f"project {ch!r} before an activity in {grp!r}")
                    blocks.append((act, ch))
                else:
                    raise ValueError(f"invalid character {ch!r} in {grp!r}")
        days += [blocks] * n
    if not days:
        raise ValueError(f"empty code {code!r}")
    if len(days) > 7:
        raise ValueError(f"{code!r} covers {len(days)} days, more than a week")
    return days


def _slots(start, count):
    """Return `count` (start, end) HH:MM ranges from `start`, with one lunch."""
    to_m = lambda s: int(s[:2]) * 60 + int(s[3:])
    fmt = lambda t: f"{t // 60:02d}:{t % 60:02d}"
    out, t, lunched = [], to_m(start), False
    for _ in range(count):
        s, e = t, t + BLOCK_MIN
        out.append((fmt(s), fmt(e)))
        gap = BREAK_MIN
        if not lunched and e >= 12 * 60:
            gap, lunched = LUNCH_MIN, True
        t = e + gap
    return out


def _rows_for(days, offsets, start):
    """Build rows for a set of day offsets that share a start time.

    Returns a list of (section_letter, start, end, {offset: project}).
    """
    if not offsets:
        return []
    count = lambda o, a: sum(1 for act, _ in days[o] if act == a)
    maxg = max(count(o, "g") for o in offsets)
    maxe = max(count(o, "e") for o in offsets)
    maxs = max(count(o, "s") for o in offsets)
    slots = _slots(start, maxg + maxe + maxs)
    per_section = {
        "g": slots[0:maxg],
        "e": slots[maxg:maxg + maxe],
        "s": slots[maxg + maxe:maxg + maxe + maxs],
    }
    cells = {(sec, i): {} for sec in "ges" for i in range(len(per_section[sec]))}
    for o in offsets:
        counters = {"g": 0, "e": 0, "s": 0}
        for act, proj in days[o]:
            i = counters[act]
            counters[act] += 1
            cells[(act, i)][o] = proj
    rows = []
    for sec in "ges":
        for i, (s, e) in enumerate(per_section[sec]):
            rows.append((sec, s, e, cells[(sec, i)]))
    return rows


def build_table(code):
    days = decode(code)
    n = len(days)
    weekday = [o for o in range(n) if o <= 4]
    weekend = [o for o in range(n) if o >= 5]
    rows = _rows_for(days, weekday, WEEKDAY_START) + _rows_for(days, weekend, WEEKEND_START)

    ncol = 1 + n                                   # Time column plus one per day
    cols = DAY_ABBREV[:n]

    projects = []
    for blocks in days:
        for _, p in blocks:
            if p not in projects:
                projects.append(p)

    table = []                                     # ("data", cells) or ("hline",)
    table.append(("data", ["Time <l>"] + cols))
    table.append(("hline",))
    for sec_letter, sec_name in SECTIONS:
        sec_rows = sorted((r for r in rows if r[0] == sec_letter), key=lambda r: r[1])
        if not sec_rows:
            continue
        table.append(("data", [sec_name + ":"] + [""] * n))
        for _, s, e, cellmap in sec_rows:
            table.append(("data", [f"{s}-{e}"] + [cellmap.get(o, "") for o in range(n)]))
    table.append(("hline",))
    for p in projects:
        desc, risk = PROJECTS.get(p, (f"project {p}", "safe"))
        table.append(("data", [f"{p}: {desc} :{risk}:"] + [""] * n))

    widths = [0] * ncol
    for kind, *rest in table:
        if kind == "data":
            for i, c in enumerate(rest[0]):
                widths[i] = max(widths[i], len(c))

    body = []
    for kind, *rest in table:
        if kind == "hline":
            body.append("|" + "+".join("-" * (w + 2) for w in widths) + "|")
        else:
            cells = rest[0]
            body.append("| " + " | ".join(cells[i].ljust(widths[i]) for i in range(ncol)) + " |")

    head = [
        f"#+TITLE: Writing schedule {code}",
        "# Generated by make_tables.py from the file name.",
        f"# Day starts {WEEKDAY_START} on weekdays and {WEEKEND_START} on the weekend.",
        "",
    ]
    return "\n".join(head + body) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate writing-schedule tables from file names.")
    ap.add_argument("names", nargs="+", help="schedule codes or <code>.org file names")
    ap.add_argument("--outdir", default=".", help="directory to write the tables into")
    args = ap.parse_args(argv)

    os.makedirs(args.outdir, exist_ok=True)
    for name in args.names:
        code = os.path.splitext(os.path.basename(name))[0]
        text = build_table(code)
        path = os.path.join(args.outdir, f"{code}.org")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
