---
name: tableagent-waveform-amplitude-comparison
description: Use for tabular time-series questions that compare waveform amplitude, range, oscillation size, or amplitude change between segments or series when numeric observations cover at least one cycle per segment. Do not use for mean level, vertical offset, trend, period, variance, or noise magnitude unless amplitude itself is explicitly requested.
---

# Waveform Amplitude Comparison

## Trigger Boundary

- Should trigger: "Did the oscillation amplitude increase after the waveform changed?" The target is segment amplitude.
- Should trigger: "Which series has the larger amplitude?" The target is comparable oscillation size.
- Should not trigger: "Did the average level increase?" Mean level is not amplitude.
- Should not trigger: "Did the period increase?" Periodicity is a separate property.
- Borderline: "Did variability increase?" Trigger only if waveform context defines variability as oscillation amplitude; otherwise use variance or noise diagnosis.

## Input Contract

Provide `file`, optional `sheet`, `series`, and either segment boundaries or a deterministic split rule. Optional parameters are `method`, `quantile`, and `minimum_cycles`. Pass all task-specific timestamps, indices, and labels as parameters. Never encode an expected option or benchmark answer.

## Procedure

1. Input: ordered numeric series and segment boundaries. Operation: remove missing values separately within each segment. Output: segment row counts. Check: each segment contains at least one complete oscillation. Failure: `insufficient_segment_coverage`.
2. Input: cleaned segments. Operation: compute robust low/high levels using the requested quantiles; default to 5th and 95th percentiles. Output: low, high, center, peak-to-peak range, and semi-amplitude `(high-low)/2`. Check: use the same definition for every segment. Failure: `incomparable_definitions`.
3. Input: segment evidence. Operation: compare semi-amplitudes by ratio and normalized difference. Output: `increase`, `decrease`, `same`, or `undetermined`. Default same-band is relative difference at most the configured tolerance; default tolerance is 15%.
4. Input: centers and extrema. Operation: verify that a vertical offset was not mistaken for amplitude. Output: offset check. Failure: `level_amplitude_confusion` when the claimed direction follows maxima but not peak-to-peak ranges.
5. Input: structured result. Operation: run `scripts/execute_analysis.py` and `scripts/validate_result.py`; derive the natural-language answer only from validated JSON. Output: one requested option or direct comparison.

## Method Selection

- Default: quantile semi-amplitude for noisy sinusoidal, square, pulse, or mixed waveforms.
- Switch to half peak-to-peak only when the data are clean and extrema are stable.
- Use fitted sinusoid amplitude only when both segments are sinusoidal and each has at least two cycles.
- If methods disagree beyond tolerance, return `method_conflict`; do not choose an option.

## Output Contract

    status: ok|failed
    method: quantile|peak_to_peak|sinusoid_fit
    segments: [{name, n, low, high, center, peak_to_peak, semi_amplitude}]
    amplitude_ratio: ...
    relative_difference: ...
    decision: increase|decrease|same|undetermined
    checks: ...
    failure_state: ...

## Failure States

- `insufficient_segment_coverage`: partial summaries allowed; no amplitude-change conclusion; extend the window.
- `incomparable_definitions`: no conclusion; recompute every segment with one method.
- `level_amplitude_confusion`: no conclusion; compare peak-to-peak or semi-amplitude instead of maxima.
- `method_conflict`: report both estimates; no forced option; inspect waveform class and boundaries.

## Script

```bash
python scripts/execute_analysis.py --file data.xlsx --sheet time_series --series value --split-index 512 --tolerance 0.15
python scripts/validate_result.py --input amplitude_result.json
```

The script accepts Excel or CSV input, emits JSON, exits `0` for a supported decision and `1` for a failure state, and asserts non-overlapping nonempty segments, finite amplitudes, and a decision recomputable from the reported values.
