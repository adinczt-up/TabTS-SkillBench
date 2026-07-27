---
name: tableagent-sparse-event-universe
description: Use when event, response, maintenance, failure, vote, comment, or attendance rows are stored sparsely and a rate, mean, count, or comparison must include eligible parent/time units with no child rows as explicit zeros. Requires a complete parent or entity-time universe, matching keys, an event definition, and semantics that absence means zero. Do not use when every analysis unit already has an indicator row, missing means unknown, or the question only analyzes observed child events.
---

# Sparse Event Universe Completion

## Trigger Boundary

- Trigger when a child table contains rows only for observed events but the denominator is all eligible parent, entity-period, or event records.
- Trigger when a child-status count must be zero for parents with no matching status rows.
- Do not trigger when missing child rows mean unavailable data rather than zero activity.
- Do not trigger when the requested population explicitly contains only observed child events.

### Routing Examples

- Should trigger: "What share of machine-days had at least one failure?" Reason: no-failure machine-days must remain in the denominator.
- Should trigger: "Compare mean invited-response counts across all events." Reason: events with no invited response require a zero count.
- Should not trigger: "Among recorded failures, compare repair duration." Reason: the population is observed failure rows only.
- Boundary: "Treat missing sensor alarms as zero." Trigger only if local metadata or the question establishes that missing means no alarm, not missing telemetry.

## Input Contract

Require these parameters without expected answers:

- `universe_source` and unique `universe_keys` defining every eligible analysis unit.
- `event_source` and corresponding `event_keys` at the same logical unit.
- half-open observation window and any event filters.
- `event_value`: row count, filtered count, sum, or binary presence.
- `absence_semantics`: must explicitly equal `no_matching_child_means_zero`.
- requested denominator unit, such as event, question, machine-day, or customer-day.

If a complete universe cannot be materialized, stop with `missing_complete_universe`. If absence may mean unknown, stop with `ambiguous_absence_semantics`.

## Mechanical Procedure

1. **Materialize the complete universe**
   - Input: parent/entity/time source and eligibility filters.
   - Operation: create one row per `universe_keys` inside the half-open window.
   - Output: unique universe table and `universe_unit_n`.
   - Check: keys are non-null and unique.
   - Failure: `missing_complete_universe` or `duplicate_universe_key`.
2. **Normalize sparse facts**
   - Input: child rows and event definition.
   - Operation: apply event filters, derive matching key/time buckets, and aggregate child rows to one event count per event key.
   - Output: unique sparse count table.
   - Check: no event key remains duplicated.
   - Failure: `duplicate_event_key_after_aggregation`.
3. **Check key coverage**
   - Input: universe and sparse keys.
   - Operation: anti-join sparse keys against universe keys.
   - Output: unmatched child key count and samples.
   - Check: unmatched count is zero after applying the same window and entity filters.
   - Failure: `unmatched_event_keys`.
4. **Complete zeros**
   - Input: universe and normalized sparse facts.
   - Operation: left join facts onto universe; set missing event count to zero only under the declared absence semantics; derive `event_flag = event_count > 0`.
   - Output: one row per universe unit with count and flag.
   - Check: output unit count equals universe unit count and keys remain unique.
   - Failure: `lost_universe_units` or `grain_multiplication`.
5. **Freeze denominator evidence**
   - Input: completed table.
   - Operation: record total units, positive units, zero units, and assert `positive + zero = total`.
   - Output: denominator manifest.
   - Check: any downstream rate uses total units, not positive units.
   - Failure: `denominator_inconsistent`.
6. **Release completed units**
   - Input: validated manifest and completed table.
   - Operation: pass the completed indicator/count table to period or contrast analysis.
   - Output: analysis-ready evidence.
   - Check: downstream joins may add labels but may not drop zero units.

## Structured Output

```json
{
  "status": "ok",
  "universe_keys": ["entity_id", "date"],
  "absence_semantics": "no_matching_child_means_zero",
  "counts": {
    "universe_unit_n": 0,
    "matched_positive_unit_n": 0,
    "zero_event_unit_n": 0,
    "output_unit_n": 0,
    "unmatched_event_key_n": 0,
    "duplicate_output_key_n": 0
  },
  "output_columns": ["entity_id", "date", "event_count", "event_flag"]
}
```

## Failure States

- `missing_complete_universe`: no rates, shares, or all-record means; report the missing parent/time source.
- `ambiguous_absence_semantics`: preserve nulls and prohibit zero-event conclusions.
- `duplicate_universe_key`: no join until the universe grain is repaired.
- `unmatched_event_keys`: partial diagnostics allowed; do not compute final denominators.
- `grain_multiplication` or `lost_universe_units`: discard completed output and repair keys.
- `denominator_inconsistent`: prohibit rate and mean comparisons.

## Deterministic Scripts

```bash
python skills/tableagent-sparse-event-universe/scripts/execute_analysis.py \
  --universe universe.parquet --events filtered_events.parquet \
  --universe-key entity_id --universe-key date \
  --event-key machine_id --event-key event_date \
  --output completed_units.parquet --manifest skill_evidence/tableagent-sparse-event-universe.json

python skills/tableagent-sparse-event-universe/scripts/validate_result.py \
  --input skill_evidence/tableagent-sparse-event-universe.json --output skill_evidence/tableagent-sparse-event-universe.validation.json
```

The executor aggregates multiple child rows per key, performs the left join, fills only event counts with zero, and records denominator invariants. It accepts CSV, TSV, Excel, or Parquet input.
