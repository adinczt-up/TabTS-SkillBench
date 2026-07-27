#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--source-value", required=True, type=float)
    parser.add_argument("--target-label", required=True)
    parser.add_argument("--target-value", required=True, type=float)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--rule", required=True, choices=[
        "target_minus_source",
        "source_minus_target",
        "improvement_higher_better",
        "improvement_lower_better",
        "absolute_change",
    ])
    args = parser.parse_args()
    raw = args.target_value - args.source_value
    if args.rule in {"target_minus_source", "improvement_higher_better"}:
        reported = raw
    elif args.rule in {"source_minus_target", "improvement_lower_better"}:
        reported = -raw
    else:
        reported = abs(raw)
    result = {
        "valid": True,
        "source": {"label": args.source_label, "value": args.source_value},
        "target": {"label": args.target_label, "value": args.target_value},
        "unit": args.unit,
        "rule": args.rule,
        "raw_target_minus_source": raw,
        "reported_delta": reported,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
