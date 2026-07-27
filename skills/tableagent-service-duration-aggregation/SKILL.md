---
name: tableagent-service-duration-aggregation
description: Use for tabular questions computing tenure, service, term, elapsed time, or occupancy duration from explicit start/end endpoints when each source row is already an interval. Resolve endpoint granularity, inclusive coverage, and ongoing rows explicitly. Do not use for consecutive high/low time-series states, runs inferred from adjacent observations, a supplied duration column, event gaps, or observation counts.
---

# Service Duration Aggregation

## Trigger Boundary

Trigger when duration must be derived from interval endpoints. Do not trigger when the table already supplies the requested duration or when rows are observations rather than intervals.

If duration must first be inferred by thresholding an ordered series into consecutive states, use `tableagent-consecutive-state-runs`; those rows are observations, not source intervals.

## Mechanical Procedure

1. Retain source row IDs and verify every included row is one service interval.
2. Parse endpoint granularity as full date or year-only. Never convert `Current` to the machine's current date without an explicit as-of date.
3. Resolve exactly one duration method:
   - full dates -> elapsed days / 365.2425 by default;
   - completed/full years -> completed calendar years;
   - year-only endpoints representing boundaries -> `end_year - start_year`;
   - year-only endpoints representing covered service years -> `end_year - start_year + 1`.
4. Infer year semantics from table structure. If at least 95% of adjacent rows share an end/start transition year, use `year_difference` to avoid double-counting. Otherwise, a legitimate same-year interval indicates covered-year semantics and requires `inclusive_years`.
5. Resolve ongoing rows before aggregation:
   - explicit as-of date -> compute through that date;
   - wording asks completed historical intervals and no as-of exists -> exclude the ongoing row and record it;
   - otherwise return `ongoing_end_unresolved`.
6. Do not filter titles or roles unless the question explicitly excludes rows. A table containing acting or interim holders still represents listed service intervals unless wording says otherwise.
7. Compute unrounded per-row durations, then aggregate once. Validate the row count and recomputation.
8. Render every month field as `YYYY-MM`, quarter as `YYYY-Qn`, and year as `YYYY` when the question requests period labels. Do not emit a full date for a month label.

## Failure States

- `duration_convention_ambiguous`: return both candidate conventions; no forced total.
- `ongoing_end_unresolved`: no machine-date substitution.
- `invalid_interval` or `overlapping_intervals`: prohibit the full aggregate until resolved.

## Commands

```bash
python skills/tableagent-service-duration-aggregation/scripts/execute_analysis.py --file datasets/tableagent_assets/data.xlsx --sheet data --start-column Start --end-column End --operation sum --method auto --ongoing-policy exclude > duration.json
python skills/tableagent-service-duration-aggregation/scripts/validate_result.py --input duration.json
```
