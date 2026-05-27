"""Tkinter observability tab: daily line charts for Duo response metrics."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime, timedelta, timezone
from typing import Any

from tuochat.observability import DailyMetricSummary, DailyRollup

CHART_WIDTH = 400
CHART_HEIGHT = 120
CHART_PAD_LEFT = 55
CHART_PAD_RIGHT = 15
CHART_PAD_TOP = 10
CHART_PAD_BOTTOM = 40

COLOR_MEDIAN = "#2563eb"  # blue
COLOR_P95 = "#ea580c"  # orange
COLOR_MAX = "#dc2626"  # red
COLOR_AXIS = "#6b7280"  # gray
COLOR_NO_DATA = "#9ca3af"


def retention_since_iso(days: int = 30) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.isoformat()


def extract_series(
    rollups: list[DailyRollup],
    field: str,
) -> tuple[list[str], list[float], list[float], list[float]]:
    """Return (days, medians, p95s, maxes) for a given metric field."""
    days: list[str] = []
    medians: list[float] = []
    p95s: list[float] = []
    maxes: list[float] = []
    for rollup in rollups:
        summary: DailyMetricSummary | None = getattr(rollup, field, None)
        if summary is None:
            continue
        days.append(rollup.day)
        medians.append(summary.median)
        p95s.append(summary.p95)
        maxes.append(summary.max)
    return days, medians, p95s, maxes


def draw_line_chart(
    canvas: tk.Canvas,
    days: list[str],
    medians: list[float],
    p95s: list[float],
    maxes: list[float],
) -> None:
    canvas.delete("all")
    w = int(canvas["width"])
    h = int(canvas["height"])

    if not days:
        canvas.create_text(
            w // 2,
            h // 2,
            text="No data",
            fill=COLOR_NO_DATA,
            font=("TkDefaultFont", 10),
        )
        return

    plot_left = CHART_PAD_LEFT
    plot_right = w - CHART_PAD_RIGHT
    plot_top = CHART_PAD_TOP
    plot_bottom = h - CHART_PAD_BOTTOM

    plot_w = plot_right - plot_left
    plot_h = plot_bottom - plot_top

    all_values = medians + p95s + maxes
    val_min = min(all_values)
    val_max = max(all_values)
    val_range = val_max - val_min if val_max != val_min else 1.0

    n = len(days)

    def x_for(i: int) -> float:
        if n == 1:
            return plot_left + plot_w / 2
        return plot_left + (i / (n - 1)) * plot_w

    def y_for(v: float) -> float:
        return plot_bottom - ((v - val_min) / val_range) * plot_h

    # Draw axes
    canvas.create_line(plot_left, plot_top, plot_left, plot_bottom, fill=COLOR_AXIS)
    canvas.create_line(plot_left, plot_bottom, plot_right, plot_bottom, fill=COLOR_AXIS)

    # Y-axis labels: min and max
    canvas.create_text(
        plot_left - 4,
        plot_bottom,
        text=format_value(val_min),
        anchor="e",
        fill=COLOR_AXIS,
        font=("TkDefaultFont", 7),
    )
    canvas.create_text(
        plot_left - 4,
        plot_top,
        text=format_value(val_max),
        anchor="e",
        fill=COLOR_AXIS,
        font=("TkDefaultFont", 7),
    )

    # X-axis day labels: every 5th, rotated 45 degrees
    for i, day in enumerate(days):
        if i % 5 == 0 or i == n - 1:
            xpos = x_for(i)
            canvas.create_text(
                xpos,
                plot_bottom + 4,
                text=day[5:],  # MM-DD
                anchor="nw",
                angle=45,
                fill=COLOR_AXIS,
                font=("TkDefaultFont", 7),
            )

    # Draw series lines
    def draw_series(values: list[float], color: str) -> None:
        if len(values) < 2:
            for i, v in enumerate(values):
                xp = x_for(i)
                yp = y_for(v)
                canvas.create_oval(xp - 2, yp - 2, xp + 2, yp + 2, fill=color, outline=color)
            return
        points: list[float] = []
        for i, v in enumerate(values):
            points.append(x_for(i))
            points.append(y_for(v))
        canvas.create_line(*points, fill=color, width=1.5, smooth=False)

    draw_series(maxes, COLOR_MAX)
    draw_series(p95s, COLOR_P95)
    draw_series(medians, COLOR_MEDIAN)


def format_value(v: float) -> str:
    if v >= 10000:
        return f"{v/1000:.1f}k"
    if v >= 1000:
        return f"{v:.0f}"
    if v >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}"


METRIC_CONFIGS: list[tuple[str, str]] = [
    ("request_tokens", "Request tokens"),
    ("response_tokens", "Response tokens"),
    ("time_to_first_token_ms", "Time to first token (ms)"),
    ("time_per_token_ms", "Time per token (ms/token)"),
    ("total_response_ms", "Total response time (ms)"),
]


class ObservabilityTabView:
    def __init__(self, parent: tk.Misc, store: Any) -> None:
        self.parent = parent
        self.store = store
        self.canvases: dict[str, tk.Canvas] = {}
        self.summary_var = tk.StringVar(value="")
        self.build_ui()

    def build_ui(self) -> None:
        outer = tk.Frame(self.parent)
        outer.pack(fill="both", expand=True)

        # Legend bar
        legend = tk.Frame(outer)
        legend.pack(fill="x", padx=8, pady=(6, 0))
        tk.Label(legend, text="Legend:", font=("TkDefaultFont", 9)).pack(side="left")
        for label, color in [("median", COLOR_MEDIAN), ("p95", COLOR_P95), ("max", COLOR_MAX)]:
            dot = tk.Label(legend, text="\u25cf", fg=color, font=("TkDefaultFont", 12))
            dot.pack(side="left", padx=(6, 1))
            tk.Label(legend, text=label, font=("TkDefaultFont", 9)).pack(side="left")

        # Scrollable canvas
        scroll_canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(outer, orient="vertical", command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        scroll_canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(scroll_canvas)
        window_id = scroll_canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_inner_configure(event: tk.Event) -> None:  # type: ignore[type-arg] # pylint: disable=unused-argument
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))

        def on_canvas_configure(event: tk.Event) -> None:  # type: ignore[type-arg] # pylint: disable=unused-argument
            scroll_canvas.itemconfig(window_id, width=event.width)

        inner.bind("<Configure>", on_inner_configure)
        scroll_canvas.bind("<Configure>", on_canvas_configure)

        # Mouse-wheel scrolling
        def on_mousewheel(event: tk.Event) -> None:  # type: ignore[type-arg] # pylint: disable=unused-argument
            scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        scroll_canvas.bind_all("<MouseWheel>", on_mousewheel)

        # Chart sections
        for field, title in METRIC_CONFIGS:
            section = tk.Frame(inner)
            section.pack(fill="x", padx=8, pady=(10, 0))
            tk.Label(
                section,
                text=title,
                font=("TkDefaultFont", 10, "bold"),
                anchor="w",
            ).pack(fill="x")
            chart = tk.Canvas(
                section,
                width=CHART_WIDTH,
                height=CHART_HEIGHT,
                bg="white",
                relief="flat",
                highlightthickness=1,
                highlightbackground="#d1d5db",
            )
            chart.pack(fill="x", expand=True)
            self.canvases[field] = chart

        # Summary block
        summary_frame = tk.LabelFrame(inner, text="Period Summary", padx=8, pady=6)
        summary_frame.pack(fill="x", padx=8, pady=(14, 10))
        tk.Label(
            summary_frame,
            textvariable=self.summary_var,
            justify="left",
            font=("TkFixedFont", 9),
            anchor="w",
        ).pack(fill="x")

        self.inner_frame = inner
        self.scroll_canvas = scroll_canvas

    def refresh(self) -> None:
        since = retention_since_iso(30)
        rollups: list[DailyRollup] = self.store.get_observability_rollups(since_iso=since)

        for field, _ in METRIC_CONFIGS:
            canvas = self.canvases[field]
            days, medians, p95s, maxes = extract_series(rollups, field)
            draw_line_chart(canvas, days, medians, p95s, maxes)

        total_completed = sum(r.completed for r in rollups)
        total_failed = sum(r.failed for r in rollups)
        total_cancelled = sum(r.cancelled for r in rollups)
        summary_text = (
            f"Completed:  {total_completed}\n"
            f"Failed:     {total_failed}\n"
            f"Cancelled:  {total_cancelled}\n"
            f"Retention:  30 days"
        )
        self.summary_var.set(summary_text)


def build_observability_tab(parent: tk.Misc, store: Any) -> ObservabilityTabView:
    view = ObservabilityTabView(parent, store)
    view.refresh()
    return view
