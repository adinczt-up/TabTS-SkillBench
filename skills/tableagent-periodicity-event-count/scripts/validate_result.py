#!/usr/bin/env python3
"""Validate periodic marker and anchor-count evidence without gold labels."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def stamp(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    errors: list[str] = []
    target = data.get("target")
    if target not in {"period", "period_change", "event_count"}:
        errors.append("invalid or missing target")
    markers = [stamp(value) for value in data.get("event_timestamps", [])]
    if markers != sorted(markers) or len(set(markers)) != len(markers):
        errors.append("event timestamps must be unique and chronological")
    if target in {"period", "period_change"} and len(markers) < 3:
        errors.append("at least three compatible markers are required")
    if target == "period_change":
        windows = data.get("windows", [])
        if len(windows) != 2 or any(int(window.get("supporting_cycle_count", 0)) < 2 for window in windows):
            errors.append("period change requires two windows with at least two intervals each")
    if target == "event_count":
        anchor = data.get("anchor_record")
        if not anchor:
            errors.append("event_count requires anchor_record")
        else:
            include = anchor.get("anchor_inclusion_rule")
            if include not in {"include", "exclude"}:
                errors.append("invalid anchor inclusion rule")
            anchor_end = stamp(anchor["event_end"]) if anchor.get("event_end") else None
            eligible = [value for value in markers if anchor_end is None or value > anchor_end]
            if include == "include" and anchor.get("event_marker"):
                eligible = [stamp(anchor["event_marker"])] + eligible
            if data.get("reported_count") is not None and int(data["reported_count"]) != len(eligible):
                errors.append("reported_count cannot be recomputed from anchor rule and markers")
    if data.get("failure_state") and data.get("final_claim"):
        errors.append("final_claim is prohibited when failure_state is present")
    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
