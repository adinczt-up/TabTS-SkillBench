---
name: tableagent-grouped-period-volatility
description: Use when a validated one-row-per-group-period table must be compared by sample standard deviation across period values, with a minimum retained-period count and tie-complete extremum selection. Do not use for raw-row variance, population standard deviation, rolling volatility, quantile spread, or data that still needs period aggregation.
---

# Grouped Period Volatility

## Trigger Boundary
- Trigger for sample volatility or sample standard deviation across monthly, quarterly, or yearly group aggregates.
- Do not trigger for raw-record dispersion, quantile ranges, rolling windows, or population `ddof=0`.
- Boundary: run period-bucket-aggregation first when group-period rows are not unique.

## Input Contract
Require `input`, unique `group_column` and `period_column`, numeric `value_column`, `minimum_periods`, and `ddof=1`. Never pass an expected winning group.

## Mechanical Procedure
1. Reject duplicate group-period keys and nonnumeric values.
2. Retain only groups with at least `minimum_periods` rows.
3. Compute full-precision sample standard deviation with denominator `n-1`.
4. Select every group tied for the maximum unrounded volatility.
5. Validate by recomputing from the original period table.
6. Round only the final presentation fields.

## Output And Failures
Output all eligible volatilities, period counts, selected ties, and invariants. Duplicate periods, fewer than two periods, wrong `ddof`, insufficient coverage, or failed validation prohibit volatility conclusions.

## Structured Execution
```bash
python skills/tableagent-grouped-period-volatility/scripts/execute_analysis.py --input period_rows.parquet --group-column segment --period-column period_start --value-column raw_value --minimum-periods 4 --ddof 1 --output skill_evidence/tableagent-grouped-period-volatility.json
python skills/tableagent-grouped-period-volatility/scripts/validate_result.py --input skill_evidence/tableagent-grouped-period-volatility.json --output skill_evidence/tableagent-grouped-period-volatility.validation.json
```