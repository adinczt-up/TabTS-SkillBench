---
name: tableagent-lag-direction-validation
description: Use for two-series questions whose target is lead/lag direction, delay, shifted-copy alignment, or lag magnitude. Verify direction with direct equations. Do not use as the regression executor when lag is already specified by the question; use grouped OLS with an explicit calendar lag instead. Also exclude Granger causality, generic correlation, unequal-pattern series, and calendar alignment without value-shift claims.
---

# Lag Direction Validation

## Use

Apply to shifted similarity between aligned series. Do not use to establish Granger causality, causal mechanism, or contemporaneous correlation.

## Procedure

1. Align both series to the same time resolution and use only valid overlap.
2. Record any offset, scale, or detrending transformation used for shape comparison.
3. Evaluate a bounded range of positive and negative lags using cross-correlation or alignment error.
4. Re-test the best lag with direct shift equations instead of relying on library sign convention:
   - `B[k:] ~= A[:-k]` means B is the lagged/delayed version of A by k steps.
   - `A[k:] ~= B[:-k]` means A is the lagged/delayed version of B by k steps.
5. Select the direction with lower alignment error only if overlap remains adequate and competing lags are clearly weaker.
6. Verify direction explicitly with both natural-language equations: A at later time equals earlier B, or B at later time equals earlier A.
7. Retain one matched timestamp or index pair that demonstrates which series occurs first.
8. Map the verified direction to the exact question wording before answering. If the question asks "Is series B a lagged version of series A?", answer Yes only for `B[k:] ~= A[:-k]`; answer No with reverse direction when `A[k:] ~= B[:-k]`.
9. For multiple-choice tasks, choose exactly one option label and text. Do not output only `[lag, n]`, arrays, or intermediate diagnostics.

## Evidence Record

    lag_steps: ...
    lag_time: ...
    tested_equations: ...
    verified_equation: ...
    leader: ...
    follower: ...
    overlap_rows: ...
    match_score: ...
    selected_option: ...

## Guardrails

- Library sign conventions alone are not evidence of direction.
- A follower is the series observed later.
- Report ambiguity rather than selecting among tied periodic lags.
- A high correlation at a signed lag is not enough; the direct shifted arrays must match the proposed wording.
- Always translate direction into the user's wording after computing the lag.
