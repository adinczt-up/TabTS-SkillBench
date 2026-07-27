---
name: tableagent-weekpart-contrast
description: Use for grouped time-series questions comparing Monday-Friday means with Saturday-Sunday means over an explicit half-open window, including minimum counts, signed weekday-minus-weekend contrast, and absolute-extremum ties. Requires validated analysis-unit rows and parseable timestamps. Do not use for locale-specific work calendars, holidays, hourly daypart comparisons, or unresolved timezone conversion.
---

# Weekpart Contrast

## Trigger Boundary
- Trigger for weekday versus weekend grouped means under the standard Monday-Friday/Saturday-Sunday definition.
- Do not trigger for business calendars with holidays, shifts, day/night comparisons, or named weekdays individually.
- Boundary: timezone-sensitive timestamps require prior temporal alignment to the declared timezone.

## Input Contract
Require `input`, `group_column`, `time_column`, `value_column`, `window_start`, `window_end_exclusive`, and `minimum_n`. Values and entities are runtime data; expected winners are forbidden.

## Mechanical Procedure
1. Parse timestamps and apply `start <= time < end`.
2. Map Monday-Friday to weekday and Saturday-Sunday to weekend using calendar weekday, not locale labels.
3. Compute full-precision group means and exact analysis-unit counts for both sets.
4. Retain groups meeting both minimum counts.
5. Compute `contrast = weekday_mean - weekend_mean`.
6. Select every group tied for maximum absolute unrounded contrast.
7. Validate against the original source before formatting.

## Output And Failures
Output all group means, counts, contrasts, selected ties, and invariants. Invalid timestamps, insufficient weekpart coverage, timezone ambiguity, or validation failure prohibit the final comparison.

## Structured Execution
```bash
python skills/tableagent-weekpart-contrast/scripts/execute_analysis.py --input prepared.parquet --group-column segment --time-column ts --value-column metric --window-start 2020-01-01 --window-end-exclusive 2021-01-01 --minimum-n 20 --output skill_evidence/tableagent-weekpart-contrast.json
python skills/tableagent-weekpart-contrast/scripts/validate_result.py --input skill_evidence/tableagent-weekpart-contrast.json --output skill_evidence/tableagent-weekpart-contrast.validation.json
```