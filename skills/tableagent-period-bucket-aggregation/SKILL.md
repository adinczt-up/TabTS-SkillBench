---
name: tableagent-period-bucket-aggregation
description: Use when raw or analysis-unit time-series rows must be converted into reproducible calendar-period aggregates with explicit within-unit and period-level aggregation, minimum observations per period, and minimum retained-period coverage. Requires a validated analysis grain, parseable timestamps, grouping keys, measure semantics, aggregation functions, and a half-open window. Do not use for rolling windows, irregular episodes, direct lookup, or already validated one-row-per-group-period data.
---

# Two-Stage Period Bucket Aggregation

## Trigger Boundary

- Trigger for daily-to-monthly, event-to-monthly, monthly-to-yearly, or similar calendar aggregation followed by volatility, trend, peak, or comparison analysis.
- Trigger when storage rows are finer than the question's observation unit, such as hourly readings that must first become building-days.
- Do not trigger for rolling windows, fixed-duration episodes, or pre-aggregated unique group-period rows.
- Do not use this skill to select extrema; release the validated period table to a selection or trend skill.

### Routing Examples

- Should trigger: "Compute monthly means of each building's daily mean consumption." Reason: two explicit aggregation stages are required.
- Should not trigger: "Which supplied monthly row is largest?" Reason: periods are already materialized.
- Boundary: "Compute monthly energy." Trigger only after resolving whether energy means a daily total, daily mean, or direct monthly sum.

## Input Contract

Require these parameters; never include Gold values or expected winners:

- `time_column`, `entity_columns`, `group_columns`, and `value_column`.
- half-open `window_start` and `window_end_exclusive`.
- `source_grain` and `analysis_unit_frequency` (`row`, `day`, `week`, `month`, `quarter`, or `year`).
- `measure_semantics`: `state_or_intensity`, `additive_flow`, `event_count`, `indicator`, or `rate`.
- `within_unit_aggregate` and `period_aggregate`.
- `period_frequency`, `min_analysis_units_per_period`, and `min_periods_per_group`.

The aggregation words must come from the question or a separately validated metric contract:

- A mean/average reading remains `mean`; do not change it to `sum` because several storage rows occur per day.
- A total/volume/amount accumulated across intervals uses `sum` only when the measure is additive.
- An event count uses `sum`; an event share uses `mean` over a complete indicator universe.
- If semantics are unresolved, return `ambiguous_aggregation`; do not run both and choose the result that looks plausible.

## Mechanical Procedure

1. **Validate grain contract**
   - Input: source schema and contract.
   - Operation: verify all columns, semantics, two aggregation functions, and threshold-count unit.
   - Output: executable contract.
   - Check: `within_unit_aggregate` is never inferred from row frequency.
   - Failure: `ambiguous_aggregation` or `missing_contract_field`.
2. **Apply the time window**
   - Input: source rows and timestamps.
   - Operation: parse timestamps and filter `start <= time < end`.
   - Output: windowed source rows.
   - Check: min and max timestamps are inside the half-open window.
   - Failure: `invalid_timestamp` or `empty_window`.
3. **Materialize one row per analysis unit**
   - Input: windowed rows.
   - Operation: if frequency is not `row`, group by entity keys, group keys, and unit start; apply exactly `within_unit_aggregate` to full-precision values.
   - Output: analysis-unit table with `unit_value`.
   - Check: unit keys are unique. Record both source-row count and analysis-unit count.
   - Failure: `duplicate_analysis_unit` or `non_numeric_measure`.
4. **Materialize calendar periods**
   - Input: analysis-unit table.
   - Operation: derive calendar `period_start`, group by group keys and period, apply `period_aggregate`, and count analysis-unit rows as `analysis_unit_n`.
   - Output: one row per group-period.
   - Check: `analysis_unit_n` never counts raw storage rows unless `analysis_unit_frequency=row`.
   - Failure: `duplicate_group_period`.
5. **Apply coverage thresholds**
   - Input: period table.
   - Operation: retain periods with `analysis_unit_n >= min_analysis_units_per_period`, then groups with at least `min_periods_per_group` retained periods.
   - Output: eligible period table and exclusion counts.
   - Check: thresholds use `>=` and are applied in this order.
   - Failure: `insufficient_period_coverage`.
6. **Validate scale and provenance**
   - Input: source, unit, and period summaries.
   - Operation: recompute sampled units and periods; report median source rows per unit and the ratio between sum and mean candidates without changing the contract.
   - Output: evidence and scale diagnostics.
   - Check: any unexplained multiplier near storage frequency, such as 24 for hourly data, causes `aggregation_scale_mismatch`.
   - Failure: `aggregation_scale_mismatch` or `unreproducible_period`.

## Structured Output

```json
{
  "status": "ok",
  "window": {"start": "...", "end_exclusive": "..."},
  "grain_contract": {
    "source_grain": "hourly reading",
    "analysis_unit_frequency": "day",
    "measure_semantics": "state_or_intensity",
    "within_unit_aggregate": "mean",
    "period_frequency": "month",
    "period_aggregate": "mean"
  },
  "counts": {
    "source_row_n": 0,
    "analysis_unit_n": 0,
    "retained_period_n": 0,
    "excluded_period_n": 0,
    "excluded_group_n": 0
  },
  "period_rows": [
    {"group": "...", "period_start": "...", "raw_value": 0.0, "analysis_unit_n": 0}
  ]
}
```

## Failure States

- `ambiguous_aggregation`: no period values; report the unresolved stage and allowed interpretations.
- `invalid_timestamp`: partial output only with rejected row IDs; prohibit full-window claims.
- `duplicate_analysis_unit`: prohibit period aggregation until the first-stage keys are repaired.
- `insufficient_period_coverage`: omit affected groups; do not compute volatility, trend, or peaks for them.
- `aggregation_scale_mismatch`: prohibit final values; compare the stated measure semantics with the first-stage aggregate.
- `unreproducible_period`: return sampled evidence and stop downstream analysis.

## Deterministic Scripts

```bash
python skills/tableagent-period-bucket-aggregation/scripts/execute_analysis.py \
  --input joined_rows.parquet --contract period_contract.json \
  --output skill_evidence/tableagent-period-bucket-aggregation.json --rows-output period_rows.parquet

python skills/tableagent-period-bucket-aggregation/scripts/validate_result.py \
  --input skill_evidence/tableagent-period-bucket-aggregation.json --output skill_evidence/tableagent-period-bucket-aggregation.validation.json
```

`execute_analysis.py` accepts CSV, TSV, Excel, or Parquet input. It performs both aggregation stages exactly as declared. `validate_result.py` checks contract completeness, count invariants, unique group-period keys, thresholds, and finite values.
