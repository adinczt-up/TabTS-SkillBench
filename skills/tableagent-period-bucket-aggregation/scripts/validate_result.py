#!/usr/bin/env python3
"""Validate a two-stage period aggregation result."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    contract = data.get("grain_contract") or {}
    thresholds = data.get("thresholds") or {}
    counts = data.get("counts") or {}
    rows = data.get("period_rows") or []
    groups = data.get("group_columns") or []
    required_contract = {
        "source_grain", "analysis_unit_frequency", "measure_semantics",
        "within_unit_aggregate", "period_frequency", "period_aggregate",
    }
    missing = sorted(required_contract - set(contract))
    if missing:
        errors.append(f"missing grain contract fields: {missing}")
    minimum = thresholds.get("min_analysis_units_per_period")
    min_periods = thresholds.get("min_periods_per_group")
    if not isinstance(minimum, int) or minimum < 1:
        errors.append("invalid min_analysis_units_per_period")
    if not isinstance(min_periods, int) or min_periods < 1:
        errors.append("invalid min_periods_per_group")
    keys = set()
    group_counts: dict[tuple[str, ...], int] = {}
    for index, row in enumerate(rows):
        key = tuple(str(row.get(k)) for k in [*groups, "period_start"])
        if key in keys:
            errors.append(f"duplicate group-period key at row {index}")
        keys.add(key)
        group_key = tuple(str(row.get(k)) for k in groups)
        group_counts[group_key] = group_counts.get(group_key, 0) + 1
        if isinstance(minimum, int) and row.get("analysis_unit_n", -1) < minimum:
            errors.append(f"row {index} violates analysis-unit threshold")
        try:
            finite = math.isfinite(float(row.get("raw_value")))
        except (TypeError, ValueError):
            finite = False
        if not finite:
            errors.append(f"row {index} has nonfinite raw_value")
    if isinstance(min_periods, int):
        for key, count in group_counts.items():
            if count < min_periods:
                errors.append(f"group {key} violates retained-period threshold")
    if counts.get("retained_period_n") != len(rows):
        errors.append("retained_period_n does not match period_rows")
    if counts.get("source_row_n", 0) < counts.get("analysis_unit_n", 0):
        errors.append("analysis-unit count exceeds source-row count")
    frequency = contract.get("analysis_unit_frequency")
    if frequency != "row" and counts.get("source_row_n") == counts.get("analysis_unit_n"):
        errors.append(
            "non-row analysis grain produced one analysis unit per source row; "
            "verify entity keys and first-stage aggregation"
        )
    if frequency == "row":
        source_grain = str(contract.get("source_grain", "")).casefold()
        if any(token in source_grain for token in ("hour", "minute", "second")):
            errors.append("row analysis unit conflicts with finer timestamped source grain")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    errors = validate(data)
    report = {"status": "failed" if errors else "ok", "valid": not errors, "errors": errors}
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
