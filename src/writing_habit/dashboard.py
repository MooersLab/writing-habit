"""Render a self-contained HTML dashboard for one writing week.

This is the twin of the Emacs Lisp ``writing-habit-dashboard.el``.  It has two
panels.  The first redraws the week's planned schedule as a time-by-day grid,
colored by activity.  The second compares planned against actual effort:
per-project meters with adherence, the activity balance, and the barbell split,
plus the summary tiles and the streak.  The output is one HTML file with inline
CSS and no external requests.

The markup is built deterministically from the shared database, and the static
style and script blocks below are the same text the Emacs Lisp module carries,
so the two produce byte-identical files from the same data.  A frozen render
lives at ``tests/fixtures/dashboard.html`` and both ports assert against it.

Colors come from the data-viz reference palette: the three activities take
blue, green, and magenta, and the planned and actual marks take blue and
orange, which sit far apart for colorblind readers.  Values appear as direct
labels in ink, never by color alone, and the schedule is a labeled table.

Public functions:
    :func:`dashboard_html`   return the dashboard HTML as a string
    :func:`write_dashboard`  render and write it to a file
"""

from __future__ import annotations

import math

from .compare import queries

DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Map an activity name to its CSS class.
ACTIVITY_CLASS = {"generative": "gen", "editing": "edit", "support": "sup"}

# The full style block, held verbatim to match the Emacs Lisp twin.
STYLE = """  <style>
    .wh { color-scheme: light;
      --surface: #fcfcfb; --plane: #f9f9f7; --ink: #0b0b0b; --ink2: #52514e;
      --muted: #898781; --grid: #e1e0d9; --axis: #c3c2b7;
      --border: rgba(11,11,11,0.10);
      --gen: #2a78d6; --edit: #008300; --sup: #e87ba4;
      --planned: #2a78d6; --actual: #eb6834; }
    @media (prefers-color-scheme: dark) {
      .wh:not([data-theme="light"]) { color-scheme: dark;
        --surface: #1a1a19; --plane: #0d0d0d; --ink: #ffffff; --ink2: #c3c2b7;
        --muted: #898781; --grid: #2c2c2a; --axis: #383835;
        --border: rgba(255,255,255,0.10);
        --gen: #3987e5; --edit: #008300; --sup: #d55181;
        --planned: #3987e5; --actual: #d95926; } }
    .wh[data-theme="dark"] { color-scheme: dark;
      --surface: #1a1a19; --plane: #0d0d0d; --ink: #ffffff; --ink2: #c3c2b7;
      --muted: #898781; --grid: #2c2c2a; --axis: #383835;
      --border: rgba(255,255,255,0.10);
      --gen: #3987e5; --edit: #008300; --sup: #d55181;
      --planned: #3987e5; --actual: #d95926; }
    * { box-sizing: border-box; }
    body.wh { margin: 0; background: var(--plane); color: var(--ink); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; line-height: 1.45; }
    .wrap { max-width: 960px; margin: 0 auto; padding: 24px 20px 48px; }
    header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    h1 { font-size: 22px; margin: 0; }
    h2 { font-size: 15px; margin: 32px 0 12px; letter-spacing: 0.02em; text-transform: uppercase; color: var(--ink2); }
    .sub { color: var(--ink2); margin: 2px 0 0; }
    .toggle { border: 1px solid var(--border); background: var(--surface); color: var(--ink2); border-radius: 8px; padding: 6px 10px; font: inherit; font-size: 13px; cursor: pointer; }
    .tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 20px; }
    .tile { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
    .tile .v { font-size: 26px; font-weight: 650; }
    .tile .k { color: var(--muted); font-size: 12px; margin-top: 2px; }
    table { border-collapse: collapse; width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; margin-top: 4px; }
    caption { text-align: left; color: var(--muted); font-size: 12px; padding: 0 2px 6px; }
    th, td { padding: 7px 10px; text-align: left; font-size: 13px; border-bottom: 1px solid var(--grid); }
    thead th { color: var(--muted); font-weight: 600; }
    tbody tr:last-child td, tbody tr:last-child th { border-bottom: 0; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .time { color: var(--ink2); font-variant-numeric: tabular-nums; white-space: nowrap; }
    .cell { font-weight: 600; }
    .cell.gen { background: color-mix(in srgb, var(--gen) 15%, transparent); border-left: 3px solid var(--gen); }
    .cell.edit { background: color-mix(in srgb, var(--edit) 15%, transparent); border-left: 3px solid var(--edit); }
    .cell.sup { background: color-mix(in srgb, var(--sup) 15%, transparent); border-left: 3px solid var(--sup); }
    .meter { display: flex; align-items: center; gap: 8px; }
    .track { flex: 1; min-width: 120px; }
    .bar { height: 8px; border-radius: 4px; }
    .bar.planned { background: var(--planned); }
    .bar.actual { background: var(--actual); margin-top: 2px; }
    .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 3px; vertical-align: middle; margin-right: 5px; }
    .legend { display: flex; gap: 16px; color: var(--ink2); font-size: 12px; margin: 8px 2px 0; flex-wrap: wrap; }
    .foot { color: var(--muted); font-size: 11px; margin-top: 28px; }
  </style>"""

# The theme-toggle script, held verbatim to match the Emacs Lisp twin.
SCRIPT = """  <script>
    document.getElementById('wh-theme').addEventListener('click', function () {
      var b = document.body;
      var dark = b.getAttribute('data-theme') === 'dark';
      b.setAttribute('data-theme', dark ? 'light' : 'dark');
      this.textContent = dark ? 'Dark theme' : 'Light theme';
    });
  </script>"""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _esc(text) -> str:
    """Escape the characters that matter inside HTML text and attributes."""
    s = "" if text is None else f"{text}"
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    return s


def _pct(value: int, whole: int) -> int:
    """Return VALUE as a whole-number percent of WHOLE, rounded half up."""
    if whole <= 0:
        return 0
    return int(math.floor(0.5 + (100.0 * value) / whole))


def _fmt2(value) -> str:
    """Format an adherence VALUE, or ``n/a`` when None."""
    return "n/a" if value is None else f"{value:.2f}"


def _ratio(actual: int, planned: int) -> str:
    """Format ACTUAL over PLANNED to two places, or ``n/a`` when PLANNED is zero."""
    return f"{actual / planned:.2f}" if planned and planned > 0 else "n/a"


def _meter(planned: int, actual: int, scale: int) -> str:
    """Return a two-bar meter of PLANNED and ACTUAL, scaled to SCALE."""
    return (
        '<div class="meter"><div class="track">'
        f'<div class="bar planned" style="width:{_pct(planned, scale)}%"></div>'
        f'<div class="bar actual" style="width:{_pct(actual, scale)}%"></div>'
        "</div></div>"
    )


def _schedule_rows(con, week_start):
    """Return the planned blocks for WEEK-START as (offset, start, end, code, activity)."""
    return con.execute(
        "SELECT CAST(julianday(b.day) - julianday(b.week_start) AS INTEGER) AS offset,"
        " b.start_time, b.end_time, p.code, c.name AS activity"
        " FROM plan_block b"
        " JOIN project p ON p.project_id = b.project_id"
        " JOIN category c ON c.category_id = b.category_id"
        " WHERE b.week_start = ?"
        " ORDER BY b.start_time, offset, p.code",
        (week_start,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _tiles(planned_total: int, actual_total: int, streak: int) -> list:
    return [
        '  <section class="tiles">',
        f'    <div class="tile"><div class="v">{planned_total}</div><div class="k">planned minutes</div></div>',
        f'    <div class="tile"><div class="v">{actual_total}</div><div class="k">actual minutes</div></div>',
        f'    <div class="tile"><div class="v">{_ratio(actual_total, planned_total)}</div><div class="k">overall adherence</div></div>',
        f'    <div class="tile"><div class="v">{streak}</div><div class="k">day writing streak</div></div>',
        "  </section>",
    ]


def _schedule(rows) -> list:
    if not rows:
        return ["  <h2>Schedule</h2>", '  <p class="sub">No planned blocks this week.</p>']
    offsets: list = []
    slots: list = []
    cells: dict = {}
    for r in rows:
        off = r[0]
        key = f"{r[1]}-{r[2]}"
        if off not in offsets:
            offsets.append(off)
        if key not in slots:
            slots.append(key)
        ck = (slots.index(key), off)
        if ck not in cells:
            cells[ck] = (r[3], r[4])
    offsets.sort()

    out = ["  <h2>Schedule</h2>", "  <table>",
           "    <caption>Planned blocks, colored by activity.</caption>"]
    head = "    <thead><tr><th>Time</th>"
    for off in offsets:
        label = DAY_LABELS[off] if 0 <= off < 7 else off
        head += f"<th>{_esc(label)}</th>"
    out.append(head + "</tr></thead>")
    out.append("    <tbody>")
    for idx, key in enumerate(slots):
        rowstr = f'      <tr><th class="time">{_esc(key)}</th>'
        for off in offsets:
            cell = cells.get((idx, off))
            if cell:
                cls = ACTIVITY_CLASS.get(cell[1], "gen")
                rowstr += f'<td class="cell {cls}">{_esc(cell[0])}</td>'
            else:
                rowstr += "<td></td>"
        out.append(rowstr + "</tr>")
    out.append("    </tbody>")
    out.append("  </table>")
    out.append(
        '  <div class="legend">'
        '<span><span class="swatch" style="background:var(--gen)"></span>generative</span>'
        '<span><span class="swatch" style="background:var(--edit)"></span>editing</span>'
        '<span><span class="swatch" style="background:var(--sup)"></span>support</span>'
        "</div>"
    )
    return out


def _projects(proj) -> list:
    if not proj:
        return []
    scale = 0
    for r in proj:
        scale = max(scale, r["planned_min"], r["actual_min"])
    out = ["  <h2>Planned vs actual by project</h2>", "  <table>",
           '    <thead><tr><th>Code</th><th>Project</th>'
           '<th class="num">Planned</th><th class="num">Actual</th>'
           '<th>Progress</th><th class="num">Adherence</th></tr></thead>',
           "    <tbody>"]
    for r in proj:
        out.append(
            '      <tr><td class="cell">'
            f'{_esc(r["code"])}</td><td>'
            f'{_esc(r["description"] or "")}'
            f'</td><td class="num">{r["planned_min"]}'
            f'</td><td class="num">{r["actual_min"]}'
            f'</td><td>{_meter(r["planned_min"], r["actual_min"], scale)}'
            f'</td><td class="num">{_fmt2(r["adherence"])}'
            "</td></tr>"
        )
    out.append("    </tbody>")
    out.append("  </table>")
    out.append(
        '  <div class="legend">'
        '<span><span class="swatch" style="background:var(--planned)"></span>planned</span>'
        '<span><span class="swatch" style="background:var(--actual)"></span>actual</span>'
        "</div>"
    )
    return out


def _activities(cat) -> list:
    if not cat:
        return []
    scale = 0
    for r in cat:
        scale = max(scale, r["planned_min"], r["actual_min"])
    out = ["  <h2>Activity balance</h2>", "  <table>",
           '    <thead><tr><th>Activity</th>'
           '<th class="num">Planned</th><th class="num">Actual</th>'
           '<th>Progress</th></tr></thead>',
           "    <tbody>"]
    for r in cat:
        out.append(
            f'      <tr><td>{_esc(r["category"])}'
            f'</td><td class="num">{r["planned_min"]}'
            f'</td><td class="num">{r["actual_min"]}'
            f'</td><td>{_meter(r["planned_min"], r["actual_min"], scale)}'
            "</td></tr>"
        )
    out.append("    </tbody>")
    out.append("  </table>")
    return out


def _sum_for(rows, risk_class: str, field: str) -> int:
    return sum(r[field] for r in rows if r["risk_class"] == risk_class)


def _barbell(bar) -> list:
    if not bar:
        return []
    p_plan = _sum_for(bar, "safe", "planned_min") + _sum_for(bar, "speculative", "planned_min")
    p_act = _sum_for(bar, "safe", "actual_min") + _sum_for(bar, "speculative", "actual_min")
    spec_plan = _sum_for(bar, "speculative", "planned_min")
    spec_act = _sum_for(bar, "speculative", "actual_min")
    out = ["  <h2>Barbell split</h2>", "  <table>",
           '    <thead><tr><th>Risk class</th>'
           '<th class="num">Planned</th><th class="num">Actual</th></tr></thead>',
           "    <tbody>"]
    for r in bar:
        out.append(
            f'      <tr><td>{_esc(r["risk_class"] or "untagged")}'
            f'</td><td class="num">{r["planned_min"]}'
            f'</td><td class="num">{r["actual_min"]}'
            "</td></tr>"
        )
    out.append("    </tbody>")
    out.append("  </table>")
    out.append(
        f'  <p class="sub">Speculative share: planned {_pct(spec_plan, p_plan)}%,'
        f' actual {_pct(spec_act, p_act)}%.</p>'
    )
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def dashboard_html(con, week: str) -> str:
    """Return a self-contained HTML dashboard string for the week containing WEEK."""
    week_start = queries._monday(week)
    proj = queries.week_project(con, week)
    cat = queries.week_category(con, week)
    bar = queries.week_barbell(con, week)
    streak = queries.current_streak(con)
    planned_total = sum(r["planned_min"] for r in proj)
    actual_total = sum(r["actual_min"] for r in proj)

    lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        f"  <title>Writing dashboard, week of {_esc(week_start)}</title>",
        STYLE,
        "</head>",
        '<body class="wh">',
        '  <div class="wrap">',
        "  <header>",
        f'    <div><h1>Writing dashboard</h1><p class="sub">Week of {_esc(week_start)}</p></div>',
        '    <button id="wh-theme" class="toggle" type="button">Dark theme</button>',
        "  </header>",
    ]
    lines += _tiles(planned_total, actual_total, streak)
    lines += _schedule(_schedule_rows(con, week_start))
    lines += _projects(proj)
    lines += _activities(cat)
    lines += _barbell(bar)
    lines += [
        '  <p class="foot">Generated by writing-habit from the shared SQLite'
        " database. Planned versus actual, self-reported effort.</p>",
        "  </div>",
        SCRIPT,
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(lines)


def write_dashboard(con, week: str, out_path: str) -> str:
    """Render the dashboard for WEEK, write it to OUT-PATH, and return OUT-PATH."""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(dashboard_html(con, week))
    return out_path
