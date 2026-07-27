---
name: tableagent-grouped-linear-trend
description: Use when a tabular time-series task asks for a signed ordinary-least-squares trend slope separately by group over equally defined period aggregates, with enough retained periods and an explicit period index origin. Requires one unique numeric observation per group-period. Do not use for nonlinear forecasting, rolling regression, causal claims, raw irregular timestamps, or data that still needs period aggregation.
---

# Grouped Linear Trend

## Trigger Boundary

- Trigger for OLS slope of monthly, quarterly, or yearly group aggregates and comparisons of signed or absolute slopes.
- Do not trigger for prediction, nonlinear trend, Granger causality, or unbucketed irregular observations.
- Borderline: prepare period means with period-bucket aggregation before using this skill.

## Input Contract

Require unique `group`, `period_start`, full-precision `value`, `origin_period`, `minimum_periods`, and the requested selection rule. Never include Gold slopes or expected winning groups.

## Mechanical Procedure

1. Input: period rows. Operation: verify one row per group-period, numeric finite values, and common calendar frequency. Output: validated rows. Check: no duplicate keys or mixed frequencies. Failure: `invalid_period_table`.
2. Input: validated rows and origin. Operation: compute integer calendar offsets `x`; January to February is one month regardless of day count. Output: `(group, x, y)` rows. Check: one-to-one mapping between period and x. Failure: `invalid_origin`.
3. Input: indexed rows. Operation: retain groups with at least `minimum_periods` and at least two distinct x values. Output: eligible groups. Failure: `insufficient_periods`.
4. Input: eligible group rows. Operation: compute `slope = sum((x-xbar)(y-ybar))/sum((x-xbar)^2)` and intercept from unrounded y. Output: raw coefficients, period count, and residual sum of squares. Check: denominator is positive. Failure: `zero_time_variance`.
5. Input: raw slopes. Operation: apply signed or absolute comparison exactly as requested; select before rounding and preserve all ties. Output: selected groups and evidence. Failure: `selection_rule_missing`.

## Output Contract

```json
{
  "status": "ok",
  "origin_period": "...",
  "frequency": "month",
  "groups": [{"group": "...", "raw_slope": 0.0, "intercept": 0.0, "period_n": 0, "residual_ss": 0.0}],
  "selected_groups": ["..."]
}
```

## Validation And Failure States

- Recompute each reported slope from the stored `(x,y)` evidence.
- Assert selection uses raw slopes and the requested sign/absolute rule.
- `insufficient_periods`: omit that group; do not estimate from fewer periods.
- `zero_time_variance`: no slope may be reported.
- `nonfinite_coefficient`: prohibit trend conclusions and return offending groups.

## Required Structured Execution
```bash
python skills/tableagent-grouped-linear-trend/scripts/execute_analysis.py --input period_rows.parquet --group-column segment --period-column period_start --value-column raw_value --origin-period 2020-01-01 --minimum-periods 4 --selection max_abs --output skill_evidence/tableagent-grouped-linear-trend.json
python skills/tableagent-grouped-linear-trend/scripts/validate_result.py --input skill_evidence/tableagent-grouped-linear-trend.json --output skill_evidence/tableagent-grouped-linear-trend.validation.json
```
Use only validated `selected_rows`; the validator reloads the period table and recomputes every coefficient.