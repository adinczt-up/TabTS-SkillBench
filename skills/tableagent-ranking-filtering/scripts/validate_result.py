#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    errors = []
    rows = data.get("selected_rows", [])
    eligible = data.get("eligible_rows", [])
    params = data.get("parameters", {})
    if data.get("selected_row_count") != len(rows):
        errors.append("selected_row_count mismatch")
    if data.get("eligible_row_count") != len(eligible):
        errors.append("eligible_row_count mismatch")
    if len({row.get("source_row") for row in rows}) != len(rows):
        errors.append("duplicate selected source rows")
    if params.get("selection_mode") == "exact_k" and len(rows) != int(params.get("k", -1)):
        errors.append("exact_k must contain exactly K rows")

    direction = params.get("direction")
    tolerance = float(params.get("tie_tolerance", 0.0))
    cutoff = float(data.get("cutoff_raw", 0.0))
    if params.get("selection_mode") == "include_ties":
        if direction == "top":
            expected = {row["source_row"] for row in eligible if float(row["raw_metric"]) >= cutoff - tolerance}
        else:
            expected = {row["source_row"] for row in eligible if float(row["raw_metric"]) <= cutoff + tolerance}
        actual = {row.get("source_row") for row in rows}
        if expected != actual:
            errors.append("tie completeness mismatch")
    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
