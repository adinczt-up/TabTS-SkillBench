#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path, low_memory=False)


def fit_predict(train: list[tuple[pd.Period, float]], targets: list[pd.Period], model: str) -> list[float]:
    if len(train) < 2:
        raise ValueError("insufficient_training")
    values = np.asarray([value for _, value in train], dtype=float)
    if model == "historical_mean":
        return [float(values.mean()) for _ in targets]
    x = np.asarray([period.ordinal for period, _ in train], dtype=float)
    slope, intercept = np.polyfit(x, values, 1)
    return [float(slope * target.ordinal + intercept) for target in targets]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--group", required=True)
    parser.add_argument("--time", required=True)
    parser.add_argument("--value", required=True)
    parser.add_argument("--frequency", choices=["month", "quarter", "year"], required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--validation-periods", type=int, required=True)
    parser.add_argument("--validation-mode", choices=["fixed_origin", "rolling_origin"], required=True)
    parser.add_argument("--models", default="historical_mean,linear_trend")
    parser.add_argument("--tie-order", default="historical_mean,linear_trend")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    models = [item.strip() for item in args.models.split(",") if item.strip()]
    tie_order = [item.strip() for item in args.tie_order.split(",") if item.strip()]
    allowed = {"historical_mean", "linear_trend"}
    if not models or not set(models) <= allowed or set(models) != set(tie_order):
        raise ValueError("invalid_model_or_tie_order")

    data = read_table(args.file)[[args.group, args.time, args.value]].copy()
    data[args.time] = pd.to_datetime(data[args.time], errors="coerce")
    data[args.value] = pd.to_numeric(data[args.value], errors="coerce")
    data = data.dropna()
    frequency = {"month": "M", "quarter": "Q", "year": "Y"}[args.frequency]
    data["period"] = data[args.time].dt.to_period(frequency)
    if data.duplicated([args.group, "period"]).any():
        result = {"status": "failed", "failure_state": "duplicate_group_period"}
        code = 1
    else:
        target = pd.Period(args.target, freq=frequency)
        validation = [target - index for index in range(args.validation_periods, 0, -1)]
        rows: list[dict[str, object]] = []
        unresolved: list[dict[str, object]] = []
        for group, frame in data.groupby(args.group, dropna=False, sort=True):
            values = {period: float(value) for period, value in frame[["period", args.value]].itertuples(index=False, name=None)}
            if target not in values:
                unresolved.append({"segment": str(group), "reason": "target_not_observed"})
                continue
            if not all(period in values for period in validation):
                unresolved.append({"segment": str(group), "reason": "incomplete_validation_block"})
                continue
            errors = {model: [] for model in models}
            try:
                if args.validation_mode == "fixed_origin":
                    fixed_train = sorted((period, value) for period, value in values.items() if period < validation[0])
                    for model in models:
                        predictions = fit_predict(fixed_train, validation, model)
                        errors[model] = [abs(prediction - values[period]) for prediction, period in zip(predictions, validation)]
                else:
                    for origin in validation:
                        train = sorted((period, value) for period, value in values.items() if period < origin)
                        for model in models:
                            prediction = fit_predict(train, [origin], model)[0]
                            errors[model].append(abs(prediction - values[origin]))
            except ValueError:
                unresolved.append({"segment": str(group), "reason": "insufficient_training"})
                continue

            candidate_mae = {model: float(np.mean(errors[model])) for model in models}
            winner = min(models, key=lambda model: (candidate_mae[model], tie_order.index(model)))
            if args.validation_mode == "fixed_origin":
                forecast_train = sorted((period, value) for period, value in values.items() if period < validation[0])
            else:
                forecast_train = sorted((period, value) for period, value in values.items() if period < target)
            forecast = fit_predict(forecast_train, [target], winner)[0]
            actual = values[target]
            rows.append({
                "segment": str(group),
                "target_month": str(target),
                "selected_model": winner,
                "validation_mae": candidate_mae[winner],
                "forecast": forecast,
                "actual": actual,
                "absolute_error": abs(forecast - actual),
                "validation_months": len(validation),
                "candidate_mae": candidate_mae,
            })
        rows.sort(key=lambda row: (float(row["validation_mae"]), str(row["segment"])))
        selected = [{key: value for key, value in row.items() if key != "candidate_mae"} for row in rows[: args.top_k]]
        result = {
            "status": "ok" if rows else "failed",
            "failure_state": None if rows else "no_valid_groups",
            "input": str(args.file),
            "parameters": {
                "group": args.group,
                "time": args.time,
                "value": args.value,
                "frequency": args.frequency,
                "target": str(target),
                "validation_periods": args.validation_periods,
                "validation_mode": args.validation_mode,
                "models": models,
                "tie_order": tie_order,
                "top_k": args.top_k,
            },
            "selected_rows": selected,
            "all_rows": rows,
            "unresolved": unresolved,
            "validation": {
                "target_excluded_from_training": True,
                "validation_excluded_from_fixed_training": True,
                "selected_count": len(selected),
            },
        }
        code = 0 if rows else 1

    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
