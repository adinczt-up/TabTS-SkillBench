---
name: tableagent-quantile-range
description: Use for grouped tabular questions that require continuous empirical quantiles and a quantile range such as p90 minus p10, with an explicit observation window and minimum group size. Requires finite numeric source values and declared quantile probabilities/interpolation convention. Do not use for mean differences, standard deviation, categorical percentiles, approximate sketches, or distribution-equality tests.
---

# Quantile Range

## Trigger Boundary

- Trigger for exact grouped p10/p90, interquartile range, or another declared continuous quantile spread.
- Do not trigger for standard deviation, average range, approximate warehouse quantiles, or distribution hypothesis tests.
- Borderline: if the question says only "spread" without defining it, stop for clarification instead of assuming quantiles.

## Input Contract

Require `group_columns`, `value_column`, `lower_probability`, `upper_probability`, continuous interpolation convention, observation filters, and `minimum_group_n`. Probabilities must satisfy `0 <= lower < upper <= 1`.

## Mechanical Procedure

1. Input: source values and filters. Operation: apply filters, coerce finite numeric values, and record excluded null/nonfinite rows. Output: grouped numeric samples. Failure: `non_numeric_values`.
2. Input: grouped samples. Operation: retain groups with `n >= minimum_group_n`. Output: eligible groups and excluded-group counts. Failure: `insufficient_group_n`.
3. Input: sorted values per group. Operation: compute continuous quantiles using the declared linear interpolation rule at both probabilities. Output: full-precision lower and upper quantiles. Check: lower quantile <= upper quantile. Failure: `quantile_order_violation`.
4. Input: quantiles. Operation: compute `raw_spread = upper_quantile - lower_quantile`. Output: raw values and n. Check: spread is nonnegative. Failure: `negative_spread`.
5. Input: raw group results. Operation: select extrema and ties before display rounding. Output: selected evidence rows.

## Output Contract

```json
{
  "status": "ok",
  "probabilities": [0.1, 0.9],
  "groups": [{"group": "...", "n": 0, "raw_lower": 0.0, "raw_upper": 0.0, "raw_spread": 0.0}],
  "excluded_nonfinite_n": 0
}
```

## Validation And Failure States

- Recompute quantiles from sorted evidence using the same interpolation convention.
- Assert reported n equals the exact eligible sample size.
- `interpolation_unspecified`: do not output a unique numeric quantile.
- `insufficient_group_n`: partial results allowed for other groups; prohibit conclusions about excluded groups.
- `approximate_quantile_only`: label approximation explicitly or stop if exact output is required.

## Required Structured Execution
```bash
python skills/tableagent-quantile-range/scripts/execute_analysis.py --input prepared.parquet --group-column segment --value-column metric --lower-probability 0.1 --upper-probability 0.9 --minimum-group-n 40 --selection max --output skill_evidence/tableagent-quantile-range.json
python skills/tableagent-quantile-range/scripts/validate_result.py --input skill_evidence/tableagent-quantile-range.json --output skill_evidence/tableagent-quantile-range.validation.json
```
Use only validated `selected_rows`; the validator reloads the original source and recomputes all quantiles.