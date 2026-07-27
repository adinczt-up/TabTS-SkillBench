from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from common import (
    CONDITION_LABELS,
    CONDITIONS,
    DEFAULT_OUTPUT_ROOT,
    gain_correlations,
    load_main_results,
)
from svg import (
    COLORS,
    circle,
    interpolate_color,
    line,
    rect,
    text,
    write,
)


def short_label(row: dict) -> str:
    harness = {
        "Codex": "Codex",
        "Claude Code": "Claude",
        "Nanobot": "Nanobot",
    }[row["harness"]]
    return f"{harness} {row['model']}"


def figure4(path: Path, data: dict) -> None:
    width, height = 1240, 650
    left, right, top, bottom = 75, 70, 85, 150
    chart_width = width - left - right
    chart_height = height - top - bottom
    y_max = 75.0
    gain_max = 35.0
    body = [
        text(left, 34, "Avg@3 across nine configurations", css="title"),
        text(
            left,
            57,
            "Bars: Skill condition; line: Self-Route gain vs. Baseline",
            css="subtitle",
        ),
    ]
    for tick in range(0, 76, 15):
        y = top + chart_height * (1 - tick / y_max)
        body.extend(
            [
                line(left, y, width - right, y, stroke=COLORS["grid"]),
                text(left - 10, y + 4, tick, css="axis", anchor="end"),
            ]
        )
    group_width = chart_width / len(data["rows"])
    bar_width = min(26.0, group_width / 4.2)
    gain_points: list[tuple[float, float]] = []
    for index, row in enumerate(data["rows"]):
        center = left + group_width * (index + 0.5)
        for offset, condition in enumerate(CONDITIONS):
            value = round(row["outcome"]["avg_at_3"][condition], 1)
            x = center + (offset - 1) * (bar_width + 3) - bar_width / 2
            bar_height = chart_height * value / y_max
            body.append(
                rect(
                    x,
                    top + chart_height - bar_height,
                    bar_width,
                    bar_height,
                    fill=COLORS[condition],
                    radius=2,
                )
            )
        gain = round(row["outcome"]["avg_at_3"]["self_route"], 1) - round(
            row["outcome"]["avg_at_3"]["baseline"], 1
        )
        gain_y = top + chart_height * (1 - gain / gain_max)
        gain_points.append((center, gain_y))
        body.append(
            text(
                center,
                top + chart_height + 18,
                short_label(row),
                css="small",
                anchor="end",
                rotate=-45,
            )
        )
    body.append(
        '<polyline points="'
        + " ".join(f"{x:.2f},{y:.2f}" for x, y in gain_points)
        + '" fill="none" stroke="#17212B" stroke-width="2"/>'
    )
    for (x, y), row in zip(gain_points, data["rows"], strict=True):
        gain = round(row["outcome"]["avg_at_3"]["self_route"], 1) - round(
            row["outcome"]["avg_at_3"]["baseline"], 1
        )
        body.extend(
            [
                circle(x, y, 4, fill="white"),
                text(x, y - 8, f"+{gain:.1f}", css="small", anchor="middle"),
            ]
        )
    for index, condition in enumerate(CONDITIONS):
        x = left + 210 * index
        body.extend(
            [
                rect(
                    x,
                    height - 30,
                    14,
                    14,
                    fill=COLORS[condition],
                    radius=2,
                ),
                text(
                    x + 20,
                    height - 18,
                    CONDITION_LABELS[condition],
                    css="axis",
                ),
            ]
        )
    body.extend(
        [
            text(20, top + chart_height / 2, "Avg@3 (%)", css="axis", rotate=-90),
            text(
                width - 15,
                top + chart_height / 2,
                "Self-Route gain (pp)",
                css="axis",
                anchor="middle",
                rotate=90,
            ),
        ]
    )
    write(path, width, height, body)


def figure5(path: Path, data: dict) -> None:
    width, height = 1420, 650
    left, top = 185, 105
    cell_width, cell_height = 78, 45
    metrics = (
        ("outcome", "avg_at_3", "Avg@3"),
        ("temporal_analysis", "tea", "TEA"),
        ("temporal_analysis", "td_f1", "TD-F1"),
        ("temporal_analysis", "tcc", "TCC"),
        ("multi_table", "rea", "REA"),
        ("multi_table", "dar", "DAR"),
    )
    panels = (
        ("self_route", "Self-Route minus Baseline"),
        ("annotated_preload", "Annotated-Skill Preload minus Baseline"),
    )
    body = [
        text(left, 34, "Per-configuration metric changes", css="title"),
        text(
            left,
            57,
            "Percentage-point differences relative to Baseline",
            css="subtitle",
        ),
    ]
    panel_width = cell_width * len(metrics)
    for panel_index, (condition, panel_label) in enumerate(panels):
        panel_x = left + panel_index * (panel_width + 95)
        body.append(
            text(
                panel_x + panel_width / 2,
                83,
                panel_label,
                css="label",
                anchor="middle",
            )
        )
        for column, (_, _, label) in enumerate(metrics):
            body.append(
                text(
                    panel_x + column * cell_width + cell_width / 2,
                    top - 10,
                    label,
                    css="axis",
                    anchor="middle",
                )
            )
        for row_index, row in enumerate(data["rows"]):
            y = top + row_index * cell_height
            if panel_index == 0:
                body.append(
                    text(
                        left - 10,
                        y + cell_height / 2 + 4,
                        short_label(row),
                        css="axis",
                        anchor="end",
                    )
                )
            for column, (group, metric, _) in enumerate(metrics):
                value = round(row[group][metric][condition], 1) - round(
                    row[group][metric]["baseline"], 1
                )
                x = panel_x + column * cell_width
                body.extend(
                    [
                        rect(
                            x,
                            y,
                            cell_width,
                            cell_height,
                            fill=interpolate_color(value),
                            stroke="white",
                        ),
                        text(
                            x + cell_width / 2,
                            y + cell_height / 2 + 4,
                            f"{value:+.1f}",
                            css="small",
                            anchor="middle",
                        ),
                    ]
                )
    legend_x = width - 85
    for index, value in enumerate(range(40, -41, -10)):
        y = top + index * 34
        body.extend(
            [
                rect(
                    legend_x,
                    y,
                    18,
                    34,
                    fill=interpolate_color(value),
                ),
                text(legend_x + 24, y + 21, f"{value:+d}", css="small"),
            ]
        )
    body.append(
        text(
            legend_x + 8,
            top + 330,
            "pp",
            css="axis",
            anchor="middle",
        )
    )
    write(path, width, height, body)


def figure7(path: Path, data: dict) -> None:
    width, height = 820, 590
    left, right, top, bottom = 80, 80, 85, 90
    chart_width = width - left - right
    chart_height = height - top - bottom
    calls_max = 40.0
    accuracy_min, accuracy_max = 30.0, 70.0
    displayed_calls = {
        condition: statistics.mean(
            round(row["cost"]["calls"][condition], 2) for row in data["rows"]
        )
        for condition in CONDITIONS
    }
    displayed_avg = {
        condition: statistics.mean(
            round(row["outcome"]["avg_at_3"][condition], 1) for row in data["rows"]
        )
        for condition in CONDITIONS
    }
    body = [
        text(left, 34, "Accuracy-cost trade-off", css="title"),
        text(
            left,
            57,
            "Bars: macro-average tool calls; line: macro-average Avg@3",
            css="subtitle",
        ),
    ]
    for tick in range(0, 41, 10):
        y = top + chart_height * (1 - tick / calls_max)
        body.extend(
            [
                line(left, y, width - right, y, stroke=COLORS["grid"]),
                text(left - 10, y + 4, tick, css="axis", anchor="end"),
            ]
        )
    positions = [left + chart_width * (index + 0.5) / 3 for index in range(3)]
    points: list[tuple[float, float]] = []
    for x, condition in zip(positions, CONDITIONS, strict=True):
        calls = displayed_calls[condition]
        avg = displayed_avg[condition]
        bar_height = chart_height * calls / calls_max
        body.extend(
            [
                rect(
                    x - 45,
                    top + chart_height - bar_height,
                    90,
                    bar_height,
                    fill=COLORS[condition],
                    radius=3,
                ),
                text(
                    x,
                    top + chart_height - bar_height + 20,
                    f"{calls:.1f}",
                    css="label",
                    anchor="middle",
                    fill="white",
                ),
                text(
                    x,
                    top + chart_height + 28,
                    CONDITION_LABELS[condition],
                    css="axis",
                    anchor="middle",
                ),
            ]
        )
        avg_y = top + chart_height * (1 - (avg - accuracy_min) / (accuracy_max - accuracy_min))
        points.append((x, avg_y))
    body.append(
        '<polyline points="'
        + " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        + '" fill="none" stroke="#17212B" stroke-width="2.5"/>'
    )
    for (x, y), condition in zip(points, CONDITIONS, strict=True):
        value = displayed_avg[condition]
        body.extend(
            [
                circle(x, y, 5, fill="white"),
                text(x, y - 12, f"{value:.1f}", css="label", anchor="middle"),
            ]
        )
    body.extend(
        [
            text(20, top + chart_height / 2, "Avg. tool calls", css="axis", rotate=-90),
            text(
                width - 14,
                top + chart_height / 2,
                "Avg@3 (%)",
                css="axis",
                anchor="middle",
                rotate=90,
            ),
        ]
    )
    write(path, width, height, body)


def _linear_fit(x_values: list[float], y_values: list[float]) -> tuple[float, float]:
    x_mean = statistics.mean(x_values)
    y_mean = statistics.mean(y_values)
    slope = sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x_values, y_values, strict=True)
    ) / sum((value - x_mean) ** 2 for value in x_values)
    return slope, y_mean - slope * x_mean


def _marker(
    harness: str,
    x: float,
    y: float,
    *,
    color: str,
    filled: bool,
) -> str:
    fill = color if filled else "white"
    if harness == "Codex":
        return circle(x, y, 5, fill=fill, stroke=color)
    if harness == "Claude Code":
        return rect(x - 5, y - 5, 10, 10, fill=fill, stroke=color, radius=0)
    points = f"{x:.2f},{y - 6:.2f} {x - 6:.2f},{y + 5:.2f} {x + 6:.2f},{y + 5:.2f}"
    return f'<polygon points="{points}" fill="{fill}" stroke="{color}" stroke-width="1.2"/>'


def figure8(path: Path, data: dict) -> None:
    width, height = 850, 620
    left, right, top, bottom = 80, 45, 90, 90
    chart_width = width - left - right
    chart_height = height - top - bottom
    x_min, x_max = 20.0, 65.0
    y_min, y_max = 0.0, 35.0
    model_colors = {
        "GPT-5.4": "#D04E4E",
        "GPT-5.6": "#E58B35",
        "DS-V4-F": "#3A78B8",
        "DS-V4-P": "#4E9A65",
    }
    correlations = gain_correlations(data)
    r_value = correlations["self_route"]["r"]
    p_value = correlations["self_route"]["p"]
    body = [
        text(left, 34, "Skill gain versus Baseline performance", css="title"),
        text(
            left,
            57,
            f"Pearson r = {r_value:.2f}, p = {p_value:.3f}",
            css="subtitle",
        ),
    ]
    for tick in range(20, 66, 10):
        x = left + chart_width * (tick - x_min) / (x_max - x_min)
        body.extend(
            [
                line(x, top, x, top + chart_height, stroke=COLORS["grid"]),
                text(x, top + chart_height + 22, tick, css="axis", anchor="middle"),
            ]
        )
    for tick in range(0, 36, 5):
        y = top + chart_height * (1 - (tick - y_min) / (y_max - y_min))
        body.extend(
            [
                line(left, y, left + chart_width, y, stroke=COLORS["grid"]),
                text(left - 10, y + 4, tick, css="axis", anchor="end"),
            ]
        )
    for condition, stroke in (
        ("self_route", COLORS["self_route"]),
        ("annotated_preload", COLORS["annotated_preload"]),
    ):
        x_values = [round(row["outcome"]["avg_at_3"]["baseline"], 1) for row in data["rows"]]
        y_values = [
            round(row["outcome"]["delta_percentage_points"][condition], 1) for row in data["rows"]
        ]
        slope, intercept = _linear_fit(x_values, y_values)
        endpoints = [
            (x_min, slope * x_min + intercept),
            (x_max, slope * x_max + intercept),
        ]
        mapped = [
            (
                left + chart_width * (x - x_min) / (x_max - x_min),
                top + chart_height * (1 - (y - y_min) / (y_max - y_min)),
            )
            for x, y in endpoints
        ]
        body.append(
            line(
                mapped[0][0],
                mapped[0][1],
                mapped[1][0],
                mapped[1][1],
                stroke=stroke,
                width=2,
                dash="7 5" if condition == "annotated_preload" else None,
            )
        )
        for row, x_value, y_value in zip(data["rows"], x_values, y_values, strict=True):
            x = left + chart_width * (x_value - x_min) / (x_max - x_min)
            y = top + chart_height * (1 - (y_value - y_min) / (y_max - y_min))
            body.append(
                _marker(
                    row["harness"],
                    x,
                    y,
                    color=model_colors[row["model"]],
                    filled=condition == "self_route",
                )
            )
    body.extend(
        [
            text(
                left + chart_width / 2,
                height - 28,
                "Baseline Avg@3 (%)",
                css="axis",
                anchor="middle",
            ),
            text(
                22,
                top + chart_height / 2,
                "Skill gain in Avg@3 (pp)",
                css="axis",
                anchor="middle",
                rotate=-90,
            ),
        ]
    )
    legend_x = left + chart_width - 180
    body.extend(
        [
            line(
                legend_x,
                top + 16,
                legend_x + 34,
                top + 16,
                stroke=COLORS["self_route"],
                width=2,
            ),
            text(
                legend_x + 42,
                top + 20,
                "Self-Route (filled)",
                css="axis",
            ),
            line(
                legend_x,
                top + 38,
                legend_x + 34,
                top + 38,
                stroke=COLORS["annotated_preload"],
                width=2,
                dash="7 5",
            ),
            text(
                legend_x + 42,
                top + 42,
                "Preload (open)",
                css="axis",
            ),
        ]
    )
    model_legend_x = legend_x
    model_legend_y = top + 70
    body.append(text(model_legend_x, model_legend_y, "Model", css="axis"))
    for index, model in enumerate(("GPT-5.4", "GPT-5.6", "DS-V4-F", "DS-V4-P")):
        y = model_legend_y + 20 + 19 * index
        body.extend(
            [
                circle(
                    model_legend_x + 5,
                    y - 4,
                    4,
                    fill=model_colors[model],
                    stroke=model_colors[model],
                ),
                text(model_legend_x + 16, y, model, css="small"),
            ]
        )
    harness_legend_x = legend_x + 92
    body.append(text(harness_legend_x, model_legend_y, "Harness", css="axis"))
    for index, harness in enumerate(("Codex", "Claude Code", "Nanobot")):
        y = model_legend_y + 20 + 22 * index
        body.extend(
            [
                _marker(
                    harness,
                    harness_legend_x + 5,
                    y - 4,
                    color=COLORS["muted"],
                    filled=False,
                ),
                text(harness_legend_x + 16, y, harness, css="small"),
            ]
        )
    write(path, width, height, body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce paper Figures 4, 5, 7, and 8")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    data = load_main_results()
    figure4(args.output_dir / "figure4.svg", data)
    figure5(args.output_dir / "figure5.svg", data)
    figure7(args.output_dir / "figure7.svg", data)
    figure8(args.output_dir / "figure8.svg", data)
    print(f"wrote Figures 4, 5, 7, and 8 to {args.output_dir}")


if __name__ == "__main__":
    main()
