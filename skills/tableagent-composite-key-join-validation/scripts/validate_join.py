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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--left-file", required=True, type=Path)
    parser.add_argument("--right-file", required=True, type=Path)
    parser.add_argument("--left-sheet")
    parser.add_argument("--right-sheet")
    parser.add_argument("--left-keys", required=True, nargs="+")
    parser.add_argument("--right-keys", required=True, nargs="+")
    parser.add_argument("--relationship", choices=["one_to_one", "many_to_one", "one_to_many", "many_to_many"], required=True)
    parser.add_argument("--min-left-match-rate", type=float, default=0.0)
    parser.add_argument("--min-right-match-rate", type=float, default=0.0)
    parser.add_argument("--max-expansion-ratio", type=float)
    args = parser.parse_args()

    errors = []
    left = read(args.left_file, args.left_sheet)
    right = read(args.right_file, args.right_sheet)
    if len(args.left_keys) != len(args.right_keys):
        errors.append("left and right key counts differ")
    missing_left = [key for key in args.left_keys if key not in left]
    missing_right = [key for key in args.right_keys if key not in right]
    if missing_left or missing_right:
        result = {"valid": False, "failure_state": "missing_key_column", "missing_left": missing_left, "missing_right": missing_right}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    left_keyed = left.dropna(subset=args.left_keys).copy()
    right_keyed = right.dropna(subset=args.right_keys).copy()
    left_dup = int(left_keyed.duplicated(args.left_keys, keep=False).sum())
    right_dup = int(right_keyed.duplicated(args.right_keys, keep=False).sum())
    if args.relationship in {"one_to_one", "one_to_many"} and left_dup:
        errors.append("left keys are not unique for declared relationship")
    if args.relationship in {"one_to_one", "many_to_one"} and right_dup:
        errors.append("right keys are not unique for declared relationship")

    renamed = right_keyed.rename(columns=dict(zip(args.right_keys, args.left_keys)))
    right_key_frame = renamed[args.left_keys].drop_duplicates()
    left_key_frame = left_keyed[args.left_keys].drop_duplicates()
    left_marked = left_keyed.merge(right_key_frame.assign(_matched=True), on=args.left_keys, how="left")
    right_marked = renamed.merge(left_key_frame.assign(_matched=True), on=args.left_keys, how="left")
    left_match_rate = float(left_marked["_matched"].fillna(False).mean()) if len(left_marked) else 0.0
    right_match_rate = float(right_marked["_matched"].fillna(False).mean()) if len(right_marked) else 0.0
    joined = left_keyed.merge(renamed, on=args.left_keys, how="inner", suffixes=("_left", "_right"))
    expansion_ratio = len(joined) / max(len(left_keyed), 1)
    if left_match_rate < args.min_left_match_rate:
        errors.append("left match rate below threshold")
    if right_match_rate < args.min_right_match_rate:
        errors.append("right match rate below threshold")
    if args.max_expansion_ratio is not None and expansion_ratio > args.max_expansion_ratio:
        errors.append("joined row expansion exceeds threshold")

    result = {
        "valid": not errors,
        "failure_state": None if not errors else "join_validation_failed",
        "relationship": args.relationship,
        "left_rows": int(len(left)),
        "right_rows": int(len(right)),
        "left_non_null_key_rows": int(len(left_keyed)),
        "right_non_null_key_rows": int(len(right_keyed)),
        "left_duplicate_key_rows": left_dup,
        "right_duplicate_key_rows": right_dup,
        "left_match_rate": round(left_match_rate, 8),
        "right_match_rate": round(right_match_rate, 8),
        "joined_rows": int(len(joined)),
        "expansion_ratio": round(expansion_ratio, 8),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
