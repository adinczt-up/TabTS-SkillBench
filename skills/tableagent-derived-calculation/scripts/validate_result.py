#!/usr/bin/env python3
"""Validate a TableAgent derived-calculation result JSON."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def numeric_values(data: dict) -> list[float]:
    values = []
    for item in data.get("inputs", []):
        try:
            values.append(float(item["value"]))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"input value is not numeric: {item!r}") from exc
    return values


def recompute(data: dict) -> float:
    op = str(data.get("operation", "")).lower()
    values = numeric_values(data)
    if op in {"sum", "total", "cumulative"}:
        return sum(values)
    if op in {"average", "mean"}:
        if not values:
            raise ValueError("average requires at least one input")
        return sum(values) / len(values)
    if op == "count":
        return float(len(data.get("included_rows", values)))
    if op == "difference":
        if len(values) != 2:
            raise ValueError("difference requires exactly two inputs")
        return values[0] - values[1]
    if op == "share":
        if len(values) != 2 or values[1] == 0:
            raise ValueError("share requires part and nonzero total")
        return values[0] / values[1] * 100.0
    if op in {"growth", "yoy", "mom"}:
        if len(values) != 2 or values[1] == 0:
            raise ValueError("growth requires current and nonzero previous")
        return (values[0] - values[1]) / values[1] * 100.0
    raise ValueError(f"unsupported operation: {op}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--tolerance", type=float, default=1e-6)
    args = parser.parse_args()

    errors: list[str] = []
    data = load_json(args.input)
    for field in ("operation", "inputs", "result"):
        if field not in data:
            errors.append(f"missing field: {field}")
    recomputed = None
    valid = False
    if not errors:
        try:
            recomputed = recompute(data)
            result = float(data["result"])
            valid = math.isclose(result, recomputed, rel_tol=args.tolerance, abs_tol=args.tolerance)
            if not valid:
                errors.append(f"result mismatch: result={result}, recomputed={recomputed}")
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    row_count = data.get("row_count")
    included_rows = data.get("included_rows")
    if row_count is not None and included_rows is not None and int(row_count) != len(included_rows):
        valid = False
        errors.append("row_count does not match included_rows length")
    print(json.dumps({"valid": valid and not errors, "recomputed": recomputed, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if valid and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
