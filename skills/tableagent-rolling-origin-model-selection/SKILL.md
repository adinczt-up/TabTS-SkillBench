---
name: tableagent-rolling-origin-model-selection
description: Use when a grouped regular time series asks to choose among a finite set of one-step forecasting rules using a declared validation block before a target period. Requires one prepared value per group-period and explicit target, frequency, validation length, validation mode (fixed pre-validation fit or expanding rolling origin), candidate models, and tie rule. Do not use for unconstrained model search, random splits, multivariate forecasting, or validation that overlaps the target/future.
---

# Rolling-Origin Model Selection

1. Verify one numeric row per group-calendar period.
2. Define the validation block as the exact consecutive periods immediately before the target.
3. Require `validation_mode` from the question:
   - `fixed_origin`: fit every candidate once using periods strictly before the validation block; use that same fit for all validation periods and the target. Trigger when the task says fitted/trained only before validation.
   - `rolling_origin`: for each validation origin, fit using only periods before that origin; after selection, refit the winner using all periods before the target. Trigger only when expanding or rolling-origin validation is explicit.
4. Never use validation observations as training data in `fixed_origin`, and never use the target actual in either mode.
5. Compute candidate MAE on identical validation targets, select minimum raw MAE, and apply the declared deterministic model tie order.
6. Preserve target actual only for post-forecast error calculation. Rank on unrounded winning MAE and answer by copying `selected_rows` exactly.

Supported deterministic rules are `historical_mean` and `linear_trend`.

```bash
python skills/tableagent-rolling-origin-model-selection/scripts/execute_analysis.py --file prepared.parquet --group segment --time month --value metric --frequency month --target 2015-10 --validation-periods 3 --validation-mode fixed_origin --models historical_mean,linear_trend --tie-order historical_mean,linear_trend --top-k 3 --output skill_evidence/tableagent-rolling-origin-model-selection.json
python skills/tableagent-rolling-origin-model-selection/scripts/validate_result.py --input skill_evidence/tableagent-rolling-origin-model-selection.json --output skill_evidence/tableagent-rolling-origin-model-selection.validation.json
```

Failure states: `validation_mode_unspecified`, `duplicate_group_period`, `incomplete_validation_block`, `insufficient_training`, `target_not_observed`, `no_valid_groups`.
