---
name: tableagent-granger-causality
description: Use only for aligned tabular time-series questions explicitly asking whether one numeric series Granger-causes another. Test both directions over the same justified lags and preserve transformation provenance. Do not use for correlation, physical causality, lag-copy detection, unaligned tables, or vague lead-lag wording.
---

# Granger Causality

## Input Contract

Require file, optional sheet, cause candidate, effect candidate, maximum lag, alpha, and preprocessing (`auto`, `none`, `difference`, or `detrend`). Pass every column and lag at runtime.

## Mechanical Procedure

1. Align both series on identical timestamps and remove rows only pairwise.
2. Test level stationarity separately for each series and record both results.
3. Resolve preprocessing once:
   - both stationary: use levels;
   - both non-stationary: difference both once;
   - one stationary and one non-stationary: do not difference both automatically. Use the bundled Toda-Yamamoto levels procedure: fit each base lag order with one augmented lag, exclude the augmented lag from the Wald restriction, and require a direction to persist across at least half of plausible base lag orders.
4. Never difference a stationary series merely because the other series is non-stationary. This can reverse predictive direction.
5. Test A-to-B and B-to-A over the identical lag range and preprocessing.
6. Require significance at two plausible lags, or a preregistered single lag. An isolated significant lag is insufficient.
7. If both directions pass, compare neither by the smallest single p-value nor by visual order; return `conflicting_or_weak` unless a declared consistency rule resolves it.
8. Map `effect_to_cause` to the reverse-direction option when that option exists.
9. Emit one option label and text after validation.

## Failure States

- `dependency_missing` or `too_few_points`: no causal answer.
- `mixed_integration_orders`: preserve transformation provenance; prohibit an unqualified causal claim when level and robust alternatives conflict.
- `isolated_significance` or `conflicting_or_weak`: do not force a direction.

## Command

```bash
python skills/tableagent-granger-causality/scripts/execute_analysis.py --file datasets/tableagent_assets/data.xlsx --sheet time_series --cause time_series_1 --effect time_series_2 --max-lag 10 --preprocess auto
```