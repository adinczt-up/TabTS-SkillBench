from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from common import (
    CONDITIONS,
    DEFAULT_OUTPUT_ROOT,
    METRICS,
    latex_escape,
    load_main_results,
    write_csv,
)


def triplet(values: list[float | None], digits: int = 1) -> str:
    return "/".join("—" if value is None else f"{value:.{digits}f}" for value in values)


def build_rows() -> list[dict[str, str]]:
    data = load_main_results()
    output: list[dict[str, str]] = []
    displayed: list[dict[str, dict[str, float | None]]] = []
    for row in data["rows"]:
        display_row: dict[str, dict[str, float | None]] = {}
        values: dict[str, str] = {}
        for group, metric, label in METRICS:
            digits = 2 if metric == "calls" else 1
            display_row[metric] = {
                condition: (
                    None
                    if row[group][metric][condition] is None
                    else round(row[group][metric][condition], digits)
                )
                for condition in CONDITIONS
            }
            values[label] = triplet(
                [display_row[metric][condition] for condition in CONDITIONS],
                digits,
            )
        display_row["calls_per_success"] = {
            condition: round(
                float(display_row["calls"][condition])
                / (float(display_row["avg_at_3"][condition]) / 100),
                1,
            )
            for condition in CONDITIONS
        }
        values["C/S"] = triplet(
            [display_row["calls_per_success"][condition] for condition in CONDITIONS]
        )
        displayed.append(display_row)
        baseline = float(display_row["avg_at_3"]["baseline"])
        self_delta = float(display_row["avg_at_3"]["self_route"]) - baseline
        preload_delta = float(display_row["avg_at_3"]["annotated_preload"]) - baseline
        output.append(
            {
                "Harness": row["harness"],
                "Model": row["model"],
                **values,
                "Δ": (f"—/{self_delta:+.1f}/{preload_delta:+.1f}"),
            }
        )
    macro_values: dict[str, str] = {}
    for _, metric, label in METRICS:
        digits = 2 if metric == "calls" else 1
        values = [
            statistics.mean(
                float(row[metric][condition])
                for row in displayed
                if row[metric][condition] is not None
            )
            if any(row[metric][condition] is not None for row in displayed)
            else None
            for condition in CONDITIONS
        ]
        macro_values[label] = triplet(values, digits)
    displayed_deltas = [
        (
            float(row["avg_at_3"]["self_route"]) - float(row["avg_at_3"]["baseline"]),
            float(row["avg_at_3"]["annotated_preload"]) - float(row["avg_at_3"]["baseline"]),
        )
        for row in displayed
    ]
    output.append(
        {
            "Harness": "Macro Average",
            "Model": "",
            **macro_values,
            "Δ": (
                f"—/{statistics.mean(row[0] for row in displayed_deltas):+.1f}/"
                f"{statistics.mean(row[1] for row in displayed_deltas):+.1f}"
            ),
        }
    )
    ordered = (
        "Harness",
        "Model",
        "Avg@3",
        "Δ",
        "TEA",
        "TD-F1",
        "TCC",
        "REA",
        "DAR",
        "SkE-F1",
        "SVR",
        "Calls",
        "C/S",
    )
    return [{key: row[key] for key in ordered} for row in output]


def write_latex(path: Path, rows: list[dict[str, str]]) -> None:
    lines = [
        r"\begin{tabular}{llrrrrrrrrrrr}",
        r"\toprule",
        (
            r"Harness & Model & Avg@3 & $\Delta$ & TEA & TD-F1 & TCC & "
            r"REA & DAR & SkE-F1 & SVR & Calls & C/S \\"
        ),
        r"\midrule",
    ]
    for row in rows:
        cells = [
            latex_escape(row["Harness"]),
            latex_escape(row["Model"]),
            row["Avg@3"],
            row["Δ"],
            row["TEA"],
            row["TD-F1"],
            row["TCC"],
            row["REA"],
            row["DAR"],
            row["SkE-F1"],
            row["SVR"],
            row["Calls"],
            row["C/S"],
        ]
        lines.append(" & ".join(cells) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce paper Table 2")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = build_rows()
    write_csv(args.output_dir / "table2.csv", rows)
    write_latex(args.output_dir / "table2.tex", rows)
    print(f"wrote Table 2 to {args.output_dir}")


if __name__ == "__main__":
    main()
