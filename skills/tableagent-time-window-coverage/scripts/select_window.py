#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def read(path: Path, sheet: str | None) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet or 0)
    return pd.read_csv(path, low_memory=False)


def write_selected(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".parquet", ".pq"}:
        frame.to_parquet(path, index=False)
    elif path.suffix.lower() == ".csv":
        frame.to_csv(path, index=False)
    else:
        raise ValueError("selected output must use .parquet, .pq, or .csv")


def convert(series: pd.Series, kind: str) -> pd.Series:
    if kind == "numeric":
        return pd.to_numeric(series, errors="coerce")
    if kind == "datetime":
        return pd.to_datetime(series, errors="coerce", utc=True)
    return series.astype("string")


def boundary(value: str | None, kind: str):
    if value is None:
        return None
    if kind == "numeric":
        return float(value)
    if kind == "datetime":
        return pd.to_datetime(value, utc=True)
    return value


def scalar(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--sheet")
    parser.add_argument("--order-column", required=True)
    parser.add_argument("--order-type", choices=["numeric", "datetime", "lexical"], required=True)
    parser.add_argument("--lower")
    parser.add_argument("--upper")
    lower = parser.add_mutually_exclusive_group()
    lower.add_argument("--lower-inclusive", action="store_true")
    lower.add_argument("--lower-exclusive", action="store_true")
    upper = parser.add_mutually_exclusive_group()
    upper.add_argument("--upper-inclusive", action="store_true")
    upper.add_argument("--upper-exclusive", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--selected-output",
        type=Path,
        help="Optional filtered data file (.parquet or .csv); rows are never embedded in evidence JSON.",
    )
    args = parser.parse_args()

    frame = read(args.file, args.sheet)
    if args.order_column not in frame:
        print(json.dumps({"valid": False, "failure_state": "missing_order_column"}, indent=2))
        return 1
    frame = frame.copy()
    frame["_order"] = convert(frame[args.order_column], args.order_type)
    invalid = int(frame["_order"].isna().sum())
    valid_frame = frame.dropna(subset=["_order"])
    low = boundary(args.lower, args.order_type)
    high = boundary(args.upper, args.order_type)
    mask = pd.Series(True, index=valid_frame.index)
    if low is not None:
        mask &= valid_frame["_order"] >= low if args.lower_inclusive else valid_frame["_order"] > low
    if high is not None:
        mask &= valid_frame["_order"] < high if args.upper_exclusive else valid_frame["_order"] <= high
    selected = valid_frame.loc[mask].drop(columns=["_order"])
    if args.selected_output:
        write_selected(selected, args.selected_output)
    result = {
        "valid": bool(len(selected) and invalid == 0),
        "failure_state": None if len(selected) and invalid == 0 else "window_validation_failed",
        "order_column": args.order_column,
        "order_type": args.order_type,
        "lower": args.lower,
        "lower_inclusive": bool(args.lower_inclusive),
        "upper": args.upper,
        "upper_inclusive": not bool(args.upper_exclusive),
        "observed_min": scalar(valid_frame["_order"].min()) if len(valid_frame) else None,
        "observed_max": scalar(valid_frame["_order"].max()) if len(valid_frame) else None,
        "input_rows": int(len(frame)),
        "invalid_order_rows": invalid,
        "selected_row_count": int(len(selected)),
        "selected_columns": [str(column) for column in selected.columns],
        "selected_output": str(args.selected_output) if args.selected_output else None,
        "selected_output_bytes": (
            args.selected_output.stat().st_size
            if args.selected_output and args.selected_output.is_file()
            else None
        ),
        "evidence_policy": "summary_only_no_embedded_rows",
    }
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
