---
name: tableagent-event-period-response
description: Use when event periods are explicitly defined by an event flag, count, or rate and the task asks for same-group change relative to a specified previous or next calendar period. Requires prepared group-period metric and event columns. Do not use to infer events from metric spikes, estimate event episodes, compare arbitrary distant windows, or discover an unknown lag.
---

# Event Period Response

## Procedure

1. Verify one row per group-period and parse the requested calendar frequency.
2. Apply the explicit event predicate to the event column; do not infer events from the response metric.
3. Construct comparison pairs by calendar-key join within group. A missing previous calendar period yields no pair; never substitute the previous retained row.
4. Compute the declared direction, defaulting only when stated to `event_value - reference_value`.
5. Rank by the requested unrounded signed or absolute field, then deterministic group/period tie order.
6. Emit all eligible pairs and selected rows. Round only the final answer.

## Failure States

- `duplicate_group_period`, `event_rule_missing`, `direction_unbound`, `no_calendar_pair`.

## Command

```bash
python skills/tableagent-event-period-response/scripts/execute_analysis.py --file prepared.csv --group segment --time month --value value --event event_rate --event-op gt --event-threshold 0 --reference-offset -1 --frequency month --top-k 3
```
