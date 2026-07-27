---
name: tableagent-derived-calculation
description: Use for spreadsheet QA requiring totals, averages, counts, filtered sums, growth, shares, differences, cumulative values, or unit conversion when source rows, numeric fields, units, and filters can be identified. Establish operation and evidence before calculating. Do not use for direct lookup, start/end interval duration, statistical tests, or unresolved ambiguous wording.
---

# TableAgent Derived Calculation

## Trigger Conditions

Use this skill when the answer is not a direct cell lookup and requires calculating an aggregate, growth, rate, share, difference, duration, cumulative value, or converted units.

## Disable Conditions

Do not use this skill when the source table already contains the exact requested final metric and no calculation is needed. Do not use it to choose among ambiguous columns; bind columns first.

## Trigger Boundary Examples

- Should trigger: "What is the total revenue for rows matching this condition?" Reason: filtered aggregate.
- Should trigger: "What is the average value across all regions?" Reason: derived mean.
- Should trigger: "How many years did all listed people serve?" Reason: duration calculation and aggregation.
- Should not trigger: "What value is in this exact cell?" Reason: direct lookup.
- Should not trigger: "Which column represents league points?" Reason: column binding must happen first.
- Borderline: "What is the total average daily flights?" Reason: parse whether total modifies an average metric or asks for an average; fail with ambiguity if unresolved.

## Steps

1. Parse the requested operation exactly: total, average/mean, count, minimum/maximum, difference, duration, share, growth, or conversion. Do not change total to average or average to total.
2. Bind the row filter separately from the value column. A filter column answers "which rows"; a value column answers "what to aggregate".
3. Record the included row labels and row count before arithmetic. If the count is surprising, re-check the filter.
4. Normalize units before aggregating. Detect header units such as thousands, millions, percent, km2, years, or days; apply the scale once.
5. For duration questions, identify start and end fields, inclusive/exclusive convention, and how to treat current/present rows from the table context. Do not substitute the current calendar year unless the table explicitly uses present/current.
6. Use these formulas:
   - Year-on-year growth = `(current - previous_year_same_period) / previous_year_same_period * 100%`.
   - Month-on-month growth = `(current - previous_period) / previous_period * 100%`.
   - Share = `part / total * 100%`.
   - Difference = `current - comparison` in the same unit.
   - Percentage-point change = `current_percent - comparison_percent`; do not divide again.
   - Cumulative total = sum the included periods once each.
   - Average = sum selected values / number of selected values; do not report the sum.
7. Guard zero or missing denominators; report them instead of fabricating a rate.
8. Keep signs: negative growth means decline. A range like `8.5%-10.5%` is a positive interval, not a negative value.
9. Round only at final presentation unless the question specifies source precision.

## Output Format

For each derived value, keep this internal calculation record and answer with the final value:

```json
{
  "operation": "sum|average|count|duration|growth|share|conversion",
  "filter": "...",
  "value_column": "...",
  "included_rows": ["..."],
  "row_count": 0,
  "formula": "...",
  "inputs": [{"period": "...", "value": 0, "unit": "..."}],
  "result": 0,
  "result_unit": "%"
}
```

## Guardrails

- If the word total modifies an average metric, decide whether the user asks for the sum of an average column or an average across rows. State the chosen operation before computing.
- If a table contains percentages and counts, never sum percentages to answer a population/count question.
- If the output magnitude is off by a factor of 10, 100, 1000, or 1,000,000, re-check unit scaling before finalizing.

## Failure States

- `ambiguous_operation`: Do not output a numeric answer. Ask for or state the ambiguity between total, average, count, or duration.
- `ambiguous_value_column`: Do not aggregate. Bind the metric column first.
- `unit_scale_uncertain`: Output the unscaled calculation only as evidence, not as a final answer.
- `row_filter_unverified`: Do not output a final aggregate; provide included/excluded row evidence.

## Script Validator

Use `scripts/validate_result.py` after preparing a calculation JSON. It validates input fields, recomputes the result from evidence, checks row count, and reports whether the final value is supported.

Command:

```bash
python scripts/validate_result.py --input calculation.json
```

The script expects operation, included_rows, inputs, result, and result_unit. It returns JSON with `valid`, `recomputed`, and `errors`.
