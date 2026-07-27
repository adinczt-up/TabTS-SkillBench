#!/usr/bin/env python3
"""Fit deterministic one-step OLS trend forecasts to regular period rows."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.casefold()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path, low_memory=False)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t", low_memory=False)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError("unsupported_input_format")


def load_contract(path: Path) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8-sig"))
    required = {
        "time_column", "group_columns", "value_column", "training_start",
        "training_end_exclusive", "forecast_period", "period_frequency",
        "minimum_periods", "output_period_format",
    }
    missing = sorted(required - set(contract))
    if missing:
        raise ValueError("missing_contract_fields:" + ",".join(missing))
    if contract["period_frequency"] not in {"month", "quarter", "year"}:
        raise ValueError("invalid_period_frequency")
    if contract["output_period_format"] not in {"YYYY-MM", "YYYY-Qn", "YYYY"}:
        raise ValueError("invalid_output_period_format")
    if not isinstance(contract["group_columns"], list):
        raise ValueError("group_columns_must_be_list")
    if int(contract["minimum_periods"]) < 2:
        raise ValueError("minimum_periods_below_two")
    return contract


def period_offset(values: pd.Series, origin: pd.Timestamp, frequency: str) -> pd.Series:
    if frequency == "month":
        return (values.dt.year - origin.year) * 12 + values.dt.month - origin.month
    if frequency == "quarter":
        return (values.dt.year - origin.year) * 4 + values.dt.quarter - origin.quarter
    return values.dt.year - origin.year


def format_period(value: pd.Timestamp, format_name: str) -> str:
    if format_name == "YYYY-MM":
        return value.strftime("%Y-%m")
    if format_name == "YYYY-Qn":
        return f"{value.year}-Q{value.quarter}"
    return value.strftime("%Y")


def execute(frame: pd.DataFrame, contract: dict[str, Any], source: Path) -> dict[str, Any]:
    time_col = contract["time_column"]
    value_col = contract["value_column"]
    group_cols = contract["group_columns"]
    needed = [*group_cols, time_col, value_col]
    missing = sorted(set(needed) - set(frame.columns))
    if missing:
        raise ValueError("missing_columns:" + ",".join(missing))
    work = frame[needed].copy()
    work[time_col] = pd.to_datetime(work[time_col], errors="coerce")
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    if work[[time_col, value_col]].isna().any().any():
        raise ValueError("invalid_training_table")
    if work.duplicated([*group_cols, time_col]).any():
        raise ValueError("duplicate_group_period")

    start = pd.Timestamp(contract["training_start"])
    end = pd.Timestamp(contract["training_end_exclusive"])
    forecast_period = pd.Timestamp(contract["forecast_period"])
    work = work[(work[time_col] >= start) & (work[time_col] < end)].copy()
    if work.empty:
        raise ValueError("empty_training_window")
    frequency = contract["period_frequency"]
    work["_x"] = period_offset(work[time_col], start, frequency)
    forecast_x = int(period_offset(pd.Series([forecast_period]), start, frequency).iloc[0])
    if forecast_x <= int(work["_x"].max()):
        raise ValueError("invalid_forecast_horizon")

    keys: Any = group_cols[0] if len(group_cols) == 1 else group_cols
    grouped = work.groupby(keys, dropna=False, sort=True) if group_cols else [((), work)]
    rows = []
    omitted = []
    for key, part in grouped:
        key_tuple = key if isinstance(key, tuple) else (key,)
        identity = dict(zip(group_cols, key_tuple))
        if len(part) < int(contract["minimum_periods"]) or part["_x"].nunique() < 2:
            omitted.append({**identity, "reason": "insufficient_training_periods"})
            continue
        x = part["_x"].astype(float)
        y = part[value_col].astype(float)
        denominator = float(((x - x.mean()) ** 2).sum())
        if denominator <= 0:
            omitted.append({**identity, "reason": "zero_time_variance"})
            continue
        slope = float(((x - x.mean()) * (y - y.mean())).sum() / denominator)
        intercept = float(y.mean() - slope * x.mean())
        forecast = float(intercept + slope * forecast_x)
        residual_ss = float(((y - (intercept + slope * x)) ** 2).sum())
        if not all(math.isfinite(value) for value in (slope, intercept, forecast, residual_ss)):
            omitted.append({**identity, "reason": "nonfinite_forecast"})
            continue
        rows.append({
            **identity,
            "slope": slope,
            "intercept": intercept,
            "forecast": forecast,
            "train_period_n": int(len(part)),
            "residual_ss": residual_ss,
        })
    if not rows:
        raise ValueError("insufficient_training_periods")
    return {
        "operation": "one_step_linear_trend_forecast",
        "status": "ok",
        "input": str(source),
        "parameters": contract,
        "forecast_period": format_period(forecast_period, contract["output_period_format"]),
        "frequency": frequency,
        "forecast_offset": forecast_x,
        "result_rows": rows,
        "omitted_groups": omitted,
        "checks": {
            "unique_group_period": True,
            "forecast_after_training": True,
            "integer_training_counts": all(isinstance(row["train_period_n"], int) for row in rows),
            "finite_results": True,
        },
    }


def compute(input_path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    return execute(read_table(input_path), contract, input_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = compute(args.input, load_contract(args.contract))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
