from __future__ import annotations

import json
import math
import re
import unicodedata
from typing import Any

from benchmark_eval.schema import TraceRecord


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return re.sub(r"\s+", " ", text)


def extract_payload(text: str) -> tuple[list[dict[str, Any]] | None, str]:
    candidates = [
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.I | re.S)
    ]
    candidates.append(text.strip())
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for index, char in enumerate(candidate):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                value = [value]
            if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                return value, "json"
    return None, "no_json_array"


def values_equal(
    actual: Any,
    expected: Any,
    *,
    absolute_tolerance: float = 1e-9,
    relative_tolerance: float = 0.0,
) -> bool:
    if isinstance(expected, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            actual_number = float(actual)
        except (TypeError, ValueError):
            return False
        return math.isfinite(actual_number) and math.isclose(
            actual_number,
            float(expected),
            rel_tol=relative_tolerance,
            abs_tol=absolute_tolerance,
        )
    if expected is None:
        return actual is None
    return normalize_text(actual) == normalize_text(expected)


def score_answer(
    actual_rows: list[dict[str, Any]] | None,
    expected_rows: list[dict[str, Any]],
    key_fields: list[str],
    numeric_tolerances: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if actual_rows is None:
        return {
            "passed": False,
            "partial_credit_score": 0.0,
            "partial_credit_f1": 0.0,
            "row_precision": 0.0,
            "row_recall": 0.0,
            "row_f1": 0.0,
            "field_precision": 0.0,
            "field_recall": 0.0,
            "field_f1": 0.0,
            "extra_row_count": 0,
            "duplicate_key_count": 0,
            "schema_exact": False,
            "matched_rows": 0,
            "actual_rows": 0,
            "expected_rows": len(expected_rows),
            "diagnostics": [{"status": "unparseable_output"}],
        }

    def row_key(row: dict[str, Any]) -> tuple[str, ...] | None:
        if any(field not in row for field in key_fields):
            return None
        return tuple(normalize_text(row[field]) for field in key_fields)

    actual_by_key: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in actual_rows:
        key = row_key(row)
        if key is not None:
            actual_by_key.setdefault(key, []).append(row)

    total_fields = sum(len(row) for row in expected_rows)
    correct_fields = 0
    matched_rows = 0
    schema_exact = True
    diagnostics = []
    for expected in expected_rows:
        key = row_key(expected)
        candidates = actual_by_key.get(key or (), [])
        if not candidates:
            diagnostics.append({"key": key, "status": "missing_row"})
            continue
        matched_rows += 1
        actual = candidates[0]
        mismatches = []
        unexpected = sorted(set(actual) - set(expected))
        if unexpected:
            schema_exact = False
        for field, expected_value in expected.items():
            if field not in actual:
                schema_exact = False
                mismatches.append(
                    {"field": field, "expected": expected_value, "actual": "<missing>"}
                )
            else:
                tolerance = (numeric_tolerances or {}).get(field) or {}
                absolute_tolerance = float(tolerance.get("absolute_tolerance", 1e-9))
                relative_tolerance = float(tolerance.get("relative_tolerance", 0.0))
                equal = values_equal(
                    actual[field],
                    expected_value,
                    absolute_tolerance=absolute_tolerance,
                    relative_tolerance=relative_tolerance,
                )
                if equal:
                    correct_fields += 1
                else:
                    mismatches.append(
                        {
                            "field": field,
                            "expected": expected_value,
                            "actual": actual[field],
                            "absolute_tolerance": absolute_tolerance,
                            "relative_tolerance": relative_tolerance,
                        }
                    )
        diagnostics.append(
            {
                "key": key,
                "status": "matched" if not mismatches and not unexpected else "field_mismatch",
                "mismatches": mismatches,
                "unexpected_fields": unexpected,
            }
        )

    expected_count = len(expected_rows)
    actual_count = len(actual_rows)
    predicted_fields = sum(len(row) for row in actual_rows)
    row_precision = matched_rows / actual_count if actual_count else 0.0
    row_recall = matched_rows / expected_count if expected_count else 1.0
    row_f1 = (
        2 * row_precision * row_recall / (row_precision + row_recall)
        if row_precision + row_recall
        else 0.0
    )
    field_precision = correct_fields / predicted_fields if predicted_fields else 0.0
    field_recall = correct_fields / total_fields if total_fields else 1.0
    field_f1 = (
        2 * field_precision * field_recall / (field_precision + field_recall)
        if field_precision + field_recall
        else 0.0
    )
    duplicate_key_count = sum(max(len(rows) - 1, 0) for rows in actual_by_key.values())
    exact = (
        matched_rows == expected_count
        and actual_count == expected_count
        and correct_fields == total_fields
        and schema_exact
    )
    return {
        "passed": exact,
        # Retained for paper-result compatibility. New analyses should prefer
        # partial_credit_f1, which penalizes extra fields and rows.
        "partial_credit_score": field_recall,
        "partial_credit_f1": field_f1,
        "row_precision": row_precision,
        "row_recall": row_recall,
        "row_f1": row_f1,
        "field_precision": field_precision,
        "field_recall": field_recall,
        "field_f1": field_f1,
        "extra_row_count": max(actual_count - matched_rows, 0),
        "duplicate_key_count": duplicate_key_count,
        "schema_exact": schema_exact,
        "matched_rows": matched_rows,
        "actual_rows": actual_count,
        "expected_rows": expected_count,
        "diagnostics": diagnostics,
    }


def prf(gold: set[str], predicted: set[str]) -> tuple[float, float, float]:
    if not gold and not predicted:
        return 1.0, 1.0, 1.0
    precision = len(gold & predicted) / len(predicted) if predicted else 0.0
    recall = len(gold & predicted) / len(gold) if gold else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def _skill_metrics(trace: TraceRecord, contract: dict[str, Any]) -> dict[str, Any]:
    usage = trace.skill_usage or {}
    if trace.locator.condition == "baseline" or usage.get("skill_mode") == "off":
        return {
            "skill_retrieval_precision": None,
            "skill_retrieval_recall": None,
            "skill_retrieval_f1": None,
            "skill_execution_precision": None,
            "skill_execution_recall": None,
            "skill_execution_f1": None,
            "skill_validation_rate": None,
            "skill_order_alignment": None,
            "skill_read_count": None,
            "skill_execution_count": None,
        }
    gold = set(contract.get("required_skills") or [])
    execution_gold = set(
        contract.get("required_execution_skills")
        or contract.get("required_skills")
        or []
    )
    predicted = set(
        usage.get("selected_skills")
        or usage.get("read_skills")
        or []
    )
    observed_scripts: dict[str, list[dict[str, Any]]] = {}
    for call in trace.tool_calls:
        arguments = call.get("arguments") or {}
        command = str(arguments.get("command", arguments.get("cmd", "")))
        for skill in gold | execution_gold | set(usage.get("allowed_skills") or []):
            pattern = rf"skills[\\/]{re.escape(skill)}[\\/]scripts[\\/][^\s\"']+\.py"
            if re.search(pattern, command, re.I):
                observed_scripts.setdefault(skill, []).append(call)
    executed = set(observed_scripts) | set(usage.get("structured_skills") or [])
    rp, rr, rf = prf(gold, predicted)
    ep, er, ef = prf(execution_gold, executed)
    skill_items = usage.get("skills") or {}
    executed_for_validation = sorted(executed)
    validation_values = []
    validation_disabled = bool(usage.get("validation_disabled_by_ablation"))
    for name in executed_for_validation:
        item = skill_items.get(name) or {}
        if validation_disabled:
            validation_values.append(False)
            continue
        validator_calls = [
            call
            for call in observed_scripts.get(name, [])
            if re.search(
                rf"skills[\\/]{re.escape(name)}[\\/]scripts[\\/]validate[^\s\"']*\.py",
                str(
                    (call.get("arguments") or {}).get(
                        "command",
                        (call.get("arguments") or {}).get("cmd", ""),
                    )
                ),
                re.I,
            )
        ]
        if validator_calls:
            validation_values.append(
                any(call.get("exit_code") == 0 for call in validator_calls)
            )
        elif item.get("validation_required"):
            validation_values.append(bool(item.get("validation_valid")))
        elif item.get("structured_evidence_valid") is not None:
            validation_values.append(bool(item.get("structured_evidence_valid")))
    validation_rate = (
        sum(validation_values) / len(validation_values)
        if validation_values
        else None
    )

    ordered = []
    for name, item in skill_items.items():
        lines = list(item.get("script_call_lines") or item.get("read_file_lines") or [])
        if lines:
            ordered.append((min(lines), name))
    predicted_order = [name for _, name in sorted(ordered)]
    gold_order = list(
        contract.get("skill_execution_order")
        or contract.get("required_execution_skills")
        or contract.get("skill_order")
        or []
    )
    gold_pairs = {
        (gold_order[i], gold_order[j])
        for i in range(len(gold_order))
        for j in range(i + 1, len(gold_order))
    }
    predicted_positions = {name: index for index, name in enumerate(predicted_order)}
    comparable = {
        pair
        for pair in gold_pairs
        if pair[0] in predicted_positions and pair[1] in predicted_positions
    }
    order_score = (
        sum(
            predicted_positions[left] < predicted_positions[right]
            for left, right in comparable
        )
        / len(comparable)
        if comparable
        else None
    )
    return {
        "skill_retrieval_precision": rp,
        "skill_retrieval_recall": rr,
        "skill_retrieval_f1": rf,
        "skill_execution_precision": ep,
        "skill_execution_recall": er,
        "skill_execution_f1": ef,
        "skill_validation_rate": validation_rate,
        "skill_order_alignment": order_score,
        "skill_read_count": len(predicted),
        "skill_execution_count": len(executed),
    }


REQUIRED_OPERATION_MATCH: dict[str, set[str]] = {
    "period_compare": {"filter"},
    "absolute_change": {"filter"},
    "extremum": {"ranking"},
    "coverage": {"filter"},
    "gap_detection": {"filter"},
    "alignment": {"period_aggregate", "shift"},
    "shift": {"shift"},
    "event_rate": {"period_aggregate", "filter"},
    "event_window": {"filter", "event_detection"},
    "regression": {"regression"},
    "lag": {"shift"},
    "correlation": {"correlation"},
    "ranking": {"ranking"},
    "period_aggregate": {"period_aggregate"},
    "linear_trend": {"regression"},
    "forecast": {"forecast"},
    "seasonal_lookup": {"shift", "period_aggregate"},
    "rolling_window": {"rolling_window"},
    "backtest": {"rolling_window", "forecast"},
    "selection": {"ranking"},
    "forward_fill": {"forward_fill"},
    "interpolation": {"interpolation"},
    "seasonal_imputation": {"period_aggregate"},
    "quantile": {"quantile"},
    "anomaly_detection": {"event_detection", "quantile"},
    "median_absolute_deviation": {"robust_scale"},
    "event_detection": {"event_detection"},
    "change_point": {"event_detection"},
    "volatility": {"period_aggregate"},
    "spread": {"quantile"},
    "two_stage_extremum": {"ranking", "period_aggregate"},
    "weekday_weekend": {"period_aggregate"},
    "seasonal_profile": {"period_aggregate"},
    "state_segmentation": {"event_detection"},
    "duration": {"filter"},
    "autocorrelation": {"correlation"},
}


def _relational_metrics(trace: TraceRecord, contract: dict[str, Any]) -> dict[str, Any]:
    gold = set(contract.get("required_tables") or [])
    predicted = set(trace.tables_read)
    candidates = set(contract.get("candidate_tables") or [])
    distractors = candidates - gold
    tp, tr, tf = prf(gold, predicted)
    relation = contract.get("relational_contract") or {}
    # F1, rather than recall alone, makes reading every visible table costly
    # when the workspace contains realistic distractors.
    components = [tf]
    required_join = bool(relation.get("required"))
    if required_join:
        required_join_count = int(relation.get("required_join_count") or 1)
        observed_join_count = sum(
            int(operation.get("join_count") or 1)
            for operation in trace.join_operations
        )
        components.append(min(observed_join_count / required_join_count, 1.0))
    gold_keys = set(relation.get("using_keys") or [])
    gold_keys.update(
        edge.get("left_key")
        for edge in relation.get("on_edges") or []
        if edge.get("left_key")
    )
    gold_keys.update(
        edge.get("right_key")
        for edge in relation.get("on_edges") or []
        if edge.get("right_key")
    )
    observed_keys: set[str] = set()
    for operation in trace.join_operations:
        observed_keys.update(str(value) for value in operation.get("using_keys") or [])
        observed_keys.update(str(value) for value in operation.get("merge_keys") or [])
        for edge in operation.get("on_edges") or []:
            if len(edge) == 4:
                observed_keys.update((str(edge[1]), str(edge[3])))
    if gold_keys:
        _, _, key_f1 = prf(
            {key.casefold() for key in gold_keys},
            {key.casefold() for key in observed_keys},
        )
        components.append(key_f1)
    return {
        "table_retrieval_precision": tp,
        "table_retrieval_recall": tr,
        "table_retrieval_f1": tf,
        "relational_execution_accuracy": sum(components) / len(components),
        "relational_join_coverage": components[1] if required_join else None,
        "relational_join_key_f1": components[-1] if gold_keys else None,
        "candidate_table_count": len(candidates),
        "distractor_table_count": len(distractors),
        "distractor_tables_read": sorted(predicted & distractors),
        "distractor_table_read_rate": (
            len(predicted & distractors) / len(distractors) if distractors else None
        ),
        "distractor_avoidance_rate": (
            1.0 - len(predicted & distractors) / len(distractors)
            if distractors and predicted
            else None
        ),
        "relational_metric_quality": "command_observed",
    }


def _temporal_anchor_tokens(
    trace: TraceRecord,
    temporal: dict[str, Any],
) -> tuple[set[str], set[str], set[str], set[str]]:
    anchors = list(temporal.get("anchors") or [])
    if not anchors:
        anchors = [
            {"role": "anchor", "value": value, "boundary": None}
            for value in temporal.get("time_literals") or []
        ]
    gold: set[str] = set()
    predicted: set[str] = {f"date:{value}" for value in trace.timestamps_used}
    gold_boundaries: set[str] = set()
    predicted_boundaries: set[str] = set()
    command_text = "\n".join(trace.commands).casefold()

    def contains(pattern: str) -> bool:
        return bool(re.search(pattern, command_text, re.I | re.S))

    for anchor in anchors:
        role = str(anchor.get("role") or "anchor")
        value = str(anchor.get("value") or "")
        if not value:
            continue
        escaped = re.escape(value)
        date_token = f"date:{value}"
        role_token = f"role:{role}:{value}"
        gold.update((date_token, role_token))
        date_seen = value in trace.timestamps_used
        role_seen = role == "anchor" and date_seen
        if role == "scope_start":
            role_seen = date_seen and (
                contains(rf"(?:>=|>)\s*(?:pd\.timestamp\s*\()?['\"]?{escaped}")
                or contains(rf"\b(?:start|from|begin)\w*\b[^\n]{{0,40}}{escaped}")
            )
        elif role == "scope_end":
            role_seen = date_seen and (
                contains(rf"(?:<=|<)\s*(?:pd\.timestamp\s*\()?['\"]?{escaped}")
                or contains(rf"\b(?:end|until|stop)\w*\b[^\n]{{0,40}}{escaped}")
            )
        elif role == "split":
            role_seen = date_seen and (
                contains(rf"\b(?:split|cutoff|origin)\w*\b[^\n]{{0,40}}{escaped}")
                or (
                    contains(rf"(?:<=|<)\s*['\"]?{escaped}")
                    and contains(rf"(?:>=|>)\s*['\"]?{escaped}")
                )
            )
        if role_seen:
            predicted.add(role_token)

        boundary = anchor.get("boundary")
        if boundary in {"inclusive", "exclusive"}:
            boundary_token = f"boundary:{role}:{value}:{boundary}"
            gold.add(boundary_token)
            gold_boundaries.add(boundary_token)
            if role == "scope_start":
                exact = contains(rf">=\s*(?:pd\.timestamp\s*\()?['\"]?{escaped}")
            else:
                operator = "<" if boundary == "exclusive" else "<="
                exact = contains(rf"{re.escape(operator)}\s*(?:pd\.timestamp\s*\()?['\"]?{escaped}")
            if exact:
                predicted.add(boundary_token)
                predicted_boundaries.add(boundary_token)
    return gold, predicted, gold_boundaries, predicted_boundaries


def _temporal_metrics(trace: TraceRecord, contract: dict[str, Any]) -> dict[str, Any]:
    temporal = contract.get("temporal_contract") or {}
    required_dates = set(temporal.get("time_literals") or [])
    observed_dates = set(trace.timestamps_used)
    anchor_gold, anchor_predicted, gold_boundaries, predicted_boundaries = (
        _temporal_anchor_tokens(trace, temporal)
    )
    date_precision, date_recall_prf, date_f1 = prf(
        anchor_gold,
        anchor_predicted,
    )
    date_recall = (
        len(required_dates & observed_dates) / len(required_dates)
        if required_dates
        else 1.0
    )
    boundary_coverage = (
        len(gold_boundaries & predicted_boundaries) / len(gold_boundaries)
        if gold_boundaries
        else None
    )
    observed_ops = set(trace.temporal_operations)
    required_ops = list(temporal.get("required_operations") or [])
    op_hits = []
    for operation in required_ops:
        acceptable = REQUIRED_OPERATION_MATCH.get(operation, {operation})
        op_hits.append(bool(acceptable & observed_ops))
    operation_recall = sum(op_hits) / len(op_hits) if op_hits else 1.0
    relevant_observed_ops = {
        observed
        for observed in observed_ops
        if any(
            observed in REQUIRED_OPERATION_MATCH.get(required, {required})
            for required in required_ops
        )
    }
    operation_precision = (
        len(relevant_observed_ops) / len(observed_ops)
        if observed_ops
        else (1.0 if not required_ops else 0.0)
    )
    operation_f1 = (
        2 * operation_precision * operation_recall
        / (operation_precision + operation_recall)
        if operation_precision + operation_recall
        else 0.0
    )
    required_granularities = set(temporal.get("required_granularities") or [])
    observed_granularities = set(trace.temporal_granularities)
    granularity_precision = granularity_recall = granularity_f1 = None
    if required_granularities:
        (
            granularity_precision,
            granularity_recall,
            granularity_f1,
        ) = prf(required_granularities, observed_granularities)
    required_dependencies = {
        tuple(value)
        for value in temporal.get("required_dependencies") or []
        if isinstance(value, (list, tuple)) and len(value) == 2
    }
    projected_sequence: list[str] = []
    for observed in trace.temporal_operation_sequence:
        matches = [
            required
            for required in required_ops
            if observed in REQUIRED_OPERATION_MATCH.get(required, {required})
        ]
        for match in matches:
            if not projected_sequence or projected_sequence[-1] != match:
                projected_sequence.append(match)
    observed_dependencies = set(zip(projected_sequence, projected_sequence[1:]))
    dependency_precision = dependency_recall = dependency_f1 = None
    if required_dependencies:
        dependency_precision, dependency_recall, dependency_f1 = prf(
            required_dependencies,
            observed_dependencies,
        )

    required_parameters = set(temporal.get("required_parameters") or [])
    observed_parameters = set(trace.temporal_parameters)

    def parameter_match(required: str) -> bool:
        if required in observed_parameters:
            return True
        required_parts = required.split(":")
        if len(required_parts) != 3:
            return False
        _, value, unit = required_parts
        for observed in observed_parameters:
            parts = observed.split(":")
            if len(parts) != 3 or parts[1] != value:
                continue
            if parts[2] == unit or parts[2] == "period" or unit == "period":
                return True
        return False

    parameter_accuracy = (
        sum(parameter_match(value) for value in required_parameters)
        / len(required_parameters)
        if required_parameters
        else None
    )

    # TG-F1 concerns only temporal anchors and scope literals. Operations,
    # granularity and parameters belong to TEA and are intentionally excluded.
    grounding_f1 = date_f1 if required_dates else None

    tea_components = [
        value
        for value in (
            granularity_f1,
            operation_f1 if required_ops else None,
            dependency_f1,
            parameter_accuracy,
        )
        if value is not None
    ]
    temporal_execution_accuracy = (
        sum(tea_components) / len(tea_components) if tea_components else None
    )

    evidence_components = [
        bool(observed_dates) if required_dates else None,
        bool(observed_granularities) if required_granularities else None,
        bool(observed_ops) if required_ops else None,
        len(projected_sequence) >= 2 if required_dependencies else None,
        bool(observed_parameters) if required_parameters else None,
    ]
    applicable_evidence = [value for value in evidence_components if value is not None]
    temporal_evidence_coverage = (
        sum(bool(value) for value in applicable_evidence) / len(applicable_evidence)
        if applicable_evidence
        else None
    )

    leakage_policy = temporal.get("leakage_policy") or {}
    command_text = "\n".join(trace.commands).casefold()
    leakage_violations: list[str] = []
    analysis_end = leakage_policy.get("analysis_end_exclusive")
    if analysis_end and any(value > str(analysis_end) for value in observed_dates):
        leakage_violations.append("timestamp_after_analysis_end")
    if leakage_policy.get("forbid_centered_window") and re.search(
        r"center\s*=\s*true", command_text
    ):
        leakage_violations.append("centered_window")
    if leakage_policy.get("forbid_future_shift") and re.search(
        r"\.shift\(\s*-\d+|\blead\s*\(", command_text
    ):
        leakage_violations.append("future_shift")
    if leakage_policy.get("forbid_backward_fill") and re.search(
        r"\bbfill\s*\(|backfill|method\s*=\s*['\"]bfill", command_text
    ):
        leakage_violations.append("backward_fill")
    train_cutoff = leakage_policy.get("train_cutoff")
    if train_cutoff and re.search(r"\b(?:fit|polyfit|train)\s*\(", command_text):
        if str(train_cutoff) not in command_text:
            leakage_violations.append("unbounded_training_fit")
    leakage_free = (
        not leakage_violations
        if leakage_policy.get("required")
        and (trace.commands or trace.timestamps_used or trace.temporal_operations)
        else None
    )

    constraint_components = [
        grounding_f1,
        granularity_f1,
        operation_f1 if required_ops else None,
        dependency_f1,
        parameter_accuracy,
        float(leakage_free) if leakage_free is not None else None,
    ]
    applicable_constraints = [
        float(value) for value in constraint_components if value is not None
    ]
    constraint_compliance = (
        sum(applicable_constraints) / len(applicable_constraints)
        if applicable_constraints
        else None
    )
    strict_compliance = (
        all(value == 1.0 for value in applicable_constraints)
        if applicable_constraints
        else None
    )
    # Backward-compatible aliases retained for old report consumers.
    tga = (date_recall + operation_recall) / 2
    tga_v2 = grounding_f1
    return {
        "temporal_scope_precision": date_precision if required_dates else None,
        "temporal_scope_recall": date_recall,
        "temporal_scope_f1": date_f1 if required_dates else None,
        "temporal_boundary_coverage": boundary_coverage,
        "temporal_operation_precision": operation_precision,
        "temporal_operation_recall": operation_recall,
        "temporal_operation_f1": operation_f1,
        "temporal_granularity_precision": granularity_precision,
        "temporal_granularity_recall": granularity_recall,
        "temporal_granularity_alignment": granularity_f1,
        "temporal_dependency_precision": dependency_precision,
        "temporal_dependency_recall": dependency_recall,
        "temporal_dependency_f1": dependency_f1,
        "temporal_parameter_accuracy": parameter_accuracy,
        "temporal_grounding_f1": grounding_f1,
        "temporal_execution_accuracy": temporal_execution_accuracy,
        "temporal_evidence_coverage": temporal_evidence_coverage,
        "temporal_grounding_accuracy": tga,
        "temporal_grounding_accuracy_v2": tga_v2,
        "temporal_constraint_compliance": constraint_compliance,
        "temporal_strict_compliance": strict_compliance,
        "leakage_free": leakage_free,
        "leakage_violations": leakage_violations,
        "temporal_metric_quality": "command_observed",
    }


def score_trace(
    trace: TraceRecord,
    task: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    infrastructure_error = trace.status in {"missing_run", "infrastructure_error"}
    answer_contract = contract.get("answer_contract") or {}
    payload, extraction = extract_payload(trace.final_answer)
    raw_payload, _ = extract_payload(
        trace.pre_repair_final_answer or trace.final_answer
    )
    answer = score_answer(
        payload,
        list(answer_contract.get("gold_rows") or []),
        list(answer_contract.get("key_fields") or []),
        dict(answer_contract.get("numeric_tolerances") or {}),
    )
    raw_answer = score_answer(
        raw_payload,
        list(answer_contract.get("gold_rows") or []),
        list(answer_contract.get("key_fields") or []),
        dict(answer_contract.get("numeric_tolerances") or {}),
    )
    relation = _relational_metrics(trace, contract)
    temporal = _temporal_metrics(trace, contract)
    skill = _skill_metrics(trace, contract)
    if infrastructure_error:
        for key in (
            "table_retrieval_precision", "table_retrieval_recall",
            "table_retrieval_f1", "relational_execution_accuracy",
            "relational_join_coverage", "relational_join_key_f1",
            "distractor_table_read_rate", "distractor_avoidance_rate",
        ):
            relation[key] = None
        for key in list(temporal):
            if key not in {"leakage_violations", "temporal_metric_quality"}:
                temporal[key] = None
        for key in list(skill):
            skill[key] = None
    valid_completion = (
        None if infrastructure_error
        else trace.status == "completed" and payload is not None
    )
    grounded = (
        None
        if infrastructure_error
        else bool(
            answer["passed"]
            and relation["table_retrieval_recall"] == 1.0
            and trace.tool_calls
        )
    )
    tokens = None
    if trace.prompt_tokens is not None or trace.completion_tokens is not None:
        tokens = int(trace.prompt_tokens or 0) + int(trace.completion_tokens or 0)
    return {
        "task_id": trace.locator.task_id,
        "framework": trace.locator.framework,
        "model": trace.locator.model,
        "condition": trace.locator.condition,
        "repeat": trace.locator.repeat,
        "run_id": trace.locator.run_id,
        "dataset": contract.get("dataset"),
        "task_family": contract.get("task_family"),
        "difficulty": contract.get("difficulty"),
        "status": trace.status,
        "failure_reason": trace.failure_reason,
        "passed": None if infrastructure_error else bool(answer["passed"]),
        "strict_success": None if infrastructure_error else float(bool(answer["passed"])),
        "raw_strict_success": (
            None if infrastructure_error else float(bool(raw_answer["passed"]))
        ),
        "after_repair_strict_success": (
            None if infrastructure_error else float(bool(answer["passed"]))
        ),
        "repair_attempted": (
            None
            if infrastructure_error
            else float(trace.final_answer_repair_attempt_count > 0)
        ),
        "repair_succeeded": (
            None
            if infrastructure_error or trace.final_answer_repair_attempt_count == 0
            else float(trace.final_answer_repair_success_count > 0)
        ),
        "whole_task_attempt_count": trace.whole_task_attempt_count,
        "infrastructure_retry_count": trace.infrastructure_retry_count,
        "partial_credit_score": None if infrastructure_error else answer["partial_credit_score"],
        "partial_credit_f1": None if infrastructure_error else answer["partial_credit_f1"],
        "row_precision": None if infrastructure_error else answer["row_precision"],
        "row_recall": None if infrastructure_error else answer["row_recall"],
        "row_f1": None if infrastructure_error else answer["row_f1"],
        "field_precision": None if infrastructure_error else answer["field_precision"],
        "field_recall": None if infrastructure_error else answer["field_recall"],
        "field_f1": None if infrastructure_error else answer["field_f1"],
        "extra_row_count": None if infrastructure_error else answer["extra_row_count"],
        "duplicate_key_count": (
            None if infrastructure_error else answer["duplicate_key_count"]
        ),
        "schema_exact": None if infrastructure_error else answer["schema_exact"],
        "valid_completion": valid_completion,
        "evidence_grounded_success": grounded,
        "evidence_metric_quality": "heuristic",
        "extraction": extraction,
        **relation,
        **temporal,
        **skill,
        "prompt_tokens": trace.prompt_tokens,
        "completion_tokens": trace.completion_tokens,
        "cached_tokens": trace.cached_tokens,
        "total_tokens": tokens,
        "duration_seconds": trace.duration_seconds,
        "tool_call_count": len(trace.tool_calls),
        "command_count": len(trace.commands),
        "tables_read": trace.tables_read,
        "required_tables": contract.get("required_tables") or [],
        "observed_temporal_operations": trace.temporal_operations,
        "observed_temporal_operation_sequence": trace.temporal_operation_sequence,
        "required_temporal_operations": (
            contract.get("temporal_contract") or {}
        ).get("required_operations")
        or [],
        "observed_temporal_granularities": trace.temporal_granularities,
        "observed_temporal_parameters": trace.temporal_parameters,
        "required_temporal_granularities": (
            contract.get("temporal_contract") or {}
        ).get("required_granularities")
        or [],
        "required_temporal_dependencies": (
            contract.get("temporal_contract") or {}
        ).get("required_dependencies")
        or [],
        "required_temporal_parameters": (
            contract.get("temporal_contract") or {}
        ).get("required_parameters")
        or [],
        "skills_read": (trace.skill_usage or {}).get("read_skills") or [],
        "skills_executed": sorted(
            set((trace.skill_usage or {}).get("script_skills") or [])
            | set((trace.skill_usage or {}).get("structured_skills") or [])
        ),
        "required_skills": contract.get("required_skills") or [],
        "required_execution_skills": contract.get("required_execution_skills") or [],
        "answer_score": answer,
        "raw_result_path": trace.raw_result_path,
    }
