---
name: tableagent-temporal-event-segmentation
description: Use for ordered tabular time-series questions asking for distinct spikes or episodes that must be inferred from numeric movement using explicit threshold, adjacency, recovery, and persistence rules. Do not use when event periods are already defined by an event flag/rate, for previous-period event responses, for consecutive threshold states, anomalous-row counts, optimal SSE change points, or recurring-cycle peaks.
---

# Temporal Event Segmentation

## Trigger Boundary

Trigger when the answer unit is an event or episode. Do not trigger when the requested unit is a row, threshold exceedance, or recurring cycle.

Do not infer events when the question already defines them, such as `event_rate > 0`; use `tableagent-event-period-response`. Use `tableagent-consecutive-state-runs` for adjacent high/low state periods.

## Mechanical Procedure

1. Resolve the requested time/phase window before detection. Persist its start and end. If unresolved, return `window_unresolved`.
2. Sort timestamps, estimate the normal sampling interval, and split at material gaps.
3. Compute adjacent changes once. Estimate robust center and scale from median and MAD; use a declared minimum magnitude when domain units require it.
4. Generate candidates with one preregistered threshold. Do not sweep thresholds until a desired count appears.
5. Group candidates separated by at most the declared adjacency gap.
6. Inspect the pre-event baseline and post-event recovery window.
   - move then recovery -> one transient spike;
   - move then persistent new level -> one level shift;
   - contiguous same-direction moves without recovery -> one sustained change.
7. Split episodes only after recovery, a material time gap, or stabilization followed by a new movement.
8. Count event records, never candidate rows. For first-event questions, sort event records and use the first in-window record.
9. For consecutive-period states, declare whether continuity means adjacent calendar periods or adjacent retained observations. Default to adjacent calendar periods; a missing month breaks a run unless the question explicitly defines retained-observation continuity.
10. Run one sensitivity check at threshold +/-20%. If the count changes and no domain threshold resolves it, return `threshold_unstable` rather than forcing an exact count.
11. Validate chronology, membership, window inclusion, count, and canonical period formatting. Stop after one execution plus one sensitivity check to avoid tool-loop exhaustion.

## Output Contract

Return parameters, structured events, reported count, and failure state. Every event must contain timestamps, direction, type, magnitude, member candidates, recovery evidence, and window membership.

## Commands

```bash
python skills/tableagent-temporal-event-segmentation/scripts/execute_analysis.py --file datasets/tableagent_assets/data.xlsx --sheet time_series --time-column timestamp --value-column value --direction down --threshold-z 6 > events.json
python skills/tableagent-temporal-event-segmentation/scripts/validate_result.py --input events.json
```
