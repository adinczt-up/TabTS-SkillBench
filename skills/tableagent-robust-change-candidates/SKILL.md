---
name: tableagent-robust-change-candidates
description: Use only for candidate timestamps of abrupt adjacent rises, drops, jumps, or spikes in an ordered numeric series, using robust first-difference scores. Produce candidates rather than a final selected model. Do not use for level anomalies scored against a group's IQR/MAD, exhaustive two-segment SSE change-point fitting, distinct-event counts, recurring periods, or final event classification.
---

# Robust Change Candidates

## Use

Apply to pointwise abrupt-change detection. Do not use for gradual trend estimation, ordinary seasonal maxima, or final event counting.

Use `tableagent-grouped-anomaly-scoring` for deviations from a group distribution and `tableagent-two-level-change-point` when every eligible split must be fitted and compared by SSE.

## Procedure

1. Sort by time, preserve missing values, and identify the normal sampling interval.
2. Split the series at material time gaps; never difference across a gap.
3. Compute first differences within each continuous segment.
4. Estimate baseline difference with the median and robust spread with 1.4826 times MAD.
5. If MAD is zero, use IQR divided by 1.349. If both are zero, explicitly review nonzero differences.
6. Select candidates using a stated standardized threshold. Apply a requested direction after candidate generation.
7. For each candidate, inspect one observation before and after it to identify an immediate reversal.
8. Retain the candidate record below. Do not turn candidate rows into an event count in this skill.

## Candidate Record

    timestamp: ...
    previous_value: ...
    current_value: ...
    delta: ...
    robust_score: ...
    direction: up or down
    continuous_segment: ...
    threshold_rule: ...

## Guardrails

- Do not choose a threshold only from visual impression.
- Do not silently discard candidates near phase boundaries or data gaps.
- Do not claim candidate completeness without reporting the threshold rule.

## Handoff

Pass the candidate records to temporal-event-segmentation when the requested unit is an event, spike, or episode.
