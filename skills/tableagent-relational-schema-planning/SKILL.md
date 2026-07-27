---
name: tableagent-relational-schema-planning
description: Use for local multi-table analysis when relevant tables must be selected from a catalog with distractors, or when a safe join path and analysis grain must be established before computation. Requires readable schemas and question-stated entity, measure, time, and population concepts. Do not use for one-table tasks, already materialized analysis-unit tables, or questions that explicitly provide the complete tables, keys, cardinalities, and target grain.
---

# Relational Schema Planning

## Input

Extract from the question only:

- entity and grouping concepts;
- requested outcome measure and its physical/counting unit;
- event/condition indicator, explicitly separated from the outcome measure;
- time owner and target grain;
- population/denominator definition;
- candidate table directory.

Never use Gold rows, expected winners, or expected numeric values when selecting tables.

## Procedure

1. Run one bounded schema profile:

```bash
python skills/tableagent-relational-schema-planning/scripts/profile_relations.py --data-dir datasets --max-rows 2000 --output relation_profile.json
```

2. Map every required concept to one or more `table.column` candidates. Assign distinct roles for `population`, `outcome_measure`, `event_indicator`, `group_label`, and `time`. A similarly named flag or response column is not the outcome measure unless its source semantics and unit match the question.
3. Choose the smallest connected table set covering all concepts. Break equally small plans by sampled key overlap, then table name.
4. Fix one analysis-unit key and one time owner before joining. Storage-row frequency does not define the requested grain.
5. Choose the population anchor before optional event/fact tables. Use a left join when absence represents zero events; otherwise preserve null. When the event indicator and outcome measure come from different child tables, pre-aggregate both independently to the analysis-unit key before joining.
6. Before a one-to-many join, aggregate the child to the join key unless the question explicitly requires expansion.
7. Before computation, perform a metric-role check: record the outcome source column, its unit, and the aggregation that creates one value per analysis unit. Reject binary flags, invitation indicators, statuses, or event labels when the requested measure is a count derived from another table.
8. After every join, check anchor-row preservation, unique analysis-unit count, duplicate units, unmatched keys, and one source-measure total or mean.
9. Read and compute only from the selected tables. Do not open rejected tables during the main analysis.

## Planning Record

Keep this compact record in the trajectory or analysis code:

```json
{
  "selected_tables": [],
  "rejected_tables": {},
  "concept_table_map": {},
  "role_bindings": {
    "outcome_measure": {"table": "", "column": "", "unit": "", "within_unit_aggregate": ""},
    "event_indicator": {"table": "", "column": "", "within_unit_aggregate": ""}
  },
  "analysis_unit_keys": [],
  "analysis_time_owner": "table.column",
  "population_anchor": "",
  "join_edges": [
    {"left": "", "right": "", "keys": [], "join_type": "left|inner", "right_preaggregated": true}
  ],
  "post_join": {"lost_anchor_units": 0, "duplicate_units": 0, "measure_preserved": true}
}
```

## Failure States

- `unresolved_concepts`: stop before reading full tables; report unmapped concepts.
- `disconnected_required_tables`: do not join on a coincidental same-name column.
- `ambiguous_analysis_grain`: do not aggregate until the observation unit is resolved from the question.
- `outcome_role_mismatch`: do not substitute a similarly named indicator, status, or event field for the requested measure.
- `missing_measure_source`: do not continue until the table that physically contains or deterministically derives the requested measure is selected.
- `unsafe_join_cardinality`: pre-aggregate or stop.
- `lost_anchor_units` or `duplicate_units`: discard the joined result and repair the join.
