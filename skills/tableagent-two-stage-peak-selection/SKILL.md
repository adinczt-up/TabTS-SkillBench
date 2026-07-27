---
name: tableagent-two-stage-peak-selection
description: "Use when a grouped period table requires two-stage selection: first retain every period tied for each group's raw maximum or minimum, then compare those retained group-period rows globally. Requires a unique eligible group-period table and an explicit within-group and global direction. Do not use for a single global extremum, top-K without a within-group stage, or period aggregation itself."
---

# Two-Stage Peak Selection

## Trigger Boundary

- Trigger for "peak month within each group, then largest peak across groups" and the symmetric minimum case.
- Do not trigger for one global maximum or for creating monthly aggregates.
- Borderline: use period-bucket aggregation first when raw rows have not yet been reduced to one eligible group-period row.

## Input Contract

Require unique `group`, `period`, full-precision `raw_metric`, optional `record_n`, `within_direction`, `global_direction`, and tie mode. Tie mode must be `include_all` for requests using every/all/tied.

## Mechanical Procedure

1. Input: eligible period table. Operation: verify unique group-period keys and preserve raw metric precision. Output: validated candidates. Failure: `duplicate_group_period`.
2. Input: candidates. Operation: compute each group's raw extremum in the declared direction. Output: group extrema. Check: no display rounding occurs.
3. Input: group extrema and candidates. Operation: retain every group-period row exactly tied with its group extremum. Output: stage-one rows. Check: each eligible group contributes at least one row. Failure: `within_group_tie_incomplete`.
4. Input: stage-one rows. Operation: compute the global raw extremum in the declared direction and retain all exact ties. Output: final selected rows. Failure: `global_tie_incomplete`.
5. Input: final rows. Operation: format periods and round display values only after selection. Output: structured evidence and presentation rows.

## Output Contract

```json
{
  "status": "ok",
  "within_direction": "max",
  "global_direction": "max",
  "stage_one_rows": [{"group": "...", "period": "...", "raw_metric": 0.0, "record_n": 0}],
  "selected_rows": [{"group": "...", "period": "...", "raw_metric": 0.0, "record_n": 0}]
}
```

## Validation And Failure States

- For every group, prove no eligible period exceeds its retained stage-one extremum.
- Prove no stage-one row exceeds the selected global extremum and no tied row is omitted.
- `empty_eligible_table`: no answer.
- `duplicate_group_period`: return duplicates; prohibit selection.
- `premature_rounding_detected`: recompute both stages from raw values.

## Required Structured Execution
```bash
python skills/tableagent-two-stage-peak-selection/scripts/execute_analysis.py --input period_rows.parquet --group-column segment --period-column period_start --metric-column raw_value --count-column analysis_unit_n --within-direction max --global-direction max --output skill_evidence/tableagent-two-stage-peak-selection.json
python skills/tableagent-two-stage-peak-selection/scripts/validate_result.py --input skill_evidence/tableagent-two-stage-peak-selection.json --output skill_evidence/tableagent-two-stage-peak-selection.validation.json
```
Use only validated `selected_rows`; the validator reloads the eligible period table and repeats both tie-preserving stages.