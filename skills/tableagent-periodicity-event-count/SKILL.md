---
name: tableagent-periodicity-event-count
description: Use for tabular time-series questions about recurring cycles, period length, period change, repeated peaks, square-wave edge intervals, or recurring-event counts around an anchor when ordered timestamps and enough repeated cycles are available. Do not use for isolated transitions, anomalous-row counts, or event morphology without recurring structure.
---

# Periodicity And Event Count

## Use

Apply to recurring structure. Do not use for one-off transitions or when ordered coverage is unavailable.

## Trigger Boundary Examples

- Should trigger: "How many spike-like events occurred after an anchor time?" Reason: recurring event count with anchor filtering.
- Should trigger: "How does the period change from beginning to end?" Reason: compares observed cycle intervals.
- Should trigger: "Does the series repeat every couple of days?" Reason: period estimation.
- Should not trigger: "How many sudden drops occurred in one stable phase?" Reason: one-off event segmentation, not periodicity.
- Should not trigger: "Is the series stationary?" Reason: statistical stationarity is separate.
- Borderline: "How many peaks are after this time?" Reason: use this if peaks are recurring cycle events; otherwise use event segmentation.

## Procedure

1. Verify the time range and sampling regularity before estimating any period.
2. Identify the waveform class: sinusoid, square wave, pulse/spike train, or irregular recurring event.
3. Choose the primary event marker: peaks for sinusoids, rising/falling edges for square waves, local maxima/minima for spikes. Use one timestamp per cycle or event.
4. If the question asks whether a period changes, partition the covered series into requested or natural early and late windows before estimating either period.
5. Estimate each period from observed intervals between compatible markers. Use autocorrelation or spectrum only as supporting evidence.
6. Use a second compatible method when the waveform is noisy or the first estimate is ambiguous.
7. Record the window boundaries, method, observed cycles, and period in observations and elapsed time.
8. For event counts, construct event timestamps before applying before/after filtering.
9. Build an anchor record when the question mentions an anchor time or anchor event: anchor timestamp, event containing the anchor, event onset, event peak, event end, and whether the wording includes or excludes that anchor event.
10. Apply the anchor rule only after event timestamps exist. If the wording says after an event or after a sudden change, exclude the event that contains the anchor timestamp; count only later independent events. Include the anchor event only when wording says from, since, starting at, including, or beginning with.
11. For cycle-peak counts after an anchor, do not count the peak of the same cycle if the anchor timestamp is already inside that cycle's rise or event. The first counted event must have an onset after the anchor-containing event ends.

## Input Contract

Required parameters are file, optional sheet, timestamp column, value column, target (period, period_change, or event_count), marker type, and minimum cycle count. Period-change also requires two non-overlapping windows. Anchor counts require anchor timestamp, inclusion wording, and event onset/end records. All task-specific values are runtime parameters.

## Evidence Record

    window_name: early, late, full, or requested
    start: ...
    end: ...
    method: ...
    period_observations: ...
    period_time: ...
    supporting_cycle_count: ...
    event_timestamps: ...
    anchor_record: ...
    anchor_inclusion_rule: include or exclude

## Guardrails

- A claim that a period changed requires at least two comparable windows.
- Do not extrapolate a period from an uninspected suffix.
- Do not count every sample in a peak or ramp as a recurring event.
- Report ambiguity when several periods fit equally well.
- For period-change questions, compare interval distributions, not just first and last sample values.
- For square waves, period is edge-to-same-edge distance; high-state or low-state duration is half-period unless the question asks for state duration.
- For after/before wording, filter events by event identity, not just timestamp. A timestamp after the anchor can still belong to the same anchor event and should be excluded when the wording asks for later events.

## Handoff

Answer with the requested period or count after the evidence record is complete.

## Failure States

- `insufficient_cycles`: partial marker list allowed; prohibit period or period-change claims; extend coverage.
- `marker_type_ambiguous`: no count; declare the waveform/marker rule.
- `incomparable_windows`: report each window only; prohibit increase/decrease claims.
- `anchor_event_unresolved`: prohibit after/before count; segment the anchor-containing event first.
- `period_method_conflict`: report estimates as undetermined; inspect markers and sampling.
- `evidence_mismatch`: no final answer; repair marker/event evidence.

## Validator

```bash
python scripts/validate_result.py --input periodicity_result.json
```

The validator checks chronological markers, minimum cycles, comparable period windows, anchor inclusion, recomputed event counts, failure-state behavior, and evidence-bounded final claims.
