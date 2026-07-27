---
name: tableagent-distribution-comparison
description: Use for two numeric time-series questions asking whether samples share an exact distribution, a location-scale distribution family, or a Gaussian-white-noise family when both have sufficient observations. Distinguish parameter equality from family equality before testing. Do not use for lag, scaling, Granger causality, stationarity, or residual-noise presence unless distribution equality is explicit.
---

# Distribution Comparison

## Trigger Boundary

- Trigger for same underlying distribution, same distribution family, or both Gaussian white noise.
- Do not trigger for time alignment, scaled copies, equal noise variance, or causal direction.
- A question saying only `same underlying distribution` defaults to family comparison unless its options explicitly require equal mean, variance, or complete empirical equality.

## Input Contract

Require file, optional sheet, two series columns, target (`generic` or `gaussian_white_noise`), and comparison (`family` or `exact`). Pass columns and tolerances at runtime.

## Mechanical Procedure

1. Resolve comparison semantics before examining results.
   - `exact`: center and scale are part of equality.
   - `family`: center and scale are nuisance parameters; robustly standardize each sample by its own median and IQR.
   - `gaussian_white_noise`: compare Gaussian-white-noise family; different noise variance alone does not imply a different family.
2. Compute raw center, scale, quantiles, skewness, and excess kurtosis for evidence.
3. For `family`, compare standardized samples using KS distance plus skewness and kurtosis differences. Never reject family equality from raw standard deviation alone.
4. For `exact`, require compatible raw center, scale, and empirical distribution.
5. For Gaussian white noise, additionally require weak serial dependence in each series and approximately Gaussian standardized shape.
6. Treat p-values as supporting evidence. With large samples, use effect-size thresholds for the decision.
7. Validate the result and output exactly one requested option.

## Guardrails

- A scaled Gaussian sample and an unscaled Gaussian sample can share a Gaussian family while failing exact equality.
- Similar mean and variance do not establish the same shape.
- Standardization is prohibited for `exact` comparison and required for `family` comparison.

## Failure States

- `insufficient_samples`: no conclusion.
- `comparison_semantics_unresolved`: state both exact and family outcomes; do not force one.
- `serial_dependence_unchecked`: do not claim Gaussian white noise.

## Commands

```bash
python skills/tableagent-distribution-comparison/scripts/execute_analysis.py --file datasets/tableagent_assets/data.xlsx --sheet time_series --series-a time_series_1 --series-b time_series_2 --target generic --comparison family > distribution.json
python skills/tableagent-distribution-comparison/scripts/validate_result.py --input distribution.json
```