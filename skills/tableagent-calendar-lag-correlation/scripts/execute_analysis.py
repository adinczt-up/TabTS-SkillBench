#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def read(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path, low_memory=False)


def emit(value: dict, path: Path | None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True, type=Path)
    p.add_argument("--group", required=True)
    p.add_argument("--time", required=True)
    p.add_argument("--response", required=True)
    p.add_argument("--predictor", required=True)
    p.add_argument("--lags", required=True)
    p.add_argument("--frequency", choices=["day", "week", "month", "quarter", "year"], required=True)
    p.add_argument("--min-pairs", type=int, default=3)
    p.add_argument("--selection-round", type=int, default=6)
    p.add_argument("--top-k", type=int, default=3)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    lags = sorted({int(value) for value in a.lags.split(",") if value.strip()})
    if not lags or any(value < 0 for value in lags):
        raise ValueError("lags must be nonnegative integers")
    d = read(a.file)[[a.group, a.time, a.response, a.predictor]].copy()
    d[a.time] = pd.to_datetime(d[a.time], errors="coerce")
    d[a.response] = pd.to_numeric(d[a.response], errors="coerce")
    d[a.predictor] = pd.to_numeric(d[a.predictor], errors="coerce")
    d = d.dropna(subset=[a.group, a.time])
    freq = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}[a.frequency]
    d["period"] = d[a.time].dt.to_period(freq)
    if d.duplicated([a.group, "period"]).any():
        emit({"status": "failed", "failure_state": "duplicate_group_period"}, a.output)
        return 1
    rows, unresolved = [], []
    for group, frame in d.groupby(a.group, dropna=False, sort=True):
        response = frame[["period", a.response]].rename(columns={a.response: "response"})
        for lag in lags:
            predictor = frame[["period", a.predictor]].rename(columns={a.predictor: "predictor"}).copy()
            predictor["period"] = predictor["period"] + lag
            pairs = response.merge(predictor, on="period", how="inner").dropna()
            if len(pairs) < a.min_pairs:
                unresolved.append({"group": str(group), "lag": lag, "reason": "insufficient_pairs", "pair_n": len(pairs)})
                continue
            x, y = pairs["predictor"].to_numpy(float), pairs["response"].to_numpy(float)
            if np.var(x) <= 1e-15 or np.var(y) <= 1e-15:
                unresolved.append({"group": str(group), "lag": lag, "reason": "constant_series", "pair_n": len(pairs)})
                continue
            corr = float(np.corrcoef(x, y)[0, 1])
            rows.append({"segment": str(group), "lag_periods": lag, "correlation": corr, "selection_correlation": round(corr, a.selection_round), "pair_n": len(pairs)})
    best = []
    for group in sorted({row["segment"] for row in rows}):
        candidates = [row for row in rows if row["segment"] == group]
        best.append(min(candidates, key=lambda row: (-abs(row["selection_correlation"]), row["lag_periods"])))
    best.sort(key=lambda row: (-abs(row["selection_correlation"]), row["segment"]))
    result = {"status": "ok" if best else "failed", "failure_state": None if best else "no_valid_correlations", "parameters": {"lags": lags, "frequency": a.frequency, "min_pairs": a.min_pairs, "selection_round": a.selection_round}, "group_lag_results": rows, "selected_rows": best[:a.top_k], "unresolved": unresolved}
    emit(result, a.output)
    return 0 if best else 1


if __name__ == "__main__":
    raise SystemExit(main())
