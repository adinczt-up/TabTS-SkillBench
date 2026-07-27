#!/usr/bin/env python3
"""Execute a declared two-stage calendar aggregation."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


AGGREGATES = {"mean", "sum", "min", "max", "count"}
FREQUENCIES = {
    "day": "D", "week": "W-MON", "month": "MS", "quarter": "QS", "year": "YS"
}


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.casefold()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"unsupported input format: {path.suffix}")


def load_contract(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    required = {
        "time_column", "entity_columns", "group_columns", "value_column",
        "window_start", "window_end_exclusive", "source_grain",
        "analysis_unit_frequency", "measure_semantics", "within_unit_aggregate",
        "period_frequency", "period_aggregate", "min_analysis_units_per_period",
        "min_periods_per_group",
    }
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(f"missing contract fields: {missing}")
    if data["within_unit_aggregate"] not in AGGREGATES:
        raise ValueError("invalid within_unit_aggregate")
    if data["period_aggregate"] not in AGGREGATES:
        raise ValueError("invalid period_aggregate")
    if data["analysis_unit_frequency"] != "row" and data["analysis_unit_frequency"] not in FREQUENCIES:
        raise ValueError("invalid analysis_unit_frequency")
    if data["period_frequency"] not in FREQUENCIES:
        raise ValueError("invalid period_frequency")
    return data


def floor_period(series: pd.Series, frequency: str) -> pd.Series:
    if frequency == "week":
        return series.dt.to_period("W-SUN").dt.start_time
    code = {"day": "D", "month": "M", "quarter": "Q", "year": "Y"}[frequency]
    return series.dt.to_period(code).dt.start_time


def aggregate(frame: pd.core.groupby.DataFrameGroupBy, column: str, operation: str) -> pd.Series:
    if operation == "count":
        return frame[column].count()
    return frame[column].agg(operation)


def execute(frame: pd.DataFrame, c: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    needed = {c["time_column"], c["value_column"], *c["entity_columns"], *c["group_columns"]}
    missing = sorted(needed - set(frame.columns))
    if missing:
        raise ValueError(f"input columns missing: {missing}")
    work = frame[list(needed)].copy()
    work[c["time_column"]] = pd.to_datetime(work[c["time_column"]], errors="coerce")
    if work[c["time_column"]].isna().any():
        raise ValueError("invalid_timestamp")
    work[c["value_column"]] = pd.to_numeric(work[c["value_column"]], errors="coerce")
    if work[c["value_column"]].isna().any():
        raise ValueError("non_numeric_measure")
    start = pd.Timestamp(c["window_start"])
    end = pd.Timestamp(c["window_end_exclusive"])
    work = work[(work[c["time_column"]] >= start) & (work[c["time_column"]] < end)].copy()
    if work.empty:
        raise ValueError("empty_window")
    source_n = len(work)

    if c["analysis_unit_frequency"] == "row":
        units = work.rename(columns={c["value_column"]: "unit_value"})
        units["unit_start"] = units[c["time_column"]]
    else:
        work["unit_start"] = floor_period(work[c["time_column"]], c["analysis_unit_frequency"])
        unit_keys = list(dict.fromkeys([*c["group_columns"], *c["entity_columns"], "unit_start"]))
        grouped = work.groupby(unit_keys, dropna=False, sort=False)
        values = aggregate(grouped, c["value_column"], c["within_unit_aggregate"])
        units = values.rename("unit_value").reset_index()
        if units.duplicated(unit_keys).any():
            raise ValueError("duplicate_analysis_unit")

    units["period_start"] = floor_period(pd.to_datetime(units["unit_start"]), c["period_frequency"])
    period_keys = [*c["group_columns"], "period_start"]
    period_grouped = units.groupby(period_keys, dropna=False, sort=False)
    period_values = aggregate(period_grouped, "unit_value", c["period_aggregate"])
    periods = period_values.rename("raw_value").reset_index()
    periods["analysis_unit_n"] = period_grouped.size().to_numpy()
    minimum = int(c["min_analysis_units_per_period"])
    before_period_n = len(periods)
    periods = periods[periods["analysis_unit_n"] >= minimum].copy()
    period_counts = periods.groupby(c["group_columns"], dropna=False).size().rename("retained_n")
    eligible = period_counts[period_counts >= int(c["min_periods_per_group"])].reset_index()[c["group_columns"]]
    before_group_n = len(period_counts)
    if c["group_columns"]:
        periods = periods.merge(eligible, on=c["group_columns"], how="inner")
    elif len(periods) < int(c["min_periods_per_group"]):
        periods = periods.iloc[0:0]
    if periods.empty:
        raise ValueError("insufficient_period_coverage")
    periods = periods.sort_values(period_keys).reset_index(drop=True)
    if periods.duplicated(period_keys).any():
        raise ValueError("duplicate_group_period")
    if not periods["raw_value"].map(lambda value: math.isfinite(float(value))).all():
        raise ValueError("nonfinite_period_value")

    rows = []
    for row in periods.to_dict(orient="records"):
        row["period_start"] = pd.Timestamp(row["period_start"]).isoformat()
        rows.append(row)
    result = {
        "status": "ok",
        "window": {"start": str(start), "end_exclusive": str(end)},
        "grain_contract": {
            key: c[key] for key in (
                "source_grain", "analysis_unit_frequency", "measure_semantics",
                "within_unit_aggregate", "period_frequency", "period_aggregate"
            )
        },
        "group_columns": c["group_columns"],
        "thresholds": {
            "min_analysis_units_per_period": minimum,
            "min_periods_per_group": int(c["min_periods_per_group"]),
        },
        "counts": {
            "source_row_n": int(source_n),
            "analysis_unit_n": int(len(units)),
            "retained_period_n": int(len(periods)),
            "excluded_period_n": int(before_period_n - len(periods)),
            "excluded_group_n": int(before_group_n - len(eligible)),
        },
        "period_rows": rows,
    }
    return result, periods


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows-output", type=Path)
    args = parser.parse_args()
    result, periods = execute(read_table(args.input), load_contract(args.contract))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.rows_output:
        periods.to_parquet(args.rows_output, index=False)
    print(json.dumps({"status": "ok", "period_rows": len(periods)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
