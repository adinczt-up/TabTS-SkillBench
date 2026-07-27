---
name: tableagent-grouped-two-period-aggregate
description: Use for grouped tabular time-series questions that compare a mean or binary-event rate across two explicit, non-overlapping half-open windows and then select signed or absolute change extrema. Requires one validated row per analysis unit, group/time/value columns, a split boundary, and minimum counts. Do not use for rank movement, percentage growth, rolling windows, or unresolved analysis grain.
---

# Grouped Two-Period Aggregate

## Trigger Boundary
- Trigger for early-versus-late grouped means, event shares, largest signed change, largest absolute change, or smallest absolute change.
- Do not trigger for dense ranks, ratios, growth percentages, or more than two windows.
- Boundary: binary event rates trigger only after a complete zero-inclusive event universe exists.

## Input Contract
Require `input`, `group_column`, `time_column`, `value_column`, `mode`, `window_start`, `split`, `window_end_exclusive`, `minimum_n`, and `selection`. `mode` is `mean` or `rate`; rate values must be 0/1. `selection` is `max_signed`, `max_abs`, or `min_abs`. Never pass expected winners or Gold values.

## Mechanical Procedure
1. Validate one row per declared analysis unit before this Skill.
2. Parse time and retain `start <= time < end`; assign early by `time < split` and late otherwise.
3. Compute group-period mean and exact analysis-unit count. For rate mode, mean the complete binary indicator.
4. Retain groups satisfying `early_n >= minimum_n` and `late_n >= minimum_n`.
5. Compute full-precision `change = late_value - early_value` and `absolute_change`.
6. Select all exact ties using the declared selection; round only when formatting the final answer.
7. Run the validator and use only `selected_rows` from validated evidence.

## Output And Failures
Output `result_rows`, `selected_rows`, period values, changes, counts, and invariants. `missing_columns`, `rate_value_not_binary`, `insufficient_period_coverage`, or failed validation prohibit a final numeric conclusion; partial candidate rows may be reported only as diagnostics.

## Structured Execution
```bash
python skills/tableagent-grouped-two-period-aggregate/scripts/execute_analysis.py --input prepared.parquet --group-column segment --time-column ts --value-column metric --mode mean --window-start 2020-01-01 --split 2021-01-01 --window-end-exclusive 2022-01-01 --minimum-n 20 --selection max_signed --output skill_evidence/tableagent-grouped-two-period-aggregate.json
python skills/tableagent-grouped-two-period-aggregate/scripts/validate_result.py --input skill_evidence/tableagent-grouped-two-period-aggregate.json --output skill_evidence/tableagent-grouped-two-period-aggregate.validation.json
```