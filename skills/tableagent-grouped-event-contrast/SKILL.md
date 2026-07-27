---
name: tableagent-grouped-event-contrast
description: Use when prepared grouped records contain an explicit event indicator and the task asks for event versus non-event means, counts, signed effects, or ranked absolute effects. Requires one row per declared analysis unit, numeric values, an explicit event rule, and minimum sample sizes. Do not use to infer events from outcome spikes, compare before/after periods, estimate event windows, or include unmatched records whose event status is unknown.
---

# Grouped Event Contrast

1. Verify the declared analysis-unit grain before invoking this Skill.
2. Exclude unknown event status; never coerce unmatched rows to non-event.
3. Within each group, compute event and non-event counts and means without rounding.
4. Enforce both minimum counts before computing `event_effect=event_mean-nonevent_mean`.
5. Rank on the requested signed or absolute raw effect and deterministic group tie order.
6. Answer only from the structured evidence.

```bash
python skills/tableagent-grouped-event-contrast/scripts/execute_analysis.py --file prepared.parquet --group segment --event event_flag --value metric --min-event 40 --min-nonevent 40 --top-k 3 --output skill_evidence/tableagent-grouped-event-contrast.json
```

Failure states: `duplicate_analysis_unit` must be handled before this Skill; `insufficient_event_rows` is group-local; `no_valid_groups` prohibits a numeric conclusion.
