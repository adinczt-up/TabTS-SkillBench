---
name: tableagent-metric-binding
description: Use for spreadsheet QA that must bind question wording to entity rows, metric columns, units, or periods when table headers, aliases, merged cells, or similarly named fields create competing candidates. Resolve candidates before lookup or calculation. Do not use when the exact row and value column are already unambiguous.
---

# Metric Binding

## Use

Apply whenever a question metric could map to more than one row or column. Do not use after exact source cells are already established.

## Trigger Boundary Examples

- Should trigger: "Which points column answers this league-table question?" Reason: competing exact and qualified metric headers.
- Should trigger: "Find the value for a metric with merged headers." Reason: requires complete header construction.
- Should trigger: "Use the 2001 general election column, not similarly named columns." Reason: period-qualified binding.
- Should not trigger: "Average the values after the column is already selected." Reason: derived calculation should aggregate.
- Should not trigger: "Count recurring events in a time series." Reason: not a table metric binding problem.
- Borderline: "How many points did the team score?" Reason: in standings tables prefer exact `points`; if wording explicitly says points-for, bind qualified column.

## Procedure

1. Parse the question into entity, metric, unit, period, and requested operation.
2. Construct complete headers from merged or multi-row labels.
3. List all candidate columns that match the metric tokens or aliases.
4. Prefer an exact normalized header match over a longer or related header.
5. Treat qualifiers as meaning-changing: for example, for, against, rate, share, rank, total, average, growth, and cumulative are distinct metrics.
6. In standings-style sports tables containing played/won/drawn/lost and `points`, bind generic season points to exact `points`. Do not substitute `points for`, `points against`, goals for, or runs for unless the wording explicitly asks for scored-for, conceded, points-for, goals-for, or offensive production.
7. If more than one candidate remains, inspect sample values, units, and neighboring headers; record why the selected column matches the requested metric and why the others do not.
8. Bind the entity row after normalization, preserving the original label.
9. Record the binding before performing a lookup or aggregation.

## Binding Record

    entity_requested: ...
    entity_row_label: ...
    metric_requested: ...
    candidate_columns: ...
    selected_column: ...
    excluded_columns: ...
    unit: ...
    period: ...
    confidence: high, medium, or low

## Guardrails

- Do not replace an exact metric with a related metric merely because the related column is nearby.
- Do not use substring matching as the final decision when qualifiers differ.
- Stop and disclose ambiguity when a defensible binding cannot be established.
- For a simple lookup, stop after the bound cell is identified and answer directly.
- When the wording is ambiguous but one candidate is an exact header and another is a qualified header, prefer the exact header and mention the ambiguity briefly.
