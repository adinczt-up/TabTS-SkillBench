#!/usr/bin/env python3
"""Compute target-specific stationarity evidence with finite-sample guardrails."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd


def read_table(path: Path, sheet: str | None) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet or 0) if path.suffix.lower() in {'.xlsx', '.xls'} else pd.read_csv(path)


def windows(x: np.ndarray, count: int) -> tuple[list[dict], list[np.ndarray]]:
    chunks = [v for v in np.array_split(x, count) if len(v)]
    rows, start = [], 0
    for v in chunks:
        rows.append({'start': start, 'end': start + len(v) - 1, 'n': len(v), 'mean': float(v.mean()), 'variance': float(v.var(ddof=1)) if len(v) > 1 else 0.0})
        start += len(v)
    return rows, chunks


def acf(x: np.ndarray, lag: int) -> float:
    if len(x) <= lag or np.std(x[:-lag]) == 0 or np.std(x[lag:]) == 0:
        return 0.0
    return float(np.corrcoef(x[:-lag], x[lag:])[0, 1])


def stability(x: np.ndarray, count: int, alpha: float) -> dict:
    rows, chunks = windows(x, count)
    means = np.array([r['mean'] for r in rows]); variances = np.array([r['variance'] for r in rows])
    scale = max(float(np.std(x, ddof=1)), 1e-12)
    variance_ratio = float((variances.max() + 1e-12) / (variances.min() + 1e-12))
    try:
        from scipy.stats import levene
        variance_p = float(levene(*chunks, center='median').pvalue)
    except Exception:
        variance_p = None
    mean_span_std = float((means.max() - means.min()) / scale)
    idx = np.arange(len(x), dtype=float)
    end_to_end_trend_std = float(np.polyfit(idx, x, 1)[0] * max(len(x) - 1, 1) / scale)
    max_lag = min(10, max(1, min(map(len, chunks)) // 8))
    acf_spreads = []
    for lag in range(1, max_lag + 1):
        values = [acf(chunk, lag) for chunk in chunks]
        acf_spreads.append({'lag': lag, 'values': values, 'spread': float(max(values) - min(values))})
    max_acf_spread = max((row['spread'] for row in acf_spreads), default=0.0)
    mean_stable = mean_span_std <= 0.75 and abs(end_to_end_trend_std) <= 0.75
    variance_stable = variance_ratio <= 1.5 or variance_p is None or variance_p >= alpha
    covariance_stable = mean_stable and variance_stable and max_acf_spread <= 0.35
    return {'window_summaries': rows, 'mean_span_std': mean_span_std, 'end_to_end_trend_std': end_to_end_trend_std, 'variance_ratio': variance_ratio, 'brown_forsythe_p': variance_p, 'acf_window_spreads': acf_spreads, 'max_acf_spread': max_acf_spread, 'mean_stable': mean_stable, 'variance_stable': variance_stable, 'covariance_stable': covariance_stable}


def seasonal_stability(x: np.ndarray, period: int) -> dict:
    cycles = len(x) // period
    if period < 2 or cycles < 4:
        return {'failure_state': 'seasonal_period_or_cycles_insufficient', 'period': period, 'cycles': cycles}
    matrix = x[:cycles * period].reshape(cycles, period)
    means = matrix.mean(axis=1); scales = matrix.std(axis=1, ddof=1)
    global_scale = max(float(np.std(x, ddof=1)), 1e-12)
    profile = np.median(matrix, axis=0)
    correlations = []
    for row in matrix:
        correlations.append(float(np.corrcoef(row, profile)[0, 1]) if np.std(row) and np.std(profile) else 1.0)
    mean_span_std = float((means.max() - means.min()) / global_scale)
    scale_ratio = float((scales.max() + 1e-12) / (scales.min() + 1e-12))
    median_profile_correlation = float(np.median(correlations))
    stable = mean_span_std <= 0.75 and scale_ratio <= 1.5 and median_profile_correlation >= 0.7
    return {'period': period, 'cycles': cycles, 'cycle_means': means.tolist(), 'cycle_scales': scales.tolist(), 'mean_span_std': mean_span_std, 'scale_ratio': scale_ratio, 'profile_correlations': correlations, 'median_profile_correlation': median_profile_correlation, 'seasonal_stable': stable}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--file', required=True, type=Path); p.add_argument('--sheet'); p.add_argument('--series', required=True)
    p.add_argument('--target', choices=['mean','variance','covariance','differencing','seasonal','anomaly'], default='covariance')
    p.add_argument('--windows', type=int, default=4); p.add_argument('--seasonal-period', type=int); p.add_argument('--alpha', type=float, default=0.01)
    a = p.parse_args(); frame = read_table(a.file, a.sheet)
    x = pd.to_numeric(frame[a.series], errors='coerce').dropna().to_numpy(float)
    if len(x) < max(32, a.windows * 8):
        print(json.dumps({'failure_state':'too_few_points','n':len(x)}, indent=2)); return 1
    level = stability(x, a.windows, a.alpha); result = {'target':a.target,'n':len(x),'alpha':a.alpha,'level':level,'failure_state':None}
    if a.target == 'mean': decision = 'stable' if level['mean_stable'] else 'unstable'
    elif a.target == 'variance': decision = 'stable' if level['variance_stable'] else 'unstable'
    elif a.target == 'covariance': decision = 'stationary' if level['covariance_stable'] else 'nonstationary'
    elif a.target == 'differencing':
        diff_windows = max(a.windows, 8) if len(x) >= 256 else a.windows
        diff = stability(np.diff(x), diff_windows, a.alpha); result['difference_windows'] = diff_windows; result['difference'] = diff; decision = 'stationary_after_differencing' if diff['covariance_stable'] else 'not_stationary_after_differencing'
    elif a.target == 'seasonal':
        if not a.seasonal_period:
            result['failure_state']='seasonal_period_missing'; decision='undetermined'
        else:
            season = seasonal_stability(x, a.seasonal_period); result['seasonal']=season
            if season.get('failure_state'): result['failure_state']=season['failure_state']; decision='undetermined'
            else: decision='seasonally_stationary' if season['seasonal_stable'] else 'not_seasonally_stationary'
    else:
        failures = sum([not level['mean_stable'], not level['variance_stable'], level['max_acf_spread'] > 0.35])
        decision = 'nonstationary_anomaly' if failures >= 2 else 'stationary_anomaly'
    result['decision']=decision; print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if not result['failure_state'] else 1
if __name__ == '__main__': raise SystemExit(main())