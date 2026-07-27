---
name: tableagent-directional-delta-validation
description: Use when a tabular question asks for change, gain, improvement, decline, swing, before-after difference, or rank movement and the sign depends on an explicit source-to-target orientation. Requires two comparable values and a declared direction rule. Do not use for ratios, growth rates, unsigned distances only, or unresolved field bindings.
---

# Directional Delta Validation

## Trigger Boundary

- Trigger when lower values may be better, wording distinguishes increase from improvement, or the requested output mixes signed and absolute changes.
- Do not trigger for percentage growth, a direct lookup, or values with different units.
- Borderline: selecting the largest absolute swing uses this skill to compute both signed and absolute values, then ranking-filtering to select the maximum.

### Query Examples

- Should trigger: "Which entity improved most from rank 19 to rank 2?" Reason: lower rank is better, so improvement is source minus target.
- Should not trigger: "What is revenue growth from 100 to 120?" Reason: use a growth-rate calculation.
- Boundary: "Find the largest position swing and report its direction." Reason: compute both absolute magnitude for selection and signed change for reporting.

## Input Contract

Require source label/value, target label/value, common unit, and one rule: `target_minus_source`, `source_minus_target`, `improvement_higher_better`, `improvement_lower_better`, or `absolute_change`. Values and labels are task parameters; never embed expected results.

## Mechanical Procedure

1. Bind source and target periods/stages before arithmetic.
2. Record whether larger or smaller values represent better performance.
3. Compute raw signed change as `target - source`.
4. Transform to the requested reported delta using the declared rule.
5. Keep the raw and reported deltas as separate fields.
6. Rank on the requested field without rounding; round only the final display.
7. Run `scripts/compute_delta.py` for each comparison or vectorize the identical formula in a deterministic script.

## Output Contract

```json
{
  "source": {"label": "", "value": 0},
  "target": {"label": "", "value": 0},
  "unit": "",
  "rule": "",
  "raw_target_minus_source": 0,
  "reported_delta": 0
}
```

## Failure States

- `orientation_unspecified`: do not output a signed conclusion.
- `incomparable_units`: normalize units or stop.
- `source_target_unbound`: return no delta.
- `absolute_signed_conflict`: retain both values and select according to the exact requested field.

## Command

```bash
python skills/tableagent-directional-delta-validation/scripts/compute_delta.py --source-label before --source-value 19 --target-label after --target-value 2 --unit rank --rule improvement_lower_better
```
