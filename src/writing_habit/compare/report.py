"""Render a plain-text comparison report, and optionally one plot."""

from __future__ import annotations

from . import queries


def _bar(planned: int, actual: int, width: int = 20) -> str:
    """A tiny text meter of actual against planned."""
    if planned <= 0:
        return ""
    filled = min(width, round(width * actual / planned))
    return "#" * filled + "-" * (width - filled)


def render_week(con, week: str) -> str:
    lines: list[str] = []
    proj = queries.week_project(con, week)
    if proj:
        week_start = proj[0]["week_start"]
    else:
        week_start = week
    lines.append(f"Writing week beginning {week_start}")
    lines.append("=" * 52)

    planned_total = sum(r["planned_min"] for r in proj)
    actual_total = sum(r["actual_min"] for r in proj)
    lines.append(
        f"Planned {planned_total} min, actual {actual_total} min, "
        f"overall adherence {_ratio(actual_total, planned_total)}"
    )

    lines.append("")
    lines.append("By project (planned -> actual, adherence)")
    lines.append("-" * 52)
    for r in proj:
        lines.append(
            f"  {r['code']:<4} {str(r['description'] or ''):<22.22} "
            f"{r['planned_min']:>4} -> {r['actual_min']:>4}  "
            f"{_fmt(r['adherence']):>5}  {_bar(r['planned_min'], r['actual_min'])}"
        )

    cat = queries.week_category(con, week)
    if cat:
        lines.append("")
        lines.append("By activity (Rule 2 balance)")
        lines.append("-" * 52)
        for r in cat:
            lines.append(
                f"  {r['category']:<11} {r['planned_min']:>4} -> {r['actual_min']:>4}  "
                f"{_bar(r['planned_min'], r['actual_min'])}"
            )

    bar = queries.week_barbell(con, week)
    if bar:
        lines.append("")
        lines.append("By barbell class (Rule 6 drift)")
        lines.append("-" * 52)
        p_plan = _sum_for(bar, "safe", "planned_min") + _sum_for(bar, "speculative", "planned_min")
        p_act = _sum_for(bar, "safe", "actual_min") + _sum_for(bar, "speculative", "actual_min")
        for r in bar:
            lines.append(
                f"  {str(r['risk_class'] or 'untagged'):<12} "
                f"{r['planned_min']:>4} -> {r['actual_min']:>4}"
            )
        spec_plan = _sum_for(bar, "speculative", "planned_min")
        spec_act = _sum_for(bar, "speculative", "actual_min")
        lines.append(
            f"  speculative share  planned {_pct(spec_plan, p_plan)}  "
            f"actual {_pct(spec_act, p_act)}"
        )

    streak = queries.current_streak(con)
    lines.append("")
    lines.append(f"Current streak of consecutive writing days: {streak}")
    return "\n".join(lines)


def write_plot(con, week: str, out_path: str) -> str:
    """Write a planned-versus-actual bar chart. Needs the optional plot extra."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on extra
        raise SystemExit(
            "Plotting needs the optional dependency. Run: pip install 'writing-habit[plot]'"
        ) from exc

    proj = queries.week_project(con, week)
    codes = [r["code"] for r in proj]
    planned = [r["planned_min"] for r in proj]
    actual = [r["actual_min"] for r in proj]
    x = range(len(codes))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar([i - 0.2 for i in x], planned, width=0.4, label="planned")
    ax.bar([i + 0.2 for i in x], actual, width=0.4, label="actual")
    ax.set_xticks(list(x))
    ax.set_xticklabels(codes)
    ax.set_ylabel("minutes")
    ax.set_title(f"Planned vs actual, week of {week}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def _ratio(actual: int, planned: int) -> str:
    return _fmt(round(actual / planned, 2)) if planned else "n/a"


def _fmt(value) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "n/a"


def _sum_for(rows, risk_class: str, field: str) -> int:
    return sum(r[field] for r in rows if r["risk_class"] == risk_class)
