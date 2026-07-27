---
name: tableagent-two-level-change-point
description: Use when a grouped ordered series asks for one change point chosen by exhaustively fitting two constant levels and minimizing total within-segment squared error, with a minimum number of observations on each side. Requires prepared group-period values, the calendar frequency, output period field, and an explicit tie rule. Do not use for adjacent jump candidates, multiple change points, gradual trends, threshold episodes, or unspecified detectors.
---

# Two-Level Change Point

## Procedure

1. Verify unique group-period rows, parse the declared calendar frequency, sort by actual period, and preserve missing calendar gaps as observed data gaps.
2. Enumerate every split index with at least `min_side` retained observations before and from the split onward.
3. Fit each side by its arithmetic mean and compute `SSE_before + SSE_after` without rounding.
4. Select minimum SSE; break exact ties toward the earlier split period.
5. Report `level_change = after_mean - before_mean`, preserving sign.
6. Rank groups by the requested unrounded magnitude and deterministic group tie order.
7. Emit compact group winners and `selected_rows`. Write all candidate splits only to an optional audit file; never inject the full candidate list into the answer context.
8. Copy the final JSON only from `selected_rows`. Use the requested output field names and the frequency-specific period label (`YYYY-MM` for month, `YYYY-Qn` for quarter, `YYYY` for year).

## Failure States

- `duplicate_group_period`, `too_few_points`, `no_eligible_split`.

## Command

```bash
python skills/tableagent-two-level-change-point/scripts/execute_analysis.py --file prepared.csv --group segment --time month --value value --frequency month --group-output-field segment --time-output-field change_month --min-side 3 --top-k 3 --output skill_evidence/tableagent-two-level-change-point.json
python skills/tableagent-two-level-change-point/scripts/validate_result.py --input skill_evidence/tableagent-two-level-change-point.json --output skill_evidence/tableagent-two-level-change-point.validation.json
```
