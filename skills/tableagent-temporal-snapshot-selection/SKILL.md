---
name: tableagent-temporal-snapshot-selection
description: Use when a tabular question needs one reproducible record per entity at a final period, exact anchor, latest period at or before an anchor, or earliest period at or after it. Requires a prepared table with group and ordered time/round fields. Do not use for rolling windows, event segmentation, interpolation, or whole-window aggregation.
---

# Temporal Snapshot Selection

## Trigger Boundary

- Trigger for final standing, status at round K, latest observation by a midpoint, or first observation after an event.
- Do not trigger for summing all records in a period, lag discovery, or selecting a global row without entity groups.
- Borderline: `after round K` aggregation uses time-window coverage; the status at round K uses this skill.

### Query Examples

- Should trigger: "For every account, take the latest risk grade available by quarter two." Reason: one per-account record must be selected at an anchor.
- Should not trigger: "Sum all payments after quarter two." Reason: this is a window aggregation.
- Boundary: "Report performance at and after round three." Reason: use this skill for the record at round three and time-window coverage for later records.

## Input Contract

Require a prepared CSV/Excel table, group columns, one ordered temporal or ordinal column, selection mode, optional anchor, and optional deterministic tie-break columns. Do not pass expected entities or values.

## Mechanical Procedure

1. Verify the order field is monotonic within each group after sorting and has a declared numeric, datetime, or lexical type.
2. Choose exactly one mode: `final`, `exact`, `latest_at_or_before`, or `earliest_at_or_after`.
3. Apply the anchor predicate within each group before selecting a row.
4. Select by the raw order value. Use tie-break columns only when their semantics are declared.
5. Reject groups with no eligible row; never backfill from a forbidden side of the anchor.
6. Materialize the selected rows and evidence with `scripts/select_snapshot.py`.
7. Assert at most one selected row per group before downstream joins.

## Output Contract

The script returns mode, anchor, group columns, order column/type, selected rows, missing groups, ambiguous groups, and `valid`.

## Failure States

- `anchor_required`: no selection.
- `no_eligible_record`: return missing groups; prohibit claims about those groups.
- `ambiguous_snapshot`: add a justified tie-break field or stop.
- `invalid_order_values`: clean or explicitly exclude invalid rows before selection.

## Command

```bash
python skills/tableagent-temporal-snapshot-selection/scripts/select_snapshot.py --file prepared.csv --group-columns season entity_id --order-column round --mode latest_at_or_before --anchor 3 --order-type numeric --output snapshots.json
```
