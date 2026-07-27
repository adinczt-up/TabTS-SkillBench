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
    for field in ("requested_role", "population", "stage", "unit", "missing_policy", "candidates", "selected_field"):
        if field not in data or data[field] in (None, "", []):
            errors.append(f"missing field: {field}")
    candidates = data.get("candidates", [])
    selected = [item for item in candidates if item.get("status") == "selected"]
    if len(selected) != 1:
        errors.append("exactly one candidate must be selected")
    if selected and selected[0].get("field") != data.get("selected_field"):
        errors.append("selected_field does not match selected candidate")
    for item in candidates:
        if not item.get("field") or not item.get("grain") or not item.get("role") or not item.get("reason"):
            errors.append(f"candidate lacks evidence: {item.get('field')}")
    result = {"valid": not errors, "selected_field": data.get("selected_field"), "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
