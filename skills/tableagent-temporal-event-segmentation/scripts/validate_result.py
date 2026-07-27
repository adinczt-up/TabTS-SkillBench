#!/usr/bin/env python3
"""Validate structured temporal event records without using a gold answer."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    errors: list[str] = []
    for field in ("parameters", "events", "reported_count"):
        if field not in data:
            errors.append(f"missing field: {field}")
    events = data.get("events", [])
    previous_end = None
    for index, event in enumerate(events):
        missing = [field for field in ("start_time", "end_time", "direction", "type", "magnitude") if field not in event]
        if missing:
            errors.append(f"event {index} missing: {','.join(missing)}")
            continue
        start, end = parse_time(event["start_time"]), parse_time(event["end_time"])
        if end < start:
            errors.append(f"event {index} ends before it starts")
        if previous_end is not None and start <= previous_end:
            errors.append(f"event {index} overlaps or is not chronologically independent")
        previous_end = max(previous_end, end) if previous_end else end
        if not event.get("member_candidates"):
            errors.append(f"event {index} has no candidate evidence")
    included = [event for event in events if event.get("in_requested_window", True)]
    if "reported_count" in data and int(data["reported_count"]) != len(included):
        errors.append("reported_count cannot be recomputed from included events")
    if data.get("failure_state") and data.get("final_claim"):
        errors.append("final_claim is prohibited when failure_state is present")
    result = {"valid": not errors, "recomputed_count": len(included), "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
