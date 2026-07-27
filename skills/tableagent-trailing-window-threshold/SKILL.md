---
name: tableagent-trailing-window-threshold
description: Use when a grouped regular time series asks for trailing-window means or sums, a threshold estimated from a declared reference period, and ranked exceedances. Requires one prepared row per group-period, a fixed calendar window, threshold rule, and cutoff. Do not use for centered windows, anomaly episodes, change points, arbitrary rolling rows, or thresholds fitted using evaluation periods.
---

# Trailing Window Threshold

1. Reject duplicate group-period rows and materialize calendar periods.
2. Fit the threshold only from periods strictly before the declared cutoff.
3. Form a trailing window only when all adjacent calendar periods are present.
4. Compute the raw rolling statistic and `excess=statistic-threshold` without rounding.
5. Keep positive exceedances, rank on raw excess, and apply deterministic group/period ties.
6. Answer only from `selected_rows`.

```bash
python skills/tableagent-trailing-window-threshold/scripts/execute_analysis.py --file prepared.parquet --group segment --time month --value metric --frequency month --window 3 --threshold-cutoff 2015-07 --quantile 0.75 --top-k 3 --output skill_evidence/tableagent-trailing-window-threshold.json
```

Failure states: `duplicate_group_period`, `insufficient_reference`, `incomplete_calendar_window`, `no_positive_exceedance`.
