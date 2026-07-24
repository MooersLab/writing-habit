"""Cross-week adherence tracker: a text series and five weekly plots.

This is build step 1 of the adherence-extension plan. It reads the cross-week
views through :mod:`writing_habit.compare.queries` and renders them two ways.

``render_text`` prints one row per week with the two headline adherence series,
the overall ratio of summed minutes and the mean of the per-project ratios, and
the mean per-project adherence within each activity.

``write_plots`` draws five plots that share the week axis: the two headline
series side by side, then one plot per activity, generative, editing, and
support. Plotting needs the optional matplotlib dependency.
"""

from __future__ import annotations

from . import queries

CATEGORIES = ["generative", "editing", "support"]

# Activity colors from the dashboard palette, so the plots and the dashboard
# read as one system. The two headline series use neutral ink.
_CATEGORY_COLOR = {"generative": "#2a78d6", "editing": "#008300", "support": "#e87ba4"}
_OVERALL_COLOR = "#0b0b0b"
_MEAN_COLOR = "#52514e"
_REF_COLOR = "#898781"


def _by_week(rows, value_key: str) -> dict:
    return {r["week_start"]: r[value_key] for r in rows}


def collect(con, start=None, end=None):
    """Return (weeks, series) for the range.

    ``weeks`` is the sorted list of week-start dates. ``series`` maps a label to
    a dict of week -> adherence value, where a missing week maps to nothing.
    """
    overall = queries.overall_series(con, start, end)
    projmean = queries.project_mean_series(con, start, end)
    cats = {c: queries.category_mean_series(con, c, start, end) for c in CATEGORIES}

    weeks = sorted(
        {r["week_start"] for r in overall}
        | {r["week_start"] for r in projmean}
        | {r["week_start"] for c in CATEGORIES for r in cats[c]}
    )

    series = {
        "overall": _by_week(overall, "adherence"),
        "project_mean": _by_week(projmean, "mean_adherence"),
    }
    for c in CATEGORIES:
        series[c] = _by_week(cats[c], "mean_adherence")
    return weeks, series


def _fmt(value) -> str:
    return "  -  " if value is None else f"{value:.2f}"


def render_text(con, start=None, end=None) -> str:
    """Return a plain-text table of the weekly adherence series."""
    weeks, series = collect(con, start, end)
    lines = ["Weekly adherence history", "=" * 72]
    if not weeks:
        lines.append("No weeks in range.")
        return "\n".join(lines)
    lines.append(
        f"{'week':<12} {'overall':>8} {'proj-mean':>10} "
        f"{'gen':>7} {'edit':>7} {'support':>8}"
    )
    lines.append("-" * 72)
    for w in weeks:
        lines.append(
            f"{w:<12} {_fmt(series['overall'].get(w)):>8} "
            f"{_fmt(series['project_mean'].get(w)):>10} "
            f"{_fmt(series['generative'].get(w)):>7} "
            f"{_fmt(series['editing'].get(w)):>7} "
            f"{_fmt(series['support'].get(w)):>8}"
        )
    lines.append("")
    lines.append(
        "overall is summed actual over summed planned. The other columns are the "
        "mean of the per-project adherence ratios. A value of 1.00 is on plan."
    )
    return "\n".join(lines)


def write_plots(con, out_path: str, start=None, end=None) -> str:
    """Write the five weekly adherence plots to OUT-PATH. Needs matplotlib."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on extra
        raise SystemExit(
            "Plotting needs the optional dependency. Run: pip install 'writing-habit[plot]'"
        ) from exc

    weeks, series = collect(con, start, end)
    if not weeks:
        raise SystemExit("No weeks in range to plot.")

    x = list(range(len(weeks)))
    labels = [w[5:] for w in weeks]  # MM-DD

    fig = plt.figure(figsize=(12, 7))
    gs = GridSpec(2, 6, figure=fig, hspace=0.55, wspace=0.7)
    panels = [
        (fig.add_subplot(gs[0, 0:3]), "Overall adherence (summed minutes)",
         series["overall"], _OVERALL_COLOR),
        (fig.add_subplot(gs[0, 3:6]), "Mean of per-project adherence",
         series["project_mean"], _MEAN_COLOR),
        (fig.add_subplot(gs[1, 0:2]), "Generative (mean per project)",
         series["generative"], _CATEGORY_COLOR["generative"]),
        (fig.add_subplot(gs[1, 2:4]), "Editing (mean per project)",
         series["editing"], _CATEGORY_COLOR["editing"]),
        (fig.add_subplot(gs[1, 4:6]), "Support (mean per project)",
         series["support"], _CATEGORY_COLOR["support"]),
    ]

    ymax = 1.2
    for _ax, _title, data, _color in panels:
        for value in data.values():
            if value is not None:
                ymax = max(ymax, value)

    for ax, title, data, color in panels:
        ys = [data.get(w) for w in weeks]
        xs_plot = [i for i, y in zip(x, ys) if y is not None]
        ys_plot = [y for y in ys if y is not None]
        ax.axhline(1.0, color=_REF_COLOR, linewidth=1.0, linestyle="--", zorder=1)
        ax.plot(xs_plot, ys_plot, marker="o", color=color, linewidth=1.8, zorder=2)
        ax.set_title(title, fontsize=10)
        ax.set_ylim(0, ymax * 1.05)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
        ax.set_ylabel("adherence", fontsize=8)
        ax.grid(True, axis="y", color="#e1e0d9", linewidth=0.6)

    fig.suptitle("Weekly adherence history", fontsize=13)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_path
