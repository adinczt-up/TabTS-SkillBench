#!/usr/bin/env python3
"""Recompute and validate a one-step linear trend forecast."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from execute_analysis import compute


def normalized(value: Any) -> Any:
    if isinstance(value, float):
        return None if not math.isfinite(value) else round(value, 10)
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    observed = json.loads(args.input.read_text(encoding="utf-8-sig"))
    errors = []
    required = {"operation", "status", "input", "parameters", "forecast_period", "result_rows", "checks"}
    missing = sorted(required - set(observed))
    if missing:
        errors.append("missing_fields:" + ",".join(missing))
    if observed.get("status") != "ok":
        errors.append("non_ok_result")
    if not errors:
        expected = compute(Path(observed["input"]), observed["parameters"])
        if normalized(expected) != normalized(observed):
            errors.append("source_recomputation_mismatch")
        if not all(isinstance(row.get("train_period_n"), int) for row in observed.get("result_rows", [])):
            errors.append("train_period_n_not_integer")
        if not all(bool(value) for value in observed.get("checks", {}).values()):
            errors.append("failed_invariant")
    report = {
        "status": "ok" if not errors else "failed",
        "valid": not errors,
        "source_result": str(args.input),
        "errors": errors,
        "recomputed_from_source": not errors,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
