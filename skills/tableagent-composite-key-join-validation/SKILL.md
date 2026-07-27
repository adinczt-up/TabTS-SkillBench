---
name: tableagent-composite-key-join-validation
description: Use before aggregating two local tables whose records must be paired on one or more identifiers, especially event-entity or entity-period keys. Requires explicit candidate keys and an expected join cardinality. Do not use for unions, fuzzy entity resolution, relation-path discovery, or already-validated materialized joins.
---

# Composite-Key Join Validation

## Trigger Boundary

- Trigger when pairing records across tables can duplicate, drop, or cross-match observations.
- Do not trigger for vertical concatenation, fuzzy name matching, or a direct many-to-one lookup whose primary key is already verified.
- Borderline: a single shared identifier still triggers when either table has repeated identifiers at a finer grain.

### Query Examples

- Should trigger: "Pair each site's hourly forecast with its observed value for the same metric." Reason: site, timestamp, and metric jointly define the record.
- Should not trigger: "Append January and February files with identical schemas." Reason: this is a union, not a join.
- Boundary: "Join on customer_id." Reason: trigger when either table repeats customers by date or product; do not trigger when the right table has a verified unique customer primary key.

## Input Contract

Require left/right files, ordered left/right key lists, expected cardinality, minimum match coverage, and optional maximum row-expansion ratio. Keys and thresholds must come from the task and schema plan, never from Gold.

## Mechanical Procedure

1. State both table grains before choosing keys.
2. Use all identifiers needed to represent the common grain; do not omit event, entity, category, or period components.
3. Run `scripts/validate_join.py` before computing any measure.
4. Check null-key rows, duplicate key groups, matched-key coverage, joined row count, and expansion ratio.
5. Stop if observed uniqueness conflicts with expected cardinality.
6. Materialize the validated join once and aggregate from that artifact.

## Output Contract

The script returns input rows, non-null key rows, duplicate groups, matched rows, match rates, joined rows, expansion ratio, cardinality, and `valid`.

## Failure States

- `missing_key_column`: no partial join; revise the schema path.
- `null_join_keys`: exclude only when the task's missing policy authorizes exclusion.
- `cardinality_violation`: prohibit aggregation.
- `low_match_coverage`: allow unmatched-row diagnostics, not a final aggregate.
- `unexpected_row_expansion`: prohibit aggregation and add missing key components.

## Command

```bash
python skills/tableagent-composite-key-join-validation/scripts/validate_join.py --left-file left.csv --right-file right.csv --left-keys event_id entity_id --right-keys event_id entity_id --relationship one_to_one --min-left-match-rate 0.95 --max-expansion-ratio 1.05
```
