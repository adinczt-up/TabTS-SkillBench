#!/usr/bin/env python3
"""Build a deterministic regular-period alignment plan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


FREQUENCIES = {"month": "MS", "quarter": "QS", "year": "YS"}
FORMATS = {"month": "YYYY-MM", "quarter": "YYYY-Qn", "year": "YYYY"}


def format_period(value: pd.Timestamp, frequency: str) -> str:
    if frequency == "month":
        return value.strftime("%Y-%m")
    if frequency == "quarter":
        return f"{value.year}-Q{value.quarter}"
    return value.strftime("%Y")


def parse_period(value: str, frequency: str) -> pd.Timestamp:
    if frequency == "quarter":
        year, quarter = value.upper().split("-Q")
        return pd.Timestamp(int(year), (int(quarter) - 1) * 3 + 1, 1)
    if frequency == "year":
        return pd.Timestamp(int(value), 1, 1)
    return pd.Timestamp(value + "-01" if len(value) == 7 else value)


def shift(value: pd.Timestamp, frequency: str, mode: str) -> pd.Timestamp | None:
    if mode == "none":
        return None
    if mode == "previous_period":
        return value - {"month": pd.DateOffset(months=1), "quarter": pd.DateOffset(months=3), "year": pd.DateOffset(years=1)}[frequency]
    if mode == "previous_year_same_period":
        return value - pd.DateOffset(years=1)
    raise ValueError("invalid_comparison_mode")


def execute(contract: dict[str, Any]) -> dict[str, Any]:
    required = {
        "frequency", "window_start", "window_end_exclusive",
        "requested_periods", "comparison_mode", "output_period_format",
    }
    missing = sorted(required - set(contract))
    if missing:
        raise ValueError("missing_contract_fields:" + ",".join(missing))
    frequency = contract["frequency"]
    if frequency not in FREQUENCIES:
        raise ValueError("unsupported_frequency")
    if contract["output_period_format"] != FORMATS[frequency]:
        raise ValueError("output_period_format_frequency_mismatch")
    start = pd.Timestamp(contract["window_start"])
    end = pd.Timestamp(contract["window_end_exclusive"])
    if start >= end:
        raise ValueError("invalid_window")
    expected_ts = list(pd.date_range(start=start, end=end, freq=FREQUENCIES[frequency], inclusive="left"))
    expected = [format_period(value, frequency) for value in expected_ts]
    requested_ts = sorted({parse_period(str(value), frequency) for value in contract["requested_periods"]})
    outside = [format_period(value, frequency) for value in requested_ts if not (start <= value < end)]
    if outside:
        raise ValueError("requested_period_outside_window:" + ",".join(outside))
    comparison_map = []
    for value in requested_ts:
        comparison = shift(value, frequency, contract["comparison_mode"])
        comparison_map.append({
            "requested": format_period(value, frequency),
            "comparison": format_period(comparison, frequency) if comparison is not None else None,
        })
    observed = {format_period(parse_period(str(value), frequency), frequency) for value in contract.get("observed_periods", [])}
    missing_periods = [value for value in expected if observed and value not in observed]
    return {
        "operation": "temporal_alignment",
        "status": "ok",
        "parameters": contract,
        "frequency": frequency,
        "output_period_format": contract["output_period_format"],
        "expected_periods": expected,
        "requested_periods": [format_period(value, frequency) for value in requested_ts],
        "comparison_map": comparison_map,
        "missing_periods": missing_periods,
        "sort_order": "chronological",
        "checks": {
            "regular_index": True,
            "requested_inside_window": True,
            "canonical_period_format": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8-sig"))
    result = execute(contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
