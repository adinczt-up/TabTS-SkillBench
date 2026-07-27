---
name: tableagent-ranking-filtering
description: Use for tabular questions involving top/bottom K, extrema, explicit ranks, threshold predicates, ties, or filtered entity selection when a raw comparison field can be materialized. Select on unrounded values and validate result-set completeness. Do not use for direct lookup, unfiltered whole-table calculations, or unresolved metric bindings.
---

# Ranking And Filtering

## Trigger Boundary

- Trigger for top/bottom K, maximum/minimum, rank thresholds, all tied extrema, or conditional row selection.
- Do not trigger for direct lookup or an aggregate with no row selection.
- Borderline: compute a derived metric first, then pass its unrounded value into this skill.

## Input Contract

Require a prepared file, raw comparison column, direction, K, selection mode, optional entity column, and all eligibility filters already applied. Never include expected winners or Gold values.

## Mechanical Procedure

1. Bind the comparison metric and normalize units before selection.
2. Materialize eligibility filters before sorting; record eligible row count.
3. Preserve the full-precision comparison value in `raw_metric`. Do not round, format, or cast to a short string before selecting.
4. Resolve semantics:
   - `top K` or `bottom K` -> `exact_k` unless the question explicitly requests ties;
   - `all maxima/minima`, `include ties`, or `every case with the largest` -> `include_ties`.
5. Sort on raw values. Under `include_ties`, use exact raw equality unless a task-defined numeric tolerance is supplied.
6. Materialize selected row IDs and all eligible raw metrics.
7. Run the validator and assert there are no omitted or extra tied rows.
8. Round only fields in the final presentation after the selected set is fixed.

## Commands

```bash
python skills/tableagent-ranking-filtering/scripts/execute_selection.py --file candidates.csv --metric-column raw_rate --entity-column entity --k 1 --direction top --selection-mode include_ties --output selection.json
python skills/tableagent-ranking-filtering/scripts/validate_result.py --input selection.json
```

## Failure States

- `fewer_than_k_rows`: no selection.
- `non_numeric_metric`: return invalid rows; do not rank formatted strings.
- `selected_count_mismatch`: prohibit downstream aggregation.
- `tie_completeness_failure`: add omitted ties or remove non-ties before answering.
- `premature_rounding_detected`: recompute selection from raw values.
