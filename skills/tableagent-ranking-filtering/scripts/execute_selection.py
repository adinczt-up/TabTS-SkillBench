#!/usr/bin/env python3
"""Materialize an auditable exact-K or tie-inclusive raw-value selection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def read(path: Path, sheet: str | None) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet or 0)
    return pd.read_csv(path, low_memory=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--sheet")
    parser.add_argument("--metric-column", required=True)
    parser.add_argument("--entity-column")
    parser.add_argument("--k", required=True, type=int)
    parser.add_argument("--direction", choices=["top", "bottom"], default="top")
    parser.add_argument("--selection-mode", choices=["exact_k", "include_ties"], default="exact_k")
    parser.add_argument("--tie-tolerance", type=float, default=0.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    frame = read(args.file, args.sheet)
    if args.k < 1 or args.metric_column not in frame:
        print(json.dumps({"valid": False, "failure_state": "invalid_selection_parameters"}))
        return 1
    if args.entity_column and args.entity_column not in frame:
        print(json.dumps({"valid": False, "failure_state": "missing_entity_column"}))
        return 1

    work = frame.copy()
    work["_source_row"] = range(len(work))
    work["_metric"] = pd.to_numeric(work[args.metric_column], errors="coerce")
    invalid_metric_rows = int(work["_metric"].isna().sum())
    work = work.dropna(subset=["_metric"])
    if len(work) < args.k:
        print(json.dumps({"valid": False, "failure_state": "fewer_than_k_rows", "available": len(work)}))
        return 1

    ascending = args.direction == "bottom"
    work = work.sort_values(["_metric", "_source_row"], ascending=[ascending, True], kind="stable")
    cutoff = float(work.iloc[args.k - 1]["_metric"])
    if args.selection_mode == "exact_k":
        selected = work.iloc[:args.k]
    elif ascending:
        selected = work[work["_metric"] <= cutoff + args.tie_tolerance]
    else:
        selected = work[work["_metric"] >= cutoff - args.tie_tolerance]

    def row_record(row) -> dict:
        return {
            "source_row": int(row["_source_row"]),
            "entity": str(row[args.entity_column]) if args.entity_column else None,
            "raw_metric": float(row["_metric"]),
        }

    result = {
        "valid": True,
        "failure_state": None,
        "parameters": {
            "metric_column": args.metric_column,
            "k": args.k,
            "direction": args.direction,
            "selection_mode": args.selection_mode,
            "tie_tolerance": args.tie_tolerance,
        },
        "eligible_row_count": int(len(work)),
        "invalid_metric_rows": invalid_metric_rows,
        "cutoff_raw": cutoff,
        "eligible_rows": [row_record(row) for _, row in work.iterrows()],
        "selected_rows": [row_record(row) for _, row in selected.iterrows()],
        "selected_row_count": int(len(selected)),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
