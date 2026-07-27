---
name: tableagent-two-period-rank-reversal
description: Use when groups must be densely ranked on the same aggregate in two explicit time windows and rank movement is defined from the two ranks. Requires validated analysis-unit rows, common group/time/value fields, minimum period counts, and an ascending or descending rank rule. Do not use for top-K in one table, raw score changes without ranks, rolling ranks, or unresolved ties.
---

# Two-Period Rank Reversal

## Trigger Boundary
- Trigger for early rank versus late rank, rank gain/loss, or rank reversal using dense ranks.
- Do not trigger for one-period top-K, ordinal source fields already containing official ranks, or percentage change.
- Boundary: if the question supplies ranks directly, validate direction with directional-delta instead.

## Input Contract
Require `input`, `group_column`, `time_column`, `value_column`, `window_start`, `split`, `window_end_exclusive`, `minimum_n`, and `rank_direction`. All entities and boundaries are runtime parameters; never encode expected groups.

## Mechanical Procedure
1. Validate one comparable row per analysis unit and filter the half-open window using the declared analysis timestamp owner. If values summarize child facts attached to parent records, do not filter child timestamps unless the question explicitly defines a child-event window.
2. Compute each group's unrounded early and late means and counts.
3. Remove groups failing either minimum count before ranking.
4. Dense-rank all remaining groups separately in each period using the declared direction.
5. Compute `rank_gain = early_rank - late_rank`.
6. Select every group tied for maximum raw rank gain.
7. Validate by recomputing from the source, then format selected rows only.

## Output And Failures
Output all group ranks, means, counts, rank gains, and selected ties. Missing columns, insufficient coverage, nonnumeric values, or failed recomputation prohibit a rank conclusion. Do not silently switch dense rank to ordinal rank.

## Structured Execution
```bash
python skills/tableagent-two-period-rank-reversal/scripts/execute_analysis.py --input prepared.parquet --group-column segment --time-column ts --value-column metric --window-start 2020-01-01 --split 2021-01-01 --window-end-exclusive 2022-01-01 --minimum-n 20 --rank-direction descending --output skill_evidence/tableagent-two-period-rank-reversal.json
python skills/tableagent-two-period-rank-reversal/scripts/validate_result.py --input skill_evidence/tableagent-two-period-rank-reversal.json --output skill_evidence/tableagent-two-period-rank-reversal.validation.json
```
