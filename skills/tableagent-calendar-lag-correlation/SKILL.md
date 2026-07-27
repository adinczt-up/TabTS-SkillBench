---
name: tableagent-calendar-lag-correlation
description: Use when a grouped regular time series asks for Pearson correlation between a current response and the same or another predictor at one or more explicit calendar lags, followed by lag or group selection. Requires one prepared row per group-period and declared lags/frequency. Do not use for retained-row shifts, unknown-lag discovery outside a finite set, regression coefficients, scaling relations, or causal claims.
---

# Calendar Lag Correlation

## Procedure

1. Prepare exactly one numeric response and predictor value per group-calendar period.
2. Reject duplicate group-period rows. Convert periods to the declared calendar frequency.
3. For lag `L`, pair response at period `t` with predictor at calendar period `t-L` by key join. Never use row-position `shift`.
4. Drop only incomplete pairs. Require the declared minimum pair count and nonzero variance on both sides.
5. Compute Pearson correlation without rounding. Apply any selection rounding stated by the question, then break lag ties toward the shorter lag.
6. Rank groups on the requested absolute or signed correlation and use deterministic group tie order.
7. Generate the final answer only from `selected_rows` in the evidence JSON.

## Command

```bash
python skills/tableagent-calendar-lag-correlation/scripts/execute_analysis.py --file prepared.parquet --group segment --time month --response metric --predictor event_rate --lags 1,2,3 --frequency month --min-pairs 3 --top-k 3 --output skill_evidence/tableagent-calendar-lag-correlation.json
```

For autocorrelation, pass the same column to `--response` and `--predictor`.

## Failure States

- `duplicate_group_period`: stop; repair the preparation grain.
- `insufficient_pairs` or `constant_series`: omit only that group-lag and report it in `unresolved`.
- `no_valid_correlations`: do not fabricate a selected lag.
