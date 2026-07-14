"""
Chart rendering for the completion-overview report (matplotlib).

Generic by design (spec §6.7): the caller decides what the metric and the grouping
mean. This module only knows "draw one horizontal bar per label, sorted by value,
with the value labelled at the end of each bar". BAS/IAS-specific meaning lives in
the payload, not here.

Style follows the approved sample (spec §6.1):
  - horizontal bars, one per person, sorted by value, highest at the top
  - a single plain blue fill, no red/amber/green banding
  - a light "track" behind each bar showing the full 0..max range
  - the value labelled at the end of each bar (1 dp unless it is a round number)
  - an optional task count on the far right
  - the chart title is the project's actual Zoho name
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")  # headless: no display, render straight to a buffer
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

# Palette — plain blue on a near-white page, per the sample.
_BLUE = "#2f6fed"
_TRACK = "#ececec"
_INK = "#1a1a1a"
_MUTED = "#8a8a8a"
_PAGE = "#fbfbfa"


@dataclass
class Row:
    """One bar: a person (or any grouping value), their average, and task count."""
    label: str
    value: float
    count: int


def _fmt_value(value: float, suffix: str) -> str:
    """Round numbers show as integers (50%), others to one decimal (31.7%)."""
    if abs(value - round(value)) < 0.05:
        return f"{round(value)}{suffix}"
    return f"{value:.1f}{suffix}"


def render_bar_chart(
    rows: list[Row],
    *,
    title: str,
    subtitle: str = "",
    value_suffix: str = "%",
    value_max: float = 100.0,
    count_suffix: str = "tasks",
    show_counts: bool = True,
) -> bytes:
    """Render one grouping's chart for one project and return PNG bytes.

    rows are sorted by value descending (highest at the top) here, so callers do
    not have to pre-sort.
    """
    rows = sorted(rows, key=lambda r: r.value, reverse=True)
    n = len(rows)

    # Height grows with the number of bars; keep a sensible floor for tiny charts.
    fig_h = max(2.2, 0.62 * n + 1.6)
    fig, ax = plt.subplots(figsize=(11, fig_h), dpi=150)
    fig.patch.set_facecolor(_PAGE)
    ax.set_facecolor(_PAGE)

    y = list(range(n))[::-1]  # first row at the top

    # Light full-range track behind every bar.
    ax.barh(y, [value_max] * n, color=_TRACK, height=0.62, zorder=1)
    # Blue value bars.
    ax.barh(y, [r.value for r in rows], color=_BLUE, height=0.62, zorder=2)

    # Value labels just past the end of each blue bar.
    label_gap = value_max * 0.012
    for yi, r in zip(y, rows):
        ax.text(
            r.value + label_gap, yi, _fmt_value(r.value, value_suffix),
            va="center", ha="left", fontsize=12, color=_INK,
            zorder=3,
        )
        if show_counts:
            unit = count_suffix if r.count != 1 else count_suffix.rstrip("s")
            ax.text(
                value_max * 1.02, yi, f"{r.count} {unit}",
                va="center", ha="left", fontsize=10.5, color=_MUTED, zorder=3,
            )

    ax.set_yticks(y)
    ax.set_yticklabels([r.label for r in rows], fontsize=12, color=_INK)
    ax.set_xlim(0, value_max)
    ax.xaxis.set_major_locator(MultipleLocator(value_max / 4))
    ax.xaxis.set_major_formatter(lambda v, _pos: f"{v:g}{value_suffix}")
    ax.tick_params(axis="x", labelsize=11, colors=_MUTED, length=0)
    ax.tick_params(axis="y", length=0)

    # Strip the frame; keep only faint vertical gridlines.
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="#dcdcdc", linewidth=0.8, zorder=0)
    ax.margins(y=0.02)

    # Title + subtitle, left-aligned above the plot.
    fig.suptitle(title, x=0.02, y=0.99, ha="left", fontsize=17, fontweight="bold", color=_INK)
    if subtitle:
        ax.set_title(subtitle, loc="left", fontsize=11, color=_MUTED, pad=14)

    # Leave room on the right for the task-count column.
    fig.subplots_adjust(left=0.20, right=0.90, top=0.86, bottom=0.12)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=_PAGE)
    plt.close(fig)
    return buf.getvalue()
