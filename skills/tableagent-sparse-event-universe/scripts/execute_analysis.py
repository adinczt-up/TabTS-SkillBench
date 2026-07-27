#!/usr/bin/env python3
"""Complete sparse event facts against a declared analysis-unit universe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.casefold()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"unsupported input format: {path.suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--universe-key", action="append", required=True)
    parser.add_argument("--event-key", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--count-column", default="event_count")
    parser.add_argument("--flag-column", default="event_flag")
    args = parser.parse_args()
    if len(args.universe_key) != len(args.event_key):
        raise ValueError("universe-key and event-key counts must match")

    universe = read_table(args.universe)
    events = read_table(args.events)
    for column in args.universe_key:
        if column not in universe:
            raise ValueError(f"universe key not found: {column}")
    for column in args.event_key:
        if column not in events:
            raise ValueError(f"event key not found: {column}")
    if universe[args.universe_key].isna().any().any():
        raise ValueError("null_universe_key")
    if events[args.event_key].isna().any().any():
        raise ValueError("null_event_key")
    if universe.duplicated(args.universe_key).any():
        raise ValueError("duplicate_universe_key")
    if args.count_column in universe or args.flag_column in universe:
        raise ValueError("output event columns already exist in universe")

    normalized = events.groupby(args.event_key, dropna=False).size().rename(args.count_column).reset_index()
    rename_map = dict(zip(args.event_key, args.universe_key))
    normalized = normalized.rename(columns=rename_map)
    unmatched = normalized.merge(
        universe[args.universe_key], on=args.universe_key, how="left", indicator=True
    )
    unmatched = unmatched[unmatched["_merge"] == "left_only"]
    if not unmatched.empty:
        sample = unmatched[args.universe_key].head(10).to_dict(orient="records")
        raise ValueError(f"unmatched_event_keys: count={len(unmatched)} sample={sample}")

    completed = universe.merge(normalized, on=args.universe_key, how="left", validate="one_to_one")
    completed[args.count_column] = completed[args.count_column].fillna(0).astype("int64")
    completed[args.flag_column] = completed[args.count_column].gt(0).astype("int8")
    duplicate_n = int(completed.duplicated(args.universe_key).sum())
    positive_n = int(completed[args.flag_column].sum())
    total_n = int(len(completed))
    zero_n = total_n - positive_n
    if total_n != len(universe) or duplicate_n:
        raise ValueError("grain_multiplication_or_lost_universe_units")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix.casefold() in {".parquet", ".pq"}:
        completed.to_parquet(args.output, index=False)
    elif args.output.suffix.casefold() == ".csv":
        completed.to_csv(args.output, index=False)
    else:
        raise ValueError("output must be CSV or Parquet")
    manifest = {
        "status": "ok",
        "universe_keys": args.universe_key,
        "absence_semantics": "no_matching_child_means_zero",
        "counts": {
            "universe_unit_n": total_n,
            "matched_positive_unit_n": positive_n,
            "zero_event_unit_n": zero_n,
            "output_unit_n": int(len(completed)),
            "unmatched_event_key_n": 0,
            "duplicate_output_key_n": duplicate_n,
        },
        "output_columns": list(completed.columns),
        "output_path": str(args.output),
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output_unit_n": total_n, "zero_event_unit_n": zero_n}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
