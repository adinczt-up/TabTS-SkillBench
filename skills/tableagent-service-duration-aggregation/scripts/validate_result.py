#!/usr/bin/env python3
"""Validate a service-duration result from retained row evidence."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    errors: list[str] = []
    rows = data.get("rows", [])
    if data.get("row_count") != len(rows):
        errors.append("row_count mismatch")
    values = []
    for index, row in enumerate(rows):
        try:
            value = float(row["duration"])
            if not math.isfinite(value) or value < 0:
                raise ValueError
            values.append(value)
        except (KeyError, TypeError, ValueError):
            errors.append(f"invalid duration at row {index}")
    operation = data.get("parameters", {}).get("operation")
    recomputed = values if operation == "per_row" else (sum(values) if operation == "sum" else (sum(values) / len(values) if values and operation == "mean" else None))
    if recomputed is None:
        errors.append("invalid operation or empty mean")
    elif operation != "per_row" and not math.isclose(float(data.get("result")), recomputed, rel_tol=args.tolerance, abs_tol=args.tolerance):
        errors.append("result cannot be recomputed")
    if data.get("failure_state") and data.get("final_claim"):
        errors.append("final_claim prohibited under failure state")
    print(json.dumps({"valid": not errors, "recomputed": recomputed, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
