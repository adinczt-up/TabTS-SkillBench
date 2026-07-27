---
name: tableagent-consecutive-state-runs
description: Use when a grouped time-series task defines high/low or boolean states from period values and asks for consecutive runs, longest duration, run boundaries, or run summaries. Requires one retained row per group-period and an explicit threshold rule and calendar frequency. Do not use for source rows that already contain start/end intervals, inferred spike episodes, or nonconsecutive counts.
---

# Consecutive State Runs

## Procedure

1. Verify unique `group, period` grain and parse periods at the requested calendar frequency.
2. Compute the threshold on the declared reference window separately per group; default only when explicitly requested is the full-window median.
3. Apply the exact comparison (`>`, `>=`, `<`, or `<=`) without rounding.
4. Sort periods and start a new run whenever state is false or the calendar successor is missing. Adjacent retained rows are not necessarily consecutive periods.
5. Compute run start, end, inclusive period count, and unrounded mean value.
6. Select each group's longest run; break equal duration toward the earlier start. Rank groups by duration, then declared group tie order.
7. Emit all runs and selected runs so boundaries and ranking can be recomputed.

## Failure States

- `duplicate_group_period`, `invalid_period`, `threshold_rule_missing`: stop.
- `no_true_state`: return an empty run list, not a fabricated interval.

## Command

```bash
python skills/tableagent-consecutive-state-runs/scripts/execute_analysis.py --file prepared.csv --group segment --time month --value value --frequency month --threshold median --comparison gt --top-k 3
```
