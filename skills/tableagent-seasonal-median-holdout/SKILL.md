---
name: tableagent-seasonal-median-holdout
description: Use when a grouped monthly or quarterly series asks to hold out an observed target and impute it with the median of the same calendar season from other years, with a minimum donor count and error ranking. Requires one prepared row per group-period and an explicit target. Do not use for adjacent-period interpolation, rolling medians, forward fill, donors from the target year, or season definitions not implied by the declared frequency.
---

# Seasonal Median Holdout

1. Reject duplicate group-period rows and preserve the target actual for evaluation only.
2. Select donors in the same calendar month or quarter, excluding the exact target period and target year.
3. Require the declared minimum donor count after numeric/missing filtering.
4. Compute the unrounded donor median, actual, and absolute error.
5. Rank on raw error with deterministic group ties. Answer only from evidence.

```bash
python skills/tableagent-seasonal-median-holdout/scripts/execute_analysis.py --file prepared.parquet --group segment --time month --value metric --frequency month --target 2011-07 --min-donors 2 --top-k 3 --output skill_evidence/tableagent-seasonal-median-holdout.json
```

Failure states: `duplicate_group_period`, `target_not_observed`, `insufficient_donors`, `no_valid_groups`.
