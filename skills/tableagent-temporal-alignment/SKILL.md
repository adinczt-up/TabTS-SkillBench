---
name: "tableagent-temporal-alignment"
description: "Use for tabular time-series QA that must construct an explicit regular period index, map requested periods to previous or same-season periods, detect missing periods, or align multiple tables on a common month, quarter, or year key. Requires parseable period fields, a declared calendar frequency, and entity keys. Do not use to choose an imputation value, detect value-shift lags, segment events, or answer a timeless lookup."
---

# TableAgent Temporal Alignment

## Trigger Boundary

- Trigger when requested or comparison periods must be generated rather than copied from one row.
- Trigger before forward-fill, interpolation, seasonal-baseline, or period-over-period operations when the regular period grid is not already materialized.
- Do not trigger merely because a table contains a timestamp.
- Boundary: this skill identifies missing cells and comparison keys; a separate analysis rule supplies any imputed value.

## Disable Conditions

Do not use this skill for a single timeless lookup after the exact source cell is known.

## Input Contract

Provide `frequency`, `window_start`, `window_end_exclusive`, `requested_periods`, `comparison_mode`, and `output_period_format`.

- `frequency`: `month`, `quarter`, or `year`.
- `comparison_mode`: `none`, `previous_period`, or `previous_year_same_period`.
- `output_period_format`: `YYYY-MM`, `YYYY-Qn`, or `YYYY`.
- Entity filters and dates are runtime parameters. Never include expected values.

## Mechanical Procedure

1. Input: contract dates. Operation: parse and validate a half-open window. Output: normalized boundaries. Failure: `invalid_window`.
2. Input: frequency and window. Operation: enumerate every expected calendar period. Output: regular period index. Check: adjacent offsets differ by exactly one. Failure: `unsupported_frequency`.
3. Input: requested periods. Operation: normalize them to the declared output format and verify membership in the expected index. Output: ordered requested periods. Failure: `requested_period_outside_window`.
4. Input: requested periods and comparison mode. Operation: map each period mechanically to the previous period or previous year's same period. Output: comparison map. Failure: `comparison_period_unrepresentable`.
5. Input: each source table's normalized period keys. Operation: left-align them to the expected index by entity keys. Output: aligned rows and missing-period flags. Check: no duplicate entity-period keys. Failure: `duplicate_entity_period`.
6. Input: aligned rows. Operation: report missing periods without filling values. Output: validated alignment evidence. Check: chronological ordering and exact output formatting.

## Output Format

Keep an internal period plan:

```json
{
  "status": "ok",
  "frequency": "month",
  "output_period_format": "YYYY-MM",
  "expected_periods": ["YYYY-MM"],
  "requested_periods": ["YYYY-MM"],
  "comparison_map": [{"requested": "YYYY-MM", "comparison": "YYYY-MM"}],
  "missing_periods": [],
  "sort_order": "chronological"
}
```

## Failure States

- `invalid_window` or `unsupported_frequency`: no period-dependent conclusion.
- `requested_period_outside_window`: partial plan allowed; do not report a value for that period.
- `duplicate_entity_period`: no downstream imputation or comparison until the duplicate grain is resolved.
- Missing periods are evidence, not zero values. This skill never fills them.

## Structured Execution

```bash
python skills/tableagent-temporal-alignment/scripts/execute_alignment.py --contract alignment_contract.json --output skill_evidence/tableagent-temporal-alignment.json
python skills/tableagent-temporal-alignment/scripts/validate_result.py --input skill_evidence/tableagent-temporal-alignment.json --output skill_evidence/tableagent-temporal-alignment.validation.json
```
