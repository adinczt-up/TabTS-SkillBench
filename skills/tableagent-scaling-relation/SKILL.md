---
name: tableagent-scaling-relation
description: Use for two-series tabular time-series questions asking whether one series is a scaled, proportional, sign-flipped, or affine copy of another after alignment. Estimate both directions and residual error. Do not use for ordinary grouped OLS slope/intercept/R2 estimation, predictor-response regression, lag construction, Granger causality, distribution equality, or segment amplitude comparison.
---

# Scaling Relation

## Use

Apply when the question asks whether two series share the same shape up to scale, sign flip, or simple affine transformation.

Use `tableagent-grouped-ols-regression` when the requested output is a regression coefficient, intercept, R2, sample size, or ranking across groups.

## Disable Conditions

Do not use for lagged versions unless the lag has already been corrected. Do not use for distribution equality; two series can have related shapes but different distributions.

## Trigger Boundary Examples

- Should trigger: "Is one series a scaled version of the other?" Reason: asks for proportional shape relation.
- Should trigger: "Are these two series flipped versions despite noise?" Reason: asks for sign-flipped relation.
- Should not trigger: "Do the two series have the same distribution?" Reason: distribution equality is not shape scaling.
- Should not trigger: "Does series 1 Granger-cause series 2?" Reason: predictive causality needs Granger testing.
- Borderline: "The series look similar but shifted and scaled." Reason: correct lag first, then apply this skill to the aligned series.

## Procedure

1. Align the two series by index or timestamp and use valid overlap.
2. Inspect whether the question allows intercept. If it says scaled version, test `y = a*x`; if it says affine or transformed, test `y = a*x + b`.
3. Estimate scale robustly using ratios only where the denominator is away from zero, and also fit a least-squares or robust regression.
4. Check sign: positive scale means same orientation; negative scale means flipped orientation.
5. Compute residual error relative to the target series' variation. A relation is supported only when residuals are small compared with signal variation.
6. Verify that high and low features occur at the same aligned indices after scaling.
7. For multiple-choice tasks, choose the option that states the correct direction: series 2 from series 1, series 1 from series 2, flipped, or no relation.

## Input Contract

Required parameters: data file path, sheet name when applicable, series A column, series B column, model type (`scale` or `affine`), whether sign flip is allowed, and residual tolerance. Do not hard-code series names, lag, scale, or option labels in the skill.

## Evidence Record

    model_tested: y=a*x or y=a*x+b
    scale: ...
    intercept: ...
    residual_error: ...
    correlation_after_alignment: ...
    feature_alignment_check: ...
    decision: scaled, flipped, affine, no_relation, or undetermined

## Guardrails

- Raw ratios near zero are unstable; exclude near-zero denominators from ratio summaries.
- Do not require every ratio to be identical when the question allows noise; use residual error and feature alignment.
- Do not infer scaling from distribution similarity alone.

## Failure States

- `insufficient_overlap`: Do not answer; report usable row count.
- `near_zero_denominator`: Do not rely on raw ratios; use regression evidence or fail if regression is unavailable.
- `high_residual_error`: Answer no relation; do not force a scale.
- `direction_ambiguous`: Do not choose between A-from-B and B-from-A without residual evidence.

## Script

Use `scripts/execute_analysis.py` to compute deterministic scaling evidence.

```bash
python scripts/execute_analysis.py --file data.xlsx --sheet time_series --series-a time_series_1 --series-b time_series_2 --model scale
```

Output is JSON containing scale estimates, residual errors for both directions, correlation, and a decision. The natural-language answer must be generated only from that JSON.
