---
name: tableagent-grouped-anomaly-scoring
description: Use when a tabular task asks to score or rank period-level observations as distributional anomalies within each entity/group using an explicitly requested IQR or median-MAD rule. Requires prepared group, period, and numeric value columns. Do not use for adjacent jumps, episode segmentation, residual-noise classification, rolling thresholds, or unspecified anomaly methods.
---

# Grouped Anomaly Scoring

## Input Contract

Require a table containing one retained observation per `group, period`, plus `method` (`iqr` or `mad`), optional `top_k`, and exact tie order. Upstream aggregation must finish before this skill runs.

## Procedure

1. Reject duplicate `group, period` rows and nonnumeric values.
2. Compute reference statistics separately within each group over the full requested window.
3. For `iqr`, compute Q1, Q3, and `IQR=Q3-Q1` with the declared quantile interpolation. Score distance outside `[Q1,Q3]` divided by IQR; score inside points as zero.
4. For `mad`, compute median and `scale=1.4826*median(abs(x-median))`; score absolute deviation divided by scale.
5. Mark zero-scale groups unresolved instead of dividing by zero.
6. Rank unrounded scores descending, then apply the declared deterministic group/period tie order. Slice `top_k` only after ranking.
7. Emit structured evidence and generate the final answer only from selected rows.

## Output

Return method, parameters, group statistics, scored rows, selected rows, and unresolved groups. Do not substitute another anomaly definition.

## Failure States

- `duplicate_group_period`: stop; repair upstream grain.
- `method_unspecified`: stop; do not choose a preferred detector.
- `zero_scale`: omit only affected groups and disclose them.
- `insufficient_group_points`: no score for that group.

## Command

```bash
python skills/tableagent-grouped-anomaly-scoring/scripts/execute_analysis.py --file prepared.csv --group segment --time month --value value --method iqr --top-k 3
```
