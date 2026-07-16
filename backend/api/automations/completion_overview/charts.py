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


@dataclass
class Panel:
    """One grouping's section within a combined chart (e.g. 'By partner')."""
    heading: str
    rows: list[Row]


def _fmt_value(value: float, suffix: str) -> str:
    """Round numbers show as integers (50%), others to one decimal (31.7%)."""
    if abs(value - round(value)) < 0.05:
        return f"{round(value)}{suffix}"
    return f"{value:.1f}{suffix}"


def _draw_panel(ax, panel: Panel, *, value_suffix: str, value_max: float,
                count_suffix: str, show_counts: bool) -> None:
    """Draw one grouping's bars onto a given axes (shared by single & combined)."""
    rows = sorted(panel.rows, key=lambda r: r.value, reverse=True)
    n = len(rows)
    y = list(range(n))[::-1]

    ax.set_facecolor(_PAGE)
    ax.barh(y, [value_max] * n, color=_TRACK, height=0.62, zorder=1)
    ax.barh(y, [r.value for r in rows], color=_BLUE, height=0.62, zorder=2)

    gap = value_max * 0.012
    for yi, r in zip(y, rows):
        ax.text(r.value + gap, yi, _fmt_value(r.value, value_suffix),
                va="center", ha="left", fontsize=12, color=_INK, zorder=3)
        if show_counts:
            unit = count_suffix if r.count != 1 else count_suffix.rstrip("s")
            ax.text(value_max * 1.02, yi, f"{r.count} {unit}",
                    va="center", ha="left", fontsize=10.5, color=_MUTED, zorder=3)

    ax.set_yticks(y)
    ax.set_yticklabels([r.label for r in rows], fontsize=12, color=_INK)
    ax.set_xlim(0, value_max)
    ax.set_ylim(-0.7, max(n - 0.3, 0.7))
    ax.xaxis.set_major_locator(MultipleLocator(value_max / 4))
    ax.xaxis.set_major_formatter(lambda v, _pos: f"{v:g}{value_suffix}")
    ax.tick_params(axis="x", labelsize=11, colors=_MUTED, length=0)
    ax.tick_params(axis="y", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="#dcdcdc", linewidth=0.8, zorder=0)
    ax.set_title(panel.heading, loc="left", fontsize=13, fontweight="bold",
                 color=_INK, pad=12)


def render_combined_chart(
    panels: list[Panel],
    *,
    title: str,
    subtitle: str = "",
    value_suffix: str = "%",
    value_max: float = 100.0,
    count_suffix: str = "tasks",
    show_counts: bool = True,
) -> bytes:
    """Render every grouping into a single PNG, one stacked panel per grouping.

    Panels are sized proportionally to their bar count so bars stay the same
    height whether a panel has three people or twelve.
    """
    panels = [p for p in panels if p.rows]
    if not panels:
        panels = [Panel(heading="No data", rows=[])]

    # Size each panel by its bar count (+ a constant allowance for its heading and
    # x-axis) so bars stay a consistent height across panels of different sizes.
    counts = [max(len(p.rows), 1) for p in panels]
    chrome_rows = 2.0          # heading + axis labels, expressed in "rows"
    row_in = 0.46              # inches per row
    # header_in must clear the title, the subtitle, AND the first panel's heading,
    # which renders above its axes.
    header_in, footer_in = 1.6, 0.35

    weights = [c + chrome_rows for c in counts]
    fig_h = sum(weights) * row_in + header_in + footer_in

    fig = plt.figure(figsize=(11, fig_h), dpi=150)
    fig.patch.set_facecolor(_PAGE)
    gs = fig.add_gridspec(len(panels), 1, height_ratios=weights)

    for i, panel in enumerate(panels):
        ax = fig.add_subplot(gs[i, 0])
        _draw_panel(ax, panel, value_suffix=value_suffix, value_max=value_max,
                    count_suffix=count_suffix, show_counts=show_counts)

    # Header/footer are fixed in inches, so they don't scale with panel count.
    fig.text(0.02, 1 - 0.34 / fig_h, title, ha="left", va="top",
             fontsize=18, fontweight="bold", color=_INK)
    if subtitle:
        fig.text(0.02, 1 - 0.72 / fig_h, subtitle, ha="left", va="top",
                 fontsize=11, color=_MUTED)

    fig.subplots_adjust(
        left=0.20, right=0.90,
        top=1 - header_in / fig_h, bottom=footer_in / fig_h,
        hspace=0.9 * chrome_rows * row_in / (sum(weights) * row_in / len(panels)),
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=_PAGE)
    plt.close(fig)
    return buf.getvalue()
