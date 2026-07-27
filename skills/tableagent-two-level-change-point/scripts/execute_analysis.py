#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def read_table(path: Path, sheet: str | None) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet or 0)
    return pd.read_csv(path, low_memory=False)


def format_period(value: pd.Timestamp, frequency: str) -> str:
    if frequency == "day":
        return value.strftime("%Y-%m-%d")
    if frequency == "month":
        return value.strftime("%Y-%m")
    if frequency == "quarter":
        return f"{value.year}-Q{value.quarter}"
    return value.strftime("%Y")


def write_json(path: Path | None, value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path is None:
        print(text, end="")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--sheet")
    parser.add_argument("--group", required=True)
    parser.add_argument("--time", required=True)
    parser.add_argument("--value", required=True)
    parser.add_argument("--frequency", required=True, choices=["day", "month", "quarter", "year"])
    parser.add_argument("--group-output-field", default="segment")
    parser.add_argument("--time-output-field", default="change_period")
    parser.add_argument("--min-side", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit-candidates-output", type=Path)
    args = parser.parse_args()

    data = read_table(args.file, args.sheet)[[args.group, args.time, args.value]].copy()
    data[args.time] = pd.to_datetime(data[args.time], errors="coerce")
    data[args.value] = pd.to_numeric(data[args.value], errors="coerce")
    data = data.dropna()
    if data.duplicated([args.group, args.time]).any():
        write_json(args.output, {"status": "failed", "failure_state": "duplicate_group_period"})
        return 1

    winners: list[dict[str, object]] = []
    audit: dict[str, list[dict[str, object]]] = {}
    unresolved: list[dict[str, object]] = []
    for group, frame in data.sort_values(args.time).groupby(args.group, dropna=False, sort=True):
        values = frame[args.value].to_numpy(float)
        times = frame[args.time].tolist()
        candidates: list[dict[str, object]] = []
        for index in range(args.min_side, len(values) - args.min_side + 1):
            before = values[:index]
            after = values[index:]
            before_mean = float(before.mean())
            after_mean = float(after.mean())
            candidates.append({
                args.time_output_field: format_period(times[index], args.frequency),
                "before_mean": before_mean,
                "after_mean": after_mean,
                "level_change": after_mean - before_mean,
                "sse": float(np.sum((before - before_mean) ** 2) + np.sum((after - after_mean) ** 2)),
                "before_n": len(before),
                "after_n": len(after),
            })
        if not candidates:
            unresolved.append({args.group_output_field: str(group), "reason": "no_eligible_split", "n": len(values)})
            continue
        best = min(candidates, key=lambda row: (float(row["sse"]), str(row[args.time_output_field])))
        winners.append({args.group_output_field: str(group), **best})
        audit[str(group)] = candidates

    winners.sort(key=lambda row: (-abs(float(row["level_change"])), str(row[args.group_output_field]), str(row[args.time_output_field])))
    selected = winners[: max(args.top_k, 0)]
    valid = all(int(row["before_n"]) >= args.min_side and int(row["after_n"]) >= args.min_side for row in winners)
    result = {
        "status": "ok" if valid else "failed",
        "failure_state": None if valid else "validation_failed",
        "input": str(args.file),
        "parameters": {
            "group": args.group,
            "time": args.time,
            "value": args.value,
            "frequency": args.frequency,
            "group_output_field": args.group_output_field,
            "time_output_field": args.time_output_field,
            "min_side": args.min_side,
            "top_k": args.top_k,
        },
        "group_results": winners,
        "selected_rows": selected,
        "unresolved_groups": unresolved,
        "validation": {"valid": valid, "selected_count": len(selected)},
    }
    write_json(args.output, result)
    if args.audit_candidates_output:
        write_json(args.audit_candidates_output, {"candidate_splits_by_group": audit})
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
