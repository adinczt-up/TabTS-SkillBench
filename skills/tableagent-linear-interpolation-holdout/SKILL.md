---
name: tableagent-linear-interpolation-holdout
description: Use when a grouped regular time series asks to hold out an observed target period, interpolate it from the immediately adjacent calendar periods, and compare the imputation with the held-out value. Requires one prepared row per group-period and an explicit target/frequency. Do not use for forward fill, seasonal imputation, irregular interpolation, extrapolation, or missing targets without both adjacent periods.
---

# Linear Interpolation Holdout

1. Verify one numeric row per group-calendar period.
2. Preserve the observed target as `actual`, then exclude it from interpolation inputs.
3. Locate exactly `target-1` and `target+1` calendar periods; adjacent retained rows are insufficient.
4. Compute `imputed=(previous+next)/2` and `absolute_error=abs(imputed-actual)` without rounding.
5. Rank on unrounded error using the stated direction and deterministic group tie order.
6. Answer only from the structured selected rows.

```bash
python skills/tableagent-linear-interpolation-holdout/scripts/execute_analysis.py --file prepared.parquet --group segment --time month --value metric --frequency month --target 2015-11 --top-k 3 --output skill_evidence/tableagent-linear-interpolation-holdout.json
```

Failure states: `duplicate_group_period`, `target_not_observed`, `missing_adjacent_period`, `no_valid_groups`.
