#!/usr/bin/env python3
"""Validate sparse-universe completion invariants."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    counts = data.get("counts") or {}
    if data.get("absence_semantics") != "no_matching_child_means_zero":
        errors.append("absence semantics do not permit zero fill")
    if not data.get("universe_keys"):
        errors.append("universe_keys are required")
    fields = (
        "universe_unit_n", "matched_positive_unit_n", "zero_event_unit_n",
        "output_unit_n", "unmatched_event_key_n", "duplicate_output_key_n",
    )
    for field in fields:
        if not isinstance(counts.get(field), int) or counts[field] < 0:
            errors.append(f"counts.{field} must be a nonnegative integer")
    if counts.get("universe_unit_n") != counts.get("output_unit_n"):
        errors.append("output count does not preserve the universe")
    if counts.get("matched_positive_unit_n", 0) + counts.get("zero_event_unit_n", 0) != counts.get("universe_unit_n"):
        errors.append("positive and zero units do not partition the universe")
    if counts.get("unmatched_event_key_n") != 0:
        errors.append("unmatched event keys remain")
    if counts.get("duplicate_output_key_n") != 0:
        errors.append("duplicate output keys remain")
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
