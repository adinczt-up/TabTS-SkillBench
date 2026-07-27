---
name: tableagent-forward-fill-imputation
description: Use when a regular grouped time series asks to fill specified missing periods with the most recent strictly earlier observed value, including an explicit holdout evaluation where an observed target is temporarily hidden and compared with the imputation. Requires unique group-period rows, period frequency, target mode, target periods, and no unresolved duplicate grain. Do not use for interpolation, seasonal baselines, backward fill, extrapolating before the first observation, or overwriting observed values outside an explicit holdout evaluation.
---

# Forward-Fill Imputation

## Trigger Boundary

- Trigger only when the requested rule is last observation carried forward or forward fill.
- Trigger after a regular period grid and missing targets have been established.
- Do not trigger when both neighboring values are used, when future observations may determine the imputation, or when an observed target is not explicitly declared as a holdout.
- Boundary: a previous-month lookup is not imputation unless the target period itself is missing and must be filled.

## Input Contract

Provide `time_column`, `group_columns`, `value_column`, `period_frequency`,
`target_mode` (`missing` or `holdout`), `target_periods`, `cutoff_exclusive`,
`maximum_gap_periods` (`null` means no declared maximum), `top_k`, and
`require_immediate_previous`. All entities and periods are runtime parameters.

## Mechanical Procedure

1. Parse periods and numeric values; reject duplicate group-period keys.
2. Retain observed rows strictly before `cutoff_exclusive`.
3. For `missing`, verify the target value is absent/null. For `holdout`, preserve exactly one observed target as `actual`, then exclude it from candidate sources.
4. Select the observed row with the greatest period strictly less than the target.
5. Compute the calendar-period gap, not the row-position gap.
6. If there is no earlier observation, return `no_prior_observation`.
7. If `maximum_gap_periods` is set and exceeded, return `gap_limit_exceeded`.
8. In holdout mode, compute `absolute_error=abs(imputed-actual)`, rank on the unrounded requested score, and emit canonical period labels plus `selected_rows`.
9. Recompute all rows with the validator before using them in the answer; copy final values only from `selected_rows`.

## Output Contract

```json
{
  "status": "ok",
  "result_rows": [
    {
      "group": "...",
      "target_period": "YYYY-MM",
      "source_period": "YYYY-MM",
      "imputed_value": 0.0,
      "gap_periods": 1
    }
  ],
  "failures": []
}
```

## Failure States

- `target_not_missing`: do not overwrite the observed value in `missing` mode.
- `target_not_observed`: holdout evaluation cannot proceed without the observed target.
- `no_prior_observation`: no imputed value; backward filling is prohibited.
- `gap_limit_exceeded`: no imputed value; report the available source and gap.
- `duplicate_group_period`: stop all imputation until grain is repaired.
- Partial output is allowed only for unaffected group-target pairs.

## Structured Execution

```bash
python skills/tableagent-forward-fill-imputation/scripts/execute_analysis.py --input period_rows.parquet --contract forward_fill_contract.json --output skill_evidence/tableagent-forward-fill-imputation.json
python skills/tableagent-forward-fill-imputation/scripts/validate_result.py --input skill_evidence/tableagent-forward-fill-imputation.json --output skill_evidence/tableagent-forward-fill-imputation.validation.json
```
