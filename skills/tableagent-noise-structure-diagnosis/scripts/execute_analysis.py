#!/usr/bin/env python3
"""Produce deterministic residual-noise evidence for a numeric table series."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def read_table(path: Path, sheet: str | None) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet or 0) if path.suffix.lower() in {".xlsx", ".xls"} else pd.read_csv(path)


def autocorrelation(x: np.ndarray, lag: int) -> float:
    if lag >= len(x):
        return float("nan")
    a, b = x[:-lag], x[lag:]
    return float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else 0.0


def robust_scale(x: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--sheet")
    parser.add_argument("--series", required=True)
    parser.add_argument(
        "--target",
        choices=["raw_white_noise", "presence", "dependence", "noise_type", "variance_form"],
        required=True,
    )
    parser.add_argument(
        "--signal-model",
        choices=["auto", "raw", "constant", "linear", "rolling_median"],
        default="auto",
    )
    parser.add_argument("--window", type=int, default=31)
    parser.add_argument("--relative-noise-threshold", type=float, default=0.02)
    parser.add_argument("--max-lag", type=int, default=10)
    args = parser.parse_args()
    if args.window < 3 or args.relative_noise_threshold < 0 or args.max_lag < 1:
        raise ValueError("invalid window, threshold, or lag")
    frame = read_table(args.file, args.sheet)
    x = pd.to_numeric(frame[args.series], errors="coerce").dropna().to_numpy(float)
    if len(x) < max(30, args.window):
        print(json.dumps({"status": "failed", "failure_state": "too_few_points", "n": len(x)}, indent=2))
        return 1
    index = np.arange(len(x), dtype=float)
    linear_fitted = np.polyval(np.polyfit(index, x, 1), index)
    rolling_window = min(args.window, 9) if args.target == "variance_form" else args.window
    rolling_fitted = pd.Series(x).rolling(rolling_window, center=True, min_periods=1).median().to_numpy()
    constant_fitted = np.full_like(x, np.median(x))
    resolved_model = args.signal_model
    if args.target == "raw_white_noise":
        resolved_model = "raw"
    elif resolved_model == "auto":
        candidate_scales = {
            "constant": robust_scale(x - constant_fitted),
            "linear": robust_scale(x - linear_fitted),
            "rolling_median": robust_scale(x - rolling_fitted),
        }
        if args.target == "variance_form":
            resolved_model = "rolling_median"
        else:
            best_scale = min(candidate_scales.values())
            if candidate_scales["constant"] <= best_scale * 1.10:
                resolved_model = "constant"
            elif candidate_scales["linear"] <= best_scale * 1.10:
                resolved_model = "linear"
            else:
                resolved_model = "rolling_median"

    if resolved_model in {"raw", "constant"}:
        fitted = np.full_like(x, np.median(x))
    elif resolved_model == "linear":
        fitted = linear_fitted
    else:
        fitted = rolling_fitted
    residual = x - fitted
    residual_scale = robust_scale(residual)
    signal_scale = float(np.quantile(fitted, 0.95) - np.quantile(fitted, 0.05))
    data_scale = float(np.quantile(x, 0.95) - np.quantile(x, 0.05))
    level_scale = float(np.median(np.abs(fitted)))
    scale_reference = max(signal_scale, data_scale, level_scale, 1e-12)
    relative_scale = residual_scale / scale_reference
    presence = "none" if relative_scale <= args.relative_noise_threshold else "meaningful"
    acf = [autocorrelation(residual, lag) for lag in range(1, min(args.max_lag, len(residual) - 1) + 1)]
    bound = 1.96 / np.sqrt(len(residual))
    lag_count = len(acf)
    q_stat = float(
        len(residual) * (len(residual) + 2)
        * sum((rho * rho) / (len(residual) - lag) for lag, rho in enumerate(acf, start=1))
    )
    try:
        from scipy.stats import chi2

        portmanteau_pvalue = float(chi2.sf(q_stat, lag_count))
        dependence = "white" if portmanteau_pvalue >= 0.05 else "autocorrelated"
    except ImportError:
        portmanteau_pvalue = None
        dependence = "white" if max(map(abs, acf), default=0.0) <= 2.8 / np.sqrt(len(residual)) else "autocorrelated"
    centered = residual - np.mean(residual)
    standard = float(np.std(centered, ddof=1))
    skewness = float(np.mean((centered / standard) ** 3)) if standard > 0 else 0.0
    excess_kurtosis = float(np.mean((centered / standard) ** 4) - 3.0) if standard > 0 else 0.0
    bins = pd.qcut(np.abs(fitted), q=4, duplicates="drop")
    spreads = pd.DataFrame({"bin": bins, "residual": residual}).groupby("bin", observed=True)["residual"].std().dropna().tolist()
    variance_form = "undetermined"
    spread_ratio = None
    spread_trend = None
    if len(spreads) >= 3 and min(spreads) > 0:
        spread_ratio = max(spreads) / min(spreads)
        spread_trend = float(np.corrcoef(np.arange(len(spreads)), spreads)[0, 1])
        variance_form = (
            "multiplicative"
            if spread_ratio >= 1.5 and spread_trend >= 0.8
            else "additive"
        )
    noise_type = "undetermined"
    if presence == "none":
        noise_type = "no_significant_noise"
    elif dependence == "white" and abs(skewness) <= 0.5 and abs(excess_kurtosis) <= 1.0:
        noise_type = "gaussian_white_noise"
    elif dependence == "autocorrelated" and acf and acf[0] > 0:
        noise_type = "red_noise"
    decision = {
        "raw_white_noise": "yes" if dependence == "white" else "no",
        "presence": presence,
        "dependence": dependence,
        "noise_type": noise_type,
        "variance_form": variance_form,
    }[args.target]
    failure = None
    if presence == "none" and args.target in {"dependence", "variance_form"}:
        failure = "residuals_negligible"
    elif args.target == "variance_form" and variance_form == "undetermined":
        failure = "insufficient_level_bins"
    elif args.target == "noise_type" and noise_type == "undetermined":
        failure = "conflicting_diagnostics"
    output = {
        "status": "failed" if failure else "ok",
        "target": args.target,
        "requested_signal_model": args.signal_model,
        "signal_model": resolved_model,
        "rolling_window": rolling_window if resolved_model == "rolling_median" else None,
        "analysis_series": "raw_centered" if args.target == "raw_white_noise" else "residual",
        "n": len(x),
        "residual_scale": residual_scale,
        "scale_reference": scale_reference,
        "relative_residual_scale": relative_scale,
        "relative_noise_threshold": args.relative_noise_threshold,
        "noise_presence": presence,
        "acf": acf,
        "acf_significance_bound": float(bound),
        "portmanteau_q": q_stat,
        "portmanteau_pvalue": portmanteau_pvalue,
        "dependence": dependence,
        "skewness": skewness,
        "excess_kurtosis": excess_kurtosis,
        "residual_spread_by_signal_bin": spreads,
        "signal_bin_basis": "absolute_fitted_level",
        "residual_spread_ratio": spread_ratio,
        "residual_spread_trend": spread_trend,
        "variance_form": variance_form,
        "noise_type": noise_type,
        "decision": decision if not failure else "undetermined",
        "failure_state": failure,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
