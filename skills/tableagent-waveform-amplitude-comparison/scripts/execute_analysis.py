#!/usr/bin/env python3
"""Compare robust waveform amplitudes between two table segments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def read_table(path: Path, sheet: str | None) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet or 0)
    return pd.read_csv(path)


def evidence(name: str, values: np.ndarray, quantile: float) -> dict:
    low, high = np.quantile(values, [quantile, 1.0 - quantile])
    span = float(high - low)
    return {
        "name": name,
        "n": int(values.size),
        "low": float(low),
        "high": float(high),
        "center": float((high + low) / 2.0),
        "peak_to_peak": span,
        "semi_amplitude": span / 2.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--sheet")
    parser.add_argument("--series", required=True)
    parser.add_argument("--split-index", required=True, type=int)
    parser.add_argument("--quantile", type=float, default=0.05)
    parser.add_argument("--tolerance", type=float, default=0.15)
    args = parser.parse_args()
    if not 0 <= args.quantile < 0.5 or args.tolerance < 0:
        raise ValueError("quantile must be in [0, 0.5) and tolerance must be nonnegative")
    frame = read_table(args.file, args.sheet)
    if args.series not in frame.columns:
        raise KeyError(f"missing series column: {args.series}")
    values = pd.to_numeric(frame[args.series], errors="coerce").to_numpy(float)
    if not 1 <= args.split_index < len(values):
        raise ValueError("split-index must create two nonempty segments")
    left = values[: args.split_index]
    right = values[args.split_index :]
    left = left[np.isfinite(left)]
    right = right[np.isfinite(right)]
    if min(left.size, right.size) < 8:
        print(json.dumps({"status": "failed", "failure_state": "insufficient_segment_coverage"}, indent=2))
        return 1
    segments = [evidence("before", left, args.quantile), evidence("after", right, args.quantile)]
    a, b = (segment["semi_amplitude"] for segment in segments)
    if min(a, b) <= 0:
        print(json.dumps({"status": "failed", "failure_state": "degenerate_amplitude", "segments": segments}, indent=2))
        return 1
    ratio = b / a
    relative = (b - a) / max(a, b)
    decision = "same" if abs(relative) <= args.tolerance else ("increase" if relative > 0 else "decrease")
    output = {
        "status": "ok",
        "method": "quantile",
        "segments": segments,
        "amplitude_ratio": float(ratio),
        "relative_difference": float(relative),
        "tolerance": args.tolerance,
        "decision": decision,
        "checks": {"same_definition": True, "offset_not_used_as_amplitude": True},
        "failure_state": None,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
