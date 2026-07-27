#!/usr/bin/env python3
"""Forward-fill declared missing group-period targets without future leakage."""
from __future__ import annotations

import argparse
import json
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
        "time_column", "group_columns", "value_column", "period_frequency",
        "target_periods", "cutoff_exclusive", "maximum_gap_periods",
    }
    missing = sorted(required - set(contract))
    if missing:
        raise ValueError("missing_contract_fields:" + ",".join(missing))
    if contract["period_frequency"] not in {"month", "quarter", "year"}:
        raise ValueError("invalid_period_frequency")
    if not isinstance(contract["group_columns"], list):
        raise ValueError("group_columns_must_be_list")
    contract.setdefault("target_mode", "missing")
    contract.setdefault("top_k", 0)
    contract.setdefault("require_immediate_previous", False)
    if contract["target_mode"] not in {"missing", "holdout"}:
        raise ValueError("invalid_target_mode")
    return contract


def offset(left: pd.Timestamp, right: pd.Timestamp, frequency: str) -> int:
    months = (left.year - right.year) * 12 + left.month - right.month
    return months if frequency == "month" else months // 3 if frequency == "quarter" else left.year - right.year


def format_period(value: pd.Timestamp, frequency: str) -> str:
    if frequency == "month":
        return value.strftime("%Y-%m")
    if frequency == "quarter":
        return f"{value.year}-Q{value.quarter}"
    return value.strftime("%Y")


def shift_period(value: pd.Timestamp, frequency: str, amount: int) -> pd.Timestamp:
    period = value.to_period({"month": "M", "quarter": "Q", "year": "Y"}[frequency])
    return (period + amount).start_time


def execute(frame: pd.DataFrame, contract: dict[str, Any], source: Path) -> dict[str, Any]:
    time_col = contract["time_column"]
    value_col = contract["value_column"]
    groups = contract["group_columns"]
    needed = [*groups, time_col, value_col]
    missing = sorted(set(needed) - set(frame.columns))
    if missing:
        raise ValueError("missing_columns:" + ",".join(missing))
    work = frame[needed].copy()
    work[time_col] = pd.to_datetime(work[time_col], errors="coerce")
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    if work[time_col].isna().any():
        raise ValueError("invalid_period")
    if work.duplicated([*groups, time_col]).any():
        raise ValueError("duplicate_group_period")
    cutoff = pd.Timestamp(contract["cutoff_exclusive"])
    observed = work[(work[time_col] < cutoff) & work[value_col].notna()].copy()
    targets = contract["target_periods"]
    if not isinstance(targets, list):
        raise ValueError("target_periods_must_be_list")
    rows = []
    failures = []
    frequency = contract["period_frequency"]
    maximum = contract["maximum_gap_periods"]
    target_mode = contract["target_mode"]
    for target in targets:
        if not isinstance(target, dict) or "period" not in target:
            raise ValueError("invalid_target")
        target_period = pd.Timestamp(target["period"])
        identity = {column: target.get(column) for column in groups}
        mask = pd.Series(True, index=work.index)
        prior_mask = pd.Series(True, index=observed.index)
        for column, value in identity.items():
            mask &= work[column].eq(value)
            prior_mask &= observed[column].eq(value)
        existing = work[mask & work[time_col].eq(target_period)]
        actual = None
        if target_mode == "missing":
            if not existing.empty and existing[value_col].notna().any():
                failures.append({**identity, "target_period": format_period(target_period, frequency), "reason": "target_not_missing"})
                continue
        else:
            actual_values = existing[value_col].dropna()
            if len(actual_values) != 1:
                failures.append({**identity, "target_period": format_period(target_period, frequency), "reason": "target_not_observed"})
                continue
            actual = float(actual_values.iloc[0])
        prior = observed[prior_mask & observed[time_col].lt(target_period)].sort_values(time_col)
        if prior.empty:
            failures.append({**identity, "target_period": format_period(target_period, frequency), "reason": "no_prior_observation"})
            continue
        source_row = prior.iloc[-1]
        gap = offset(target_period, pd.Timestamp(source_row[time_col]), frequency)
        if contract["require_immediate_previous"] and gap != 1:
            failures.append({**identity, "target_period": format_period(target_period, frequency), "reason": "immediate_previous_missing", "gap_periods": gap})
            continue
        if maximum is not None and gap > int(maximum):
            failures.append({**identity, "target_period": format_period(target_period, frequency), "reason": "gap_limit_exceeded", "gap_periods": gap})
            continue
        result_row = {
            **identity,
            "target_period": format_period(target_period, frequency),
            "source_period": format_period(pd.Timestamp(source_row[time_col]), frequency),
            "imputed_value": float(source_row[value_col]),
            "gap_periods": int(gap),
        }
        if target_mode == "holdout":
            result_row.update({
                "target_month": format_period(target_period, frequency),
                "previous_month": format_period(pd.Timestamp(source_row[time_col]), frequency),
                "next_month": format_period(shift_period(target_period, frequency, 1), frequency),
                "imputed": float(source_row[value_col]),
                "actual": actual,
                "absolute_error": abs(float(source_row[value_col]) - float(actual)),
            })
        rows.append(result_row)
    holdout_rows = sorted(rows, key=lambda row: (-float(row.get("absolute_error", 0.0)), tuple(str(row.get(column, "")) for column in groups), row["target_period"]))
    if target_mode == "holdout":
        answer_fields = [*groups, "target_month", "previous_month", "next_month", "imputed", "actual", "absolute_error"]
        holdout_rows = [{field: row[field] for field in answer_fields} for row in holdout_rows]
    top_k = int(contract.get("top_k", 0))
    selected_rows = holdout_rows[:top_k] if target_mode == "holdout" and top_k > 0 else holdout_rows if target_mode == "holdout" else rows
    return {
        "operation": "forward_fill_imputation",
        "status": "ok",
        "input": str(source),
        "parameters": contract,
        "result_rows": rows,
        "selected_rows": selected_rows,
        "failures": failures,
        "checks": {
            "unique_group_period": True,
            "strictly_past_sources": all(row["gap_periods"] > 0 for row in rows),
            "no_observed_overwrite": target_mode == "holdout" or not any(item["reason"] == "target_not_missing" for item in failures),
        },
    }


def compute(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    return execute(read_table(path), contract, path)


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
