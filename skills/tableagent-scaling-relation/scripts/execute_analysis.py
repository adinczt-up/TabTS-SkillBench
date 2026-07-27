#!/usr/bin/env python3
"""Compute deterministic evidence for two-series scaling relations."""

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


def fit_scale(x: np.ndarray, y: np.ndarray, affine: bool) -> tuple[float, float, float, float]:
    if affine:
        slope, intercept = np.polyfit(x, y, 1)
    else:
        denom = float(np.dot(x, x))
        if denom == 0:
            raise ValueError("zero denominator for scale fit")
        slope, intercept = float(np.dot(x, y) / denom), 0.0
    pred = slope * x + intercept
    rmse = float(np.sqrt(np.mean((y - pred) ** 2)))
    rel = rmse / (float(np.std(y)) + 1e-12)
    corr = float(np.corrcoef(pred, y)[0, 1]) if len(y) > 1 else float("nan")
    return float(slope), float(intercept), rmse, rel if np.isfinite(rel) else float("inf")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--series-a", required=True)
    parser.add_argument("--series-b", required=True)
    parser.add_argument("--model", choices=["scale", "affine"], default="scale")
    parser.add_argument("--residual-tolerance", type=float, default=0.1)
    args = parser.parse_args()
    df = read_table(args.file, args.sheet)
    a = pd.to_numeric(df[args.series_a], errors="coerce").to_numpy(float)
    b = pd.to_numeric(df[args.series_b], errors="coerce").to_numpy(float)
    mask = np.isfinite(a) & np.isfinite(b)
    a, b = a[mask], b[mask]
    if len(a) < 3:
        print(json.dumps({"failure_state": "insufficient_overlap", "overlap_rows": int(len(a))}, indent=2))
        return 1
    affine = args.model == "affine"
    ab = fit_scale(a, b, affine)
    ba = fit_scale(b, a, affine)
    decision = "no_relation"
    if ab[3] <= args.residual_tolerance and ab[3] <= ba[3]:
        decision = "series_b_from_series_a"
    if ba[3] <= args.residual_tolerance and ba[3] < ab[3]:
        decision = "series_a_from_series_b"
    out = {
        "overlap_rows": int(len(a)),
        "model": args.model,
        "series_b_from_series_a": {"scale": ab[0], "intercept": ab[1], "rmse": ab[2], "relative_rmse": ab[3]},
        "series_a_from_series_b": {"scale": ba[0], "intercept": ba[1], "rmse": ba[2], "relative_rmse": ba[3]},
        "decision": decision,
        "valid": True,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
