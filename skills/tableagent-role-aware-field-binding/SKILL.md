---
name: tableagent-role-aware-field-binding
description: Use when related tables contain similarly named columns that represent different stages, roles, populations, units, or null semantics and the requested measure must be bound before calculation. Requires headers plus sample values or metadata. Do not use when the exact field and semantic role are explicit or for choosing join keys.
---

# Role-Aware Field Binding

## Trigger Boundary

- Trigger for competing fields such as observed versus forecast, opening versus closing, rank versus order, official classification versus completed-finish position, cumulative versus period value, or event result versus later standing.
- Do not trigger to discover tables, validate join cardinality, or calculate after a field is already bound.
- Borderline: identical field names in two tables trigger only when their record stages or populations differ.

### Query Examples

- Should trigger: "Measure improvement from scheduled rank to final processing order." Reason: several rank/order fields represent different stages.
- Should not trigger: "Average `final_order`, which has already been defined as the completion order." Reason: the analytical role is explicit.
- Boundary: "Use the `position` field from two related tables." Reason: trigger if the tables represent different stages; do not trigger if they are verified replicas.
- Should trigger: "Compare qualifying rank with official classified race order, retaining classified non-finishers." Reason: the result table may also contain a nullable display position whose missingness means something different.
- Should not trigger: "Average only actual finishers using the explicitly named completed-finish field." Reason: the role and missing-value policy are already fixed.

## Input Contract

Provide requested concept, candidate `table.column` fields, table grain, stage/role, unit, null meaning, and sample evidence. Never provide the expected result.

## Mechanical Procedure

1. Rewrite the requested concept as `population + stage + measure + unit + missing-value policy`.
2. Enumerate every plausible candidate; do not select by column name alone.
3. For each candidate, record table grain, stage, measure definition, unit, and null meaning from data evidence.
4. Reject candidates whose stage, population, or missing-value policy conflicts with the question. Never replace an official order field with a nullable finish-display field merely because both are named position/order.
5. Select exactly one field for each analytical role. Different roles may bind to different fields.
6. Save a binding record and run `scripts/validate_binding.py` before calculating.

## Binding Record

```json
{
  "requested_role": "",
  "population": "",
  "stage": "",
  "unit": "",
  "missing_policy": "exclude|retain_as_order|zero_is_observed|error",
  "candidates": [
    {"field": "table.column", "grain": "", "role": "", "status": "selected|rejected", "reason": ""}
  ],
  "selected_field": "table.column"
}
```

## Failure States

- `multiple_selected_fields`: prohibit calculation until one field is selected for the role.
- `role_not_evidenced`: allow schema notes only; do not output a value.
- `null_semantics_unknown`: do not silently drop or zero-fill nulls.
- `unit_conflict`: normalize or stop before aggregation.

## Command

```bash
python skills/tableagent-role-aware-field-binding/scripts/validate_binding.py --input binding.json
```
