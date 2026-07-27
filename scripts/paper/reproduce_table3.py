from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    DEFAULT_OUTPUT_ROOT,
    compute_ablation_results,
    latex_escape,
    write_csv,
)


def table_rows() -> list[dict[str, str | int | float]]:
    output: list[dict[str, str | int | float]] = []
    for row in compute_ablation_results():
        output.append(
            {
                "Ablation": row["ablation"],
                "Ref.": ("P" if row["reference_condition"] == "annotated_preload" else "S"),
                "Ref. SR": f"{row['reference_sr']:.1f}",
                "Ablated SR": f"{row['ablated_sr']:.1f}",
                "SR drop": f"{row['sr_loss']:.1f}",
                "95% CI": (f"[{row['ci_low']:.1f}, {row['ci_high']:.1f}]"),
                "McNemar p": row["mcnemar_exact_p"],
                "Paired tasks": row["paired_tasks"],
            }
        )
    return output


def write_latex(path: Path, rows: list[dict[str, str | int | float]]) -> None:
    lines = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Ablation & Ref. & Ref. SR & Ablated SR & SR drop (95\% CI) \\",
        r"\midrule",
    ]
    for row in rows:
        significance = r"$^\dagger$" if float(row["McNemar p"]) < 0.05 else ""
        lines.append(
            f"{latex_escape(str(row['Ablation']))} & {row['Ref.']} & "
            f"{row['Ref. SR']} & {row['Ablated SR']} & "
            f"{row['SR drop']} {row['95% CI']}{significance}" + r" \\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce paper Table 3")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = table_rows()
    write_csv(args.output_dir / "table3.csv", rows)
    write_latex(args.output_dir / "table3.tex", rows)
    print(f"wrote Table 3 to {args.output_dir}")


if __name__ == "__main__":
    main()
