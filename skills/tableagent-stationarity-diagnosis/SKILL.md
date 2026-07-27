---
name: tableagent-stationarity-diagnosis
description: Use for ordered numeric time-series questions explicitly asking about mean stability, variance stability, covariance stationarity, stationarity after differencing, seasonal stationarity, or stationary versus non-stationary anomalies when multiple comparable windows are available. Do not use for a single full-series variance, distribution equality, noise type, Granger causality, or periodicity without a stationarity claim.
---

# Stationarity Diagnosis

## Trigger Boundary

- Trigger for covariance stationarity, stability over time, stationarity after differencing, or stationarity within seasonal phases.
- Do not trigger for a single variance value, noise label, repeated-cycle count, or two-sample distribution comparison.
- For a periodic series, use this skill only when the question asks whether cycle-specific statistical properties remain stable.

## Input Contract

Require file, optional sheet, ordered series column, target (`mean`, `variance`, `covariance`, `differencing`, `seasonal`, or `anomaly`), and window count. Require a seasonal period for `seasonal`. Pass all columns and periods at runtime.

## Mechanical Procedure

1. Validate ordering and retain at least 32 finite observations with at least eight observations per window.
2. Select exactly one target before computing evidence. Do not apply every stationarity test to every question.
3. Compute equal-window means, variances, normalized end-to-end trend, and normalized ACF differences.
4. Treat finite-sample variance fluctuation as evidence of instability only when the max/min variance ratio exceeds 1.5 and a median-centered Brown-Forsythe test rejects at `alpha=0.01`. A raw ratio or p-value alone is insufficient.
5. For covariance stationarity, require mean, variance, and normalized ACF evidence to agree. Do not compare raw autocovariance when window variances differ; raw scale changes mechanically alter covariance.
6. For differencing, evaluate the differenced series directly. ADF rejection alone cannot establish stationarity.
7. For seasonal stationarity, reshape into complete cycles and compare cycle means, scales, and correlation with the median seasonal profile. Do not fit a separate trend to every phase unless at least 12 complete cycles exist.
8. For anomaly stationarity, require at least two independent failures among mean, variance, and ACF stability before labeling the anomaly non-stationary.
9. Run the validator. Map the structured decision to exactly one requested option.

## Conflict Rules

- Window ratio below 1.5 overrides small p-value fluctuations: retain `variance_stable`.
- ADF/KPSS disagreement with stable target-specific evidence yields `undetermined`, not automatic non-stationarity.
- Fewer than four complete seasonal cycles yields `seasonal_period_or_cycles_insufficient`.

## Output Contract

Return target, window evidence, normalized effect sizes, formal-test evidence, decision, and failure state. The natural-language answer may only use the structured decision.

## Commands

```bash
python skills/tableagent-stationarity-diagnosis/scripts/execute_analysis.py --file datasets/tableagent_assets/data.xlsx --sheet time_series --series time_series_1 --target covariance --windows 4 > stationarity.json
python skills/tableagent-stationarity-diagnosis/scripts/validate_result.py --input stationarity.json
```