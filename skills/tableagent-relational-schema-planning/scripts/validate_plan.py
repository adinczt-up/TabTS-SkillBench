#!/usr/bin/env python3
"""Validate a relation and analysis-grain plan without using expected answers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ALLOWED_MEASURE_SEMANTICS = {
    "state_or_intensity", "additive_flow", "event_count", "indicator", "rate"
}
ALLOWED_ABSENCE_POLICIES = {
    "not_applicable", "preserve_null", "zero_means_no_event"
}
ALLOWED_CHILD_TIME_POLICIES = {
    "ignore_child_time", "filter_child_to_parent_window", "filter_child_to_explicit_window"
}


def load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("input must be a JSON object")
    return data


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    selection = data.get("table_selection") or {}
    unit = data.get("analysis_unit") or {}
    measure = data.get("measure") or {}
    roles = data.get("role_bindings") or {}
    population = data.get("population") or {}
    checks = data.get("post_join_checks") or {}
    edges = data.get("join_path") or []

    selected = selection.get("selected_tables") or []
    rejected = selection.get("rejected_tables") or {}
    concept_map = selection.get("concept_table_map") or {}
    if not isinstance(selected, list) or not selected:
        errors.append("table_selection.selected_tables must be a nonempty list")
        selected = []
    if len(selected) != len(set(selected)):
        errors.append("table_selection.selected_tables contains duplicates")
    if not isinstance(rejected, dict):
        errors.append("table_selection.rejected_tables must map tables to reasons")
        rejected = {}
    if any(not str(reason).strip() for reason in rejected.values()):
        errors.append("every rejected table requires a nonempty reason")
    if set(selected) & set(rejected):
        errors.append("a table cannot be both selected and rejected")
    if not isinstance(concept_map, dict) or not concept_map:
        errors.append("table_selection.concept_table_map must be nonempty")
    elif any(not str(target).strip() for target in concept_map.values()):
        errors.append("every requested concept requires a table-column mapping")
    if selection.get("minimal_sufficient") is not True:
        errors.append("table_selection.minimal_sufficient must be true")

    if not unit.get("keys") or not unit.get("time_grain"):
        errors.append("analysis_unit requires nonempty keys and time_grain")
    if not unit.get("analysis_time_owner"):
        errors.append("analysis_unit.analysis_time_owner is required")
    if measure.get("semantics") not in ALLOWED_MEASURE_SEMANTICS:
        errors.append("measure.semantics is invalid")
    if not measure.get("within_unit_aggregate"):
        errors.append("measure.within_unit_aggregate is required")
    outcome = roles.get("outcome_measure") or {}
    event = roles.get("event_indicator") or {}
    for field in ("table", "column", "unit", "within_unit_aggregate"):
        if not str(outcome.get(field, "")).strip():
            errors.append(f"role_bindings.outcome_measure.{field} is required")
    if selected and outcome.get("table") not in selected:
        errors.append("outcome measure source table must be selected")
    event_declared = bool(event)
    if event_declared:
        for field in ("table", "column", "within_unit_aggregate"):
            if not str(event.get(field, "")).strip():
                errors.append(f"role_bindings.event_indicator.{field} is required")
        if selected and event.get("table") not in selected:
            errors.append("event indicator source table must be selected")
        same_source = outcome.get("table") == event.get("table") and outcome.get("column") == event.get("column")
        if same_source and roles.get("same_source_role_justification") not in {"requested_measure_is_event_indicator", "requested_measure_is_event_count"}:
            errors.append("outcome measure and event indicator share a source without a valid role justification")
    requested_measure = str(measure.get("requested_concept", "")).strip()
    if not requested_measure:
        errors.append("measure.requested_concept is required")
    elif isinstance(concept_map, dict):
        mapped = concept_map.get(requested_measure)
        expected = f"{outcome.get('table')}.{outcome.get('column')}"
        if isinstance(mapped, str) and mapped != expected:
            errors.append("requested outcome concept does not map to the declared outcome source")
    if not population.get("definition") or not population.get("anchor_table"):
        errors.append("population definition and anchor_table are required")
    elif selected and population.get("anchor_table") not in selected:
        errors.append("population.anchor_table must be selected")
    anchor_n = population.get("anchor_unit_count")
    if not isinstance(anchor_n, int) or anchor_n < 0:
        errors.append("population.anchor_unit_count must be a nonnegative integer")
    if not isinstance(edges, list):
        errors.append("join_path must be a list")
        edges = []
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"join_path[{index}] must be an object")
            continue
        if not edge.get("left") or not edge.get("right") or not edge.get("keys"):
            errors.append(f"join_path[{index}] requires left, right, and keys")
        if selected and (
            edge.get("left") not in selected or edge.get("right") not in selected
        ):
            errors.append(f"join_path[{index}] references a non-selected table")
        cardinality = edge.get("expected_cardinality")
        if cardinality in {"one_to_many", "many_to_many"} and not edge.get("right_preaggregated"):
            errors.append(f"join_path[{index}] has unsafe cardinality without preaggregation")
        policy = edge.get("absence_policy", "not_applicable")
        if policy not in ALLOWED_ABSENCE_POLICIES:
            errors.append(f"join_path[{index}] has invalid absence_policy")
        if policy != "not_applicable" and edge.get("join_type") != "left":
            errors.append(f"join_path[{index}] optional facts require a left join")
        child_time_policy = edge.get("child_time_policy")
        if child_time_policy not in ALLOWED_CHILD_TIME_POLICIES:
            errors.append(f"join_path[{index}] has invalid child_time_policy")
        if child_time_policy == "filter_child_to_explicit_window" and not edge.get("child_time_window"):
            errors.append(f"join_path[{index}] explicit child-time filter requires child_time_window")

    integer_checks = (
        "output_row_count", "unique_analysis_unit_count",
        "duplicate_analysis_unit_count", "lost_anchor_unit_count",
        "unmatched_child_key_count",
    )
    for field in integer_checks:
        if not isinstance(checks.get(field), int) or checks[field] < 0:
            errors.append(f"post_join_checks.{field} must be a nonnegative integer")
    if checks.get("duplicate_analysis_unit_count") != 0:
        errors.append("analysis units are duplicated after join")
    if checks.get("lost_anchor_unit_count") != 0:
        errors.append("anchor units were lost after join")
    if isinstance(anchor_n, int) and checks.get("unique_analysis_unit_count") != anchor_n:
        errors.append("unique analysis-unit count does not equal anchor count")
    if checks.get("output_row_count") != checks.get("unique_analysis_unit_count"):
        errors.append("output is not one row per analysis unit")
    if checks.get("measure_preserved") is not True:
        errors.append("source measure was not preserved across joins")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    errors = validate(load(args.input))
    report = {"status": "failed" if errors else "ok", "valid": not errors, "errors": errors}
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
