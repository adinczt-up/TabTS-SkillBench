from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from common import (
    DEFAULT_OUTPUT_ROOT,
    gain_correlations,
    load_main_manifest,
    load_main_results,
    write_checksums,
    write_csv,
    write_json,
)
from reproduce_figures import figure4, figure5, figure7, figure8
from reproduce_table2 import build_rows as build_table2_rows
from reproduce_table2 import write_latex as write_table2_latex
from reproduce_table3 import table_rows as build_table3_rows
from reproduce_table3 import write_latex as write_table3_latex


def derived_summary() -> dict:
    data = load_main_results()
    manifest = load_main_manifest()
    baselines = [row["outcome"]["avg_at_3"]["baseline"] for row in data["rows"]]
    self_route = [row["outcome"]["avg_at_3"]["self_route"] for row in data["rows"]]
    correlations = gain_correlations(data)
    return {
        "benchmark": data["benchmark"],
        "task_count": manifest["task_count"],
        "configuration_count": manifest["configuration_count"],
        "condition_count": len(manifest["conditions"]),
        "repeats": manifest["repeats"],
        "execution_count": manifest["execution_count"],
        "macro_avg_at_3": data["macro_average"]["outcome"]["avg_at_3"],
        "macro_calls": data["macro_average"]["cost"]["calls"],
        "cross_configuration_std": {
            "baseline": statistics.pstdev(baselines),
            "self_route": statistics.pstdev(self_route),
        },
        "gain_vs_baseline": {
            condition: {
                "pearson_r": values["r"],
                "two_sided_p": values["p"],
                "sample_size": 9,
            }
            for condition, values in correlations.items()
        },
    }


def reproduce(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    table2 = build_table2_rows()
    write_csv(output_dir / "table2.csv", table2)
    write_table2_latex(output_dir / "table2.tex", table2)
    table3 = build_table3_rows()
    write_csv(output_dir / "table3.csv", table3)
    write_table3_latex(output_dir / "table3.tex", table3)
    data = load_main_results()
    figure4(output_dir / "figure4.svg", data)
    figure5(output_dir / "figure5.svg", data)
    figure7(output_dir / "figure7.svg", data)
    figure8(output_dir / "figure8.svg", data)
    write_json(output_dir / "paper_summary.json", derived_summary())
    if output_dir.resolve() == DEFAULT_OUTPUT_ROOT.resolve():
        write_checksums()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce all paper tables and figures")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    reproduce(args.output_dir)
    print(f"paper reproduction complete: {args.output_dir}")


if __name__ == "__main__":
    main()
