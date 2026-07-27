---
name: tableagent-grouped-ols-regression
description: Use when a tabular task requests per-group OLS slope, intercept, R2, sample size, or ranking for a numeric response and predictor, optionally with an explicitly specified calendar lag. Requires prepared group-period predictor/response columns. Do not use for testing whether two series are scaled copies, discovering an unknown lag, Granger causality, multivariate regression, or causal claims.
---

# Grouped OLS Regression

## Procedure

1. Verify unique group-period rows and numeric predictor/response values.
2. If lag is zero, pair values in the same row. If lag is specified, create pairs by calendar-key join within each group; never use retained-row `shift` across a missing period.
3. Drop only pairs with missing predictor or response and retain `pair_n`.
4. Require at least three pairs and nonzero predictor variance.
5. Fit `response = intercept + slope * predictor` by OLS. Compute R2 from SSE and centered total sum of squares.
6. Preserve slope sign. Rank on the requested unrounded field, then deterministic group tie order; round only final display.
7. Emit paired rows and coefficients for recomputation. Do not make causal claims.

## Failure States

- `duplicate_group_period`, `insufficient_pairs`, `constant_predictor`, `lag_direction_unbound`.

## Command

```bash
python skills/tableagent-grouped-ols-regression/scripts/execute_analysis.py --file prepared.csv --group segment --time month --predictor event_rate --response value --calendar-lag 1 --frequency month --top-k 3
```
