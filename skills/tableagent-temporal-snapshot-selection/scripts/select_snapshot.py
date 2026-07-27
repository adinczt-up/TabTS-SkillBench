#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def read(path: Path, sheet: str | None) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet or 0)
    return pd.read_csv(path, low_memory=False)


def convert(series: pd.Series, kind: str) -> pd.Series:
    if kind == "numeric":
        return pd.to_numeric(series, errors="coerce")
    if kind == "datetime":
        return pd.to_datetime(series, errors="coerce", utc=True)
    return series.astype("string")


def parse_anchor(value: str | None, kind: str):
    if value is None:
        return None
    if kind == "numeric":
        return float(value)
    if kind == "datetime":
        return pd.to_datetime(value, utc=True)
    return value


def json_value(value):
    if pd.isna(value):
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
    parser.add_argument("--group-columns", required=True, nargs="+")
    parser.add_argument("--order-column", required=True)
    parser.add_argument("--order-type", choices=["numeric", "datetime", "lexical"], required=True)
    parser.add_argument("--mode", choices=["final", "exact", "latest_at_or_before", "earliest_at_or_after"], required=True)
    parser.add_argument("--anchor")
    parser.add_argument("--tie-break-columns", nargs="*", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.mode != "final" and args.anchor is None:
        print(json.dumps({"valid": False, "failure_state": "anchor_required"}, indent=2))
        return 1
    frame = read(args.file, args.sheet)
    required = [*args.group_columns, args.order_column, *args.tie_break_columns]
    missing = [column for column in required if column not in frame]
    if missing:
        print(json.dumps({"valid": False, "failure_state": "missing_columns", "missing": missing}, indent=2))
        return 1

    frame = frame.copy()
    frame["_order"] = convert(frame[args.order_column], args.order_type)
    invalid_order_rows = int(frame["_order"].isna().sum())
    frame = frame.dropna(subset=[*args.group_columns, "_order"])
    anchor = parse_anchor(args.anchor, args.order_type)
    selected = []
    missing_groups = []
    ambiguous_groups = []
    grouper = args.group_columns[0] if len(args.group_columns) == 1 else args.group_columns
    for group_key, group in frame.groupby(grouper, dropna=False, sort=False):
        key_values = group_key if isinstance(group_key, tuple) else (group_key,)
        key_record = {column: json_value(value) for column, value in zip(args.group_columns, key_values)}
        eligible = group
        if args.mode == "exact":
            eligible = group[group["_order"] == anchor]
            target = anchor
        elif args.mode == "latest_at_or_before":
            eligible = group[group["_order"] <= anchor]
            target = eligible["_order"].max() if len(eligible) else None
        elif args.mode == "earliest_at_or_after":
            eligible = group[group["_order"] >= anchor]
            target = eligible["_order"].min() if len(eligible) else None
        else:
            target = eligible["_order"].max() if len(eligible) else None
        if target is None or not len(eligible):
            missing_groups.append(key_record)
            continue
        candidates = eligible[eligible["_order"] == target].copy()
        if len(candidates) > 1 and not args.tie_break_columns:
            ambiguous_groups.append({**key_record, "candidate_count": int(len(candidates)), "order_value": json_value(target)})
            continue
        if args.tie_break_columns:
            candidates = candidates.sort_values(args.tie_break_columns, kind="stable")
        row = candidates.iloc[-1].drop(labels=["_order"]).to_dict()
        selected.append({str(key): json_value(value) for key, value in row.items()})

    valid = not ambiguous_groups and invalid_order_rows == 0
    result = {
        "valid": valid,
        "failure_state": None if valid else "snapshot_validation_failed",
        "mode": args.mode,
        "anchor": args.anchor,
        "group_columns": args.group_columns,
        "order_column": args.order_column,
        "order_type": args.order_type,
        "input_rows": int(len(read(args.file, args.sheet))),
        "invalid_order_rows": invalid_order_rows,
        "selected_count": len(selected),
        "selected_rows": selected,
        "missing_groups": missing_groups,
        "ambiguous_groups": ambiguous_groups,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
