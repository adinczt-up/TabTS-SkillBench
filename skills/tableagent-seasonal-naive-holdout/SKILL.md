---
name: tableagent-seasonal-naive-holdout
description: Use when a grouped regular time series asks to forecast an observed target period using the value from an explicit seasonal calendar offset, then evaluate and rank holdout errors. Requires one prepared row per group-period, a target, frequency, and seasonal lag. Do not use for previous-retained-row lookup, learned seasonal models, multi-step recursive forecasting, or targets without the exact reference period.
---

# Seasonal Naive Holdout

1. Reject duplicate group-period rows and preserve the target actual only for evaluation.
2. Compute `reference_period = target_period - seasonal_lag` in calendar periods.
3. Require the exact reference period for each group; never substitute a nearby retained row.
4. Set `forecast=reference_value` and compute unrounded absolute error.
5. Rank in the requested direction with deterministic group ties. Answer only from evidence rows.

```bash
python skills/tableagent-seasonal-naive-holdout/scripts/execute_analysis.py --file prepared.parquet --group segment --time month --value metric --frequency month --target 2017-08 --seasonal-lag 12 --top-k 3 --output skill_evidence/tableagent-seasonal-naive-holdout.json
```

Failure states: `duplicate_group_period`, `target_not_observed`, `reference_period_missing`, `no_valid_groups`.
