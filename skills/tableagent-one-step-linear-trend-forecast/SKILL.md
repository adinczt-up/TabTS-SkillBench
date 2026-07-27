---
name: tableagent-one-step-linear-trend-forecast
description: Use when a regular tabular time series asks for a one-period-ahead forecast obtained by fitting an ordinary least-squares line to an explicit historical window, separately by group if requested. Requires one validated value per group-period, a regular calendar frequency, at least two training periods, and an explicit forecast period. Do not use for multi-step recursive forecasts, nonlinear models, model selection, irregular timestamps, causal regression, or data that still needs aggregation.
---

# One-Step Linear Trend Forecast

## Trigger Boundary

- Trigger for a next-month, next-quarter, or next-year forecast explicitly defined as linear extrapolation from period values.
- Trigger only after the input is one row per group-period at the question's analysis grain.
- Do not trigger for a descriptive trend slope without a forecast, rolling backtests, seasonal-naive forecasts, or predictor-response regression.
- Boundary: if the question asks both for a slope and the next value, this skill owns both because the forecast contract determines the time index.

## Input Contract

Provide a JSON contract containing:

- `time_column`, `group_columns`, and `value_column`;
- `training_start`, `training_end_exclusive`, and `forecast_period`;
- `period_frequency`: `month`, `quarter`, or `year`;
- `minimum_periods`;
- `output_period_format`: `YYYY-MM`, `YYYY-Qn`, or `YYYY`.

Entity names, dates, and thresholds are runtime parameters. Never include expected coefficients or forecasts.

## Mechanical Procedure

1. Input: analysis-ready rows and contract. Operation: parse periods and values, then filter the half-open training window. Output: training rows. Check: keys are unique and values finite. Failure: `invalid_training_table`.
2. Input: training periods. Operation: map calendar periods to integer offsets from `training_start`. Output: `(group, x, y)` rows. Check: offsets are unique and the forecast offset is strictly after every training offset. Failure: `invalid_forecast_horizon`.
3. Input: indexed rows. Operation: retain groups with at least `minimum_periods` and two distinct offsets. Output: eligible groups. Failure: `insufficient_training_periods`.
4. Input: each eligible group. Operation: fit `y = intercept + slope*x` by closed-form OLS using unrounded values. Output: slope, intercept, residual sum of squares, and training count. Check: positive time variance and finite coefficients. Failure: `zero_time_variance`.
5. Input: coefficients and forecast offset. Operation: compute exactly one direct forecast. Output: raw forecast. Check: no recursive or seasonal substitution occurred. Failure: `nonfinite_forecast`.
6. Input: structured result. Operation: run the validator, then render the period using `output_period_format`. Output: final rows. Check: `train_period_n` is an integer count, not a list of periods.

## Output Contract

```json
{
  "status": "ok",
  "forecast_period": "YYYY-MM",
  "frequency": "month",
  "result_rows": [
    {
      "group": "...",
      "slope": 0.0,
      "intercept": 0.0,
      "forecast": 0.0,
      "train_period_n": 0,
      "residual_ss": 0.0
    }
  ]
}
```

## Failure States

- `invalid_training_table`: no forecast; report missing, duplicate, or nonnumeric fields.
- `invalid_forecast_horizon`: no forecast; report the last training period and requested period.
- `insufficient_training_periods`: omit only affected groups; partial output is allowed and must list omissions.
- `zero_time_variance` or `nonfinite_forecast`: prohibit a numeric forecast for the affected group.

## Structured Execution

```bash
python skills/tableagent-one-step-linear-trend-forecast/scripts/execute_analysis.py --input period_rows.parquet --contract forecast_contract.json --output skill_evidence/tableagent-one-step-linear-trend-forecast.json
python skills/tableagent-one-step-linear-trend-forecast/scripts/validate_result.py --input skill_evidence/tableagent-one-step-linear-trend-forecast.json --output skill_evidence/tableagent-one-step-linear-trend-forecast.validation.json
```
