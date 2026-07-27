---
name: tableagent-noise-structure-diagnosis
description: Use for tabular time-series questions asking whether the raw series is white noise, whether residual noise is practically significant, what residual noise type is present, or whether residual variance is additive or multiplicative. Select the analysis target before selecting a signal model. Do not use for MAD/IQR anomaly ranking, raw-series distribution equality, stationarity, Granger causality, or generic variance lookup.
---

# Noise Structure Diagnosis

## Use

Apply only when noise behavior is the requested property. A raw white-noise-process question analyzes the centered raw series; all other targets analyze residuals after an explicit signal model.

## Trigger Boundary Examples

- Should trigger: "What type of noise is present?" Reason: asks residual noise classification.
- Should trigger: "Is the noise additive or multiplicative?" Reason: asks variance form of residuals.
- Should trigger: "Do both series have the same noise level?" Reason: compares residual noise variance after signal removal.
- Should not trigger: "Do the raw series have the same distribution?" Reason: distribution comparison is separate.
- Should not trigger: "Is the raw variance stable over time?" Reason: stationarity diagnosis is separate unless noise type is requested.
- Borderline: "Is this white noise?" Reason: use this when the question asks noise process; use stationarity only when stationarity is the target.

## Procedure

1. Input: question. Operation: choose exactly one target from the table below. Output: target. Check: do not combine targets. Failure: ambiguous_noise_target.

| User target | Script target | Analysis series | Default model |
|---|---|---|---|
| Is the given series itself white noise? | raw_white_noise | centered raw series | raw |
| Is residual noise present or negligible? | presence | residual | auto |
| Is residual dependence white or autocorrelated? | dependence | residual | auto |
| What named residual noise type is present? | noise_type | residual | auto |
| Is residual noise additive or multiplicative? | variance_form | residual | auto |

2. Input: target and ordered series. Operation: if target is raw_white_noise, center the raw series and prohibit smoothing, detrending, or rolling-median fitting. Output: raw-centered analysis series. Check: signal_model must equal raw. Failure: wrong_analysis_series.
3. Input: a residual target. Operation: select the simplest signal model whose robust residual scale is within 10% of the smallest candidate scale: constant, then linear, then rolling median. Output: fitted signal and residuals. Check: retain the resolved model. Failure: signal_model_unverified.
4. Input: raw-centered series or residuals. Operation: compute short-lag ACF and a portmanteau p-value. Output: white when p is at least 0.05, otherwise autocorrelated. Check: do not reject whiteness because one of many lags barely crosses an unadjusted bound.
5. Input: residual target. Operation: compare robust residual scale with signal level or range. Output: none or meaningful. Check: perform this before naming a residual noise type.
6. Input: noise_type evidence. Operation: return no_significant_noise when presence is none; otherwise return gaussian_white_noise only when dependence is white and skewness or kurtosis are compatible, or red_noise when dependence is positive and autocorrelated. Output: one type or undetermined.
7. Input: variance_form evidence. Operation: use a 9-point local-median signal by default, split absolute fitted-signal magnitude into at least three populated bins, and compare residual spread. Output: multiplicative only when spread ratio is at least 1.5 and its bin trend is at least 0.8; otherwise additive or undetermined.
8. Input: structured JSON. Operation: run the validator and map only decision to the final answer. Output: one requested option. Failure: any failure state prohibits a forced label.

## Input Contract

Required parameters are data file, optional sheet, series column, and target. Signal model defaults to auto, except raw_white_noise always forces raw. Optional parameters are rolling window, relative-noise threshold, and maximum ACF lag. All dataset-specific values must be passed at runtime.

## Evidence Record

    signal_model: ...
    analysis_series: raw_centered or residual
    residual_scale: ...
    source_precision: ...
    acf_summary: ...
    portmanteau_result: ...
    residual_spread_by_signal_bin: ...
    noise_presence: none or meaningful
    dependence: white, autocorrelated, or undetermined
    variance_form: additive, multiplicative, or undetermined
    noise_type: no_significant_noise, gaussian_white_noise, red_noise, or undetermined

## Guardrails

- No significant autocorrelation does not mean no noise.
- White describes serial dependence; do not call it Gaussian without a distribution check.
- Do not diagnose raw trending values as residual noise.
- Never smooth or detrend the series when the target is whether the raw series itself is white noise.
- State undetermined when the fitted signal or residual evidence is inadequate.
- For multiple-choice tasks, stop after selecting the supported option; do not continue refining the model.
- Do not call tiny numerical jitter Gaussian white noise when the practical question offers no significant noise.

## Failure States

- `ambiguous_noise_target`: no partial classification; restate the requested property.
- `wrong_analysis_series`: no conclusion; rerun the raw white-noise target without signal fitting.
- `too_few_points`: summary only; do not label noise; obtain a longer series.
- `signal_model_unverified`: no residual-noise conclusion; provide or estimate signal structure.
- `residuals_negligible`: answer only the presence target as no significant noise; prohibit Gaussian/red/additive/multiplicative labels.
- `insufficient_level_bins`: allow presence/dependence evidence; prohibit additive/multiplicative conclusion.
- `conflicting_diagnostics`: report undetermined; do not select an option.

## Script

    python skills/tableagent-noise-structure-diagnosis/scripts/execute_analysis.py --file datasets/tableagent_assets/data.xlsx --sheet time_series --series value --target raw_white_noise
    python skills/tableagent-noise-structure-diagnosis/scripts/execute_analysis.py --file datasets/tableagent_assets/data.xlsx --sheet time_series --series value --target noise_type --signal-model auto
    python skills/tableagent-noise-structure-diagnosis/scripts/validate_result.py --input noise_result.json

The execution script emits structured JSON. The validator recomputes relative scale, presence, and requested-target decision and rejects claims under failure states.
