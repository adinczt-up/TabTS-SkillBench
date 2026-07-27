---
name: tableagent-time-window-coverage
description: Use for tabular time-series analysis that depends on a start/end period, before/after boundary, named phase, anchor time, ordinal round, or full-record claim when an ordered time or period field is available. Materialize endpoint inclusion and coverage before aggregation. Do not use for timeless filters, one-record snapshots, or conclusions independent of the selected window.
---

# Time Window Coverage

## Trigger Boundary

- Trigger for before/after K, between dates, later-period totals, named phases, or full-history claims.
- Do not trigger for a timeless row filter or one per-entity snapshot; use temporal snapshot selection for the latter.
- Borderline: status at round K is a snapshot; points after round K are a window with an exclusive lower endpoint.

## Input Contract

Require a prepared file, ordered field, order type (`numeric`, `datetime`, or `lexical`), boundary values, and explicit endpoint inclusion. Entity and metric fields remain parameters; never include expected results.

## Mechanical Procedure

1. Identify the order field, type, observed minimum/maximum, and requested boundaries.
2. Translate wording into predicates before filtering:
   - `after K` -> `order > K`;
   - `from K` or `K onward` -> `order >= K`;
   - `before K` -> `order < K`;
   - `through K` -> `order <= K`.
3. Apply predicates on values, never preview length, row number, or file order.
4. Record selected row count, observed coverage, invalid order rows, and missing groups.
5. Run `scripts/select_window.py` with `--selected-output <window.parquet>` and aggregate only that filtered data file. The evidence JSON must contain summary metadata only; never serialize selected rows into evidence.
6. Keep boundary-window values separate from values at the anchor snapshot.

## Evidence Record

```json
{
  "order_column": "",
  "order_type": "numeric|datetime|lexical",
  "lower": null,
  "lower_inclusive": false,
  "upper": null,
  "upper_inclusive": true,
  "observed_min": null,
  "observed_max": null,
  "selected_rows": 0,
  "coverage_complete": true,
  "selected_output": "prepared_window.parquet",
  "selected_output_bytes": 0,
  "evidence_policy": "summary_only_no_embedded_rows"
}
```

## Failure States

- `invalid_order_values`: clean or explicitly exclude invalid rows.
- `empty_window`: output no aggregate.
- `boundary_outside_coverage`: allow a bounded partial result only with an explicit coverage limitation.
- `endpoint_ambiguity`: do not compute until inclusion is resolved from wording.

## Command

```bash
python skills/tableagent-time-window-coverage/scripts/select_window.py --file prepared.csv --order-column round --order-type numeric --lower 3 --lower-exclusive --selected-output prepared_window.parquet --output skill_evidence/tableagent-time-window-coverage.json
```

The JSON evidence is a bounded control record, not a transport format for filtered data. Downstream scripts read `selected_output`; validators check counts, boundaries, and file existence without copying table rows.
