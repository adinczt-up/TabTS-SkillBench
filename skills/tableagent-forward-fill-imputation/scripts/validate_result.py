#!/usr/bin/env python3
"""Validate forward-fill evidence by source recomputation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from execute_analysis import compute


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    observed = json.loads(args.input.read_text(encoding="utf-8-sig"))
    errors = []
    if observed.get("status") != "ok":
        errors.append("non_ok_result")
    elif compute(Path(observed["input"]), observed.get("parameters", {})) != observed:
        errors.append("source_recomputation_mismatch")
    if any(row.get("gap_periods", 0) <= 0 for row in observed.get("result_rows", [])):
        errors.append("future_or_same_period_source")
    report = {
        "status": "ok" if not errors else "failed",
        "valid": not errors,
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
