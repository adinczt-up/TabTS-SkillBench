from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from benchmark_eval.utils import load_json, write_json, write_jsonl

DATE_RE = re.compile(r"\b(?:19|20)\d{2}-\d{2}(?:-\d{2})?\b")
USING_RE = re.compile(r"\bUSING\s*\(([^)]+)\)", re.I)
ON_KEY_RE = re.compile(
    r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)",
    re.I,
)


FAMILY_OPERATIONS: dict[str, list[str]] = {
    "entity_consistency": ["period_compare", "absolute_change", "extremum"],
    "coverage_gap_detection": ["coverage", "gap_detection"],
    "temporal_shift": ["alignment", "shift"],
    "event_contrast": ["event_rate", "period_compare"],
    "event_rate_shift": ["event_rate", "period_compare"],
    "event_window_response": ["event_window", "period_compare"],
    "event_sensitivity_regression": ["regression", "event_rate"],
    "lagged_predictor_regression": ["lag", "regression"],
    "lagged_cross_correlation": ["lag", "correlation"],
    "rank_reversal": ["period_compare", "ranking"],
    "two_period_rank_reversal": ["period_compare", "ranking"],
    "trend_slope": ["period_aggregate", "linear_trend"],
    "linear_trend_forecast": ["period_aggregate", "linear_trend", "forecast"],
    "seasonal_naive_forecast": ["alignment", "seasonal_lookup", "forecast"],
    "rolling_backtest_selection": ["rolling_window", "backtest", "selection"],
    "forward_fill_imputation": ["alignment", "forward_fill"],
    "linear_interpolation_imputation": ["alignment", "interpolation"],
    "seasonal_median_imputation": ["alignment", "seasonal_imputation"],
    "iqr_anomaly_detection": ["quantile", "anomaly_detection"],
    "mad_anomaly_detection": ["median_absolute_deviation", "anomaly_detection"],
    "rolling_threshold_detection": ["rolling_window", "event_detection"],
    "change_point_detection": ["change_point"],
    "volatility_regime_shift": ["period_compare", "volatility"],
    "monthly_volatility": ["period_aggregate", "volatility"],
    "tail_spread": ["quantile", "spread"],
    "peak_month": ["period_aggregate", "two_stage_extremum"],
    "weekday_contrast": ["weekday_weekend", "period_compare"],
    "seasonal_profile_shift": ["seasonal_profile", "period_compare"],
    "state_duration_analysis": ["state_segmentation", "duration"],
    "cohort_retention_shift": ["cohort", "retention", "period_compare"],
    "autocorrelation_structure": ["autocorrelation"],
}

LEAKAGE_SENSITIVE_FAMILIES = {
    "event_window_response",
    "forward_fill_imputation",
    "lagged_cross_correlation",
    "lagged_predictor_regression",
    "linear_interpolation_imputation",
    "linear_trend_forecast",
    "rolling_backtest_selection",
    "rolling_threshold_detection",
    "seasonal_median_imputation",
    "seasonal_naive_forecast",
}

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "twenty-four": 24,
}


def _question_text(task: dict[str, Any]) -> str:
    return "\n".join(
        str(turn.get("question") or "")
        for turn in task.get("turns") or []
        if isinstance(turn, dict)
    )


def _number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    return NUMBER_WORDS.get(value.casefold())


def _temporal_parameter_tokens(text: str) -> list[str]:
    """Extract parameter values whose semantics are explicitly temporal.

    Tokens intentionally omit absolute dates because those are evaluated by
    temporal grounding rather than by execution-parameter accuracy.
    """
    lowered = text.casefold()
    tokens: set[str] = set()
    number = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty-four)"
    for match in re.finditer(
        rf"\b({number})[- ]+(?:calendar[- ]+)?(hours?|days?|weeks?|months?|quarters?|years?)\b",
        lowered,
    ):
        value = _number(match.group(1))
        if value is None:
            continue
        unit = match.group(2).rstrip("s")
        tokens.add(f"duration:{value}:{unit}")
    for match in re.finditer(r"\bt\s*([+-])\s*(\d+)\s*([hdwmy])\b", lowered):
        unit = {"h": "hour", "d": "day", "w": "week", "m": "month", "y": "year"}[match.group(3)]
        sign = 1 if match.group(1) == "+" else -1
        tokens.add(f"offset:{sign * int(match.group(2))}:{unit}")
    for match in re.finditer(
        rf"\b(?:lag|horizon|window|rolling)\D{{0,16}}({number})\s*(hours?|days?|weeks?|months?|quarters?|years?)?",
        lowered,
    ):
        value = _number(match.group(1))
        if value is None:
            continue
        unit = (match.group(2) or "period").rstrip("s")
        tokens.add(f"parameter:{value}:{unit}")
    return sorted(tokens)

GRANULARITY_PATTERNS: dict[str, tuple[str, ...]] = {
    "hour": ("hour", "hourly"),
    "day": ("day", "daily", "machine-day", "building-day"),
    "week": ("week", "weekly", "weekday", "weekend"),
    "month": ("month", "monthly"),
    "quarter": ("quarter", "quarterly"),
    "year": ("year", "yearly", "annual"),
    "season": ("season", "seasonal"),
    "event": ("event", "race", "transaction", "post"),
}


def _infer_granularities(metadata: dict[str, Any]) -> list[str]:
    parameters = metadata.get("task_parameters") or {}
    semantic = metadata.get("semantic_contract") or {}
    candidates = [
        parameters.get("frequency"),
        parameters.get("period"),
        parameters.get("granularity"),
        parameters.get("observation_unit"),
        semantic.get("observation_unit"),
        semantic.get("frequency"),
        semantic.get("granularity"),
    ]
    candidates.extend(parameters.keys())
    candidates.extend(parameters.values())
    candidates.extend(semantic.keys())
    candidates.extend(semantic.values())
    text = " ".join(str(value).casefold() for value in candidates if value)
    found = []
    for granularity, patterns in GRANULARITY_PATTERNS.items():
        if any(re.search(rf"\b{re.escape(pattern)}s?\b", text) for pattern in patterns):
            found.append(granularity)
    return found


def _source(task: dict[str, Any]) -> str:
    metadata = task.get("metadata") or {}
    if metadata.get("source"):
        return str(metadata["source"])
    for tag in task.get("tags") or []:
        if tag not in {"skillmtts", "multi_table", "temporal", "hard", "reviewed"}:
            return str(tag)
    return "unknown"


def _required_tables(task: dict[str, Any]) -> list[str]:
    metadata = task.get("metadata") or {}
    values = metadata.get("required_tables") or []
    if values:
        return list(dict.fromkeys(str(value) for value in values))
    return list(
        dict.fromkeys(
            Path(str(asset.get("path", ""))).stem
            for asset in task.get("data_assets") or []
            if asset.get("path")
        )
    )


def _join_contract(metadata: dict[str, Any], required_tables: list[str]) -> dict[str, Any]:
    sql = str(metadata.get("oracle_sql") or "")
    using_keys = []
    for match in USING_RE.finditer(sql):
        using_keys.extend(
            value.strip().strip('"`[]')
            for value in match.group(1).split(",")
            if value.strip()
        )
    on_edges = []
    for match in ON_KEY_RE.finditer(sql):
        on_edges.append(
            {
                "left_alias": match.group(1),
                "left_key": match.group(2),
                "right_alias": match.group(3),
                "right_key": match.group(4),
            }
        )
    return {
        "required": len(required_tables) > 1,
        "minimum_table_count": len(required_tables),
        # The oracle may contain auxiliary joins that do not contribute to the
        # requested output. The minimum connected plan is the stable contract.
        "required_join_count": len(required_tables) - 1,
        "using_keys": sorted(set(using_keys)),
        "on_edges": on_edges,
        "target_granularity": (
            metadata.get("task_parameters", {}).get("observation_unit")
            or metadata.get("semantic_contract", {}).get("observation_unit")
            or ""
        ),
        "quality": "measured" if sql else "task_metadata",
    }


def _temporal_contract(
    task: dict[str, Any],
    metadata: dict[str, Any],
    family: str,
) -> dict[str, Any]:
    parameters = metadata.get("task_parameters") or {}
    semantic = metadata.get("semantic_contract") or {}
    question = _question_text(task)
    parameter_dates: list[str] = []
    for value in parameters.values():
        if isinstance(value, str):
            parameter_dates.extend(DATE_RE.findall(value))
    question_dates = DATE_RE.findall(question)
    # Only dates exposed by the task are valid grounding targets. Hidden
    # generator parameters and oracle-only dates must never affect the score.
    dates = sorted(set(question_dates))
    start_candidates = [
        str(parameters[key])
        for key in parameters
        if key.casefold()
        in {"start", "start_date", "window_start", "training_start", "scope_start"}
        and isinstance(parameters[key], str)
        and DATE_RE.fullmatch(str(parameters[key]))
    ]
    end_candidates = [
        str(parameters[key])
        for key in parameters
        if key.casefold()
        in {
            "end",
            "end_date",
            "window_end",
            "cutoff",
            "forecast_origin",
            "scope_end",
        }
        and isinstance(parameters[key], str)
        and DATE_RE.fullmatch(str(parameters[key]))
    ]
    start_candidates = [value for value in start_candidates if value in dates]
    end_candidates = [value for value in end_candidates if value in dates]
    scope_start = start_candidates[0] if start_candidates else (dates[0] if dates else None)
    scope_end = end_candidates[-1] if end_candidates else (dates[-1] if dates else None)
    anchors: list[dict[str, Any]] = []
    role_keys = {
        "scope_start": ("start", "start_date", "window_start", "training_start", "scope_start"),
        "scope_end": ("end", "end_date", "window_end", "scope_end"),
        "split": ("split", "cutoff", "forecast_origin"),
    }
    assigned_dates: set[str] = set()
    half_open = bool(re.search(r"half[- ]open|\[[^\]]+\)", question, re.I))
    for role, keys in role_keys.items():
        values = [
            str(parameters[key])
            for key in keys
            if key in parameters
            and isinstance(parameters[key], str)
            and DATE_RE.fullmatch(str(parameters[key]))
            and str(parameters[key]) in dates
        ]
        for value in values:
            boundary = None
            if role == "scope_start":
                boundary = "inclusive" if half_open else "unspecified"
            elif role == "scope_end":
                boundary = "exclusive" if half_open else "unspecified"
            anchors.append({"role": role, "value": value, "boundary": boundary})
            assigned_dates.add(value)
    for value in dates:
        if value not in assigned_dates:
            anchors.append({"role": "anchor", "value": value, "boundary": None})
    required_operations = list(
        semantic.get("required_operations")
        or FAMILY_OPERATIONS.get(family, [])
    )
    operation_sequence = list(
        semantic.get("required_operation_sequence")
        or semantic.get("operation_sequence")
        or required_operations
    )
    dependencies = [
        [operation_sequence[index], operation_sequence[index + 1]]
        for index in range(len(operation_sequence) - 1)
    ]
    split = parameters.get("split")
    leakage_sensitive = bool(
        semantic.get("leakage_sensitive", family in LEAKAGE_SENSITIVE_FAMILIES)
    )
    return {
        "required": True,
        "time_literals": dates,
        "anchors": anchors,
        "scope_start": scope_start,
        "scope_end_exclusive": scope_end,
        "scope_boundaries": [
            value for value in (scope_start, scope_end) if value is not None
        ],
        "frequency": parameters.get("frequency") or parameters.get("period") or "",
        "required_granularities": _infer_granularities(metadata),
        "required_operations": required_operations,
        "required_operation_sequence": operation_sequence,
        "required_dependencies": dependencies,
        "required_parameters": _temporal_parameter_tokens(question),
        "leakage_policy": {
            "required": leakage_sensitive,
            "analysis_end_exclusive": parameters.get("end") or scope_end,
            "train_cutoff": split if leakage_sensitive else None,
            "forbid_centered_window": leakage_sensitive,
            "forbid_future_shift": family.startswith("lagged_")
            or family in {"linear_trend_forecast", "rolling_backtest_selection"},
            "forbid_backward_fill": family == "forward_fill_imputation",
            "quality": "task_metadata",
        },
        "quality": "task_metadata",
    }


def build_contract(task: dict[str, Any]) -> dict[str, Any]:
    metadata = task.get("metadata") or {}
    family = str(metadata.get("task_family") or "unknown")
    required_tables = _required_tables(task)
    skills = list(dict.fromkeys(str(value) for value in task.get("skills") or []))
    execution_skills = list(
        dict.fromkeys(
            str(value)
            for value in (
                task.get("required_execution_skills")
                or metadata.get("required_execution_skills")
                or skills
            )
        )
    )
    execution_skills = [value for value in execution_skills if value in skills]
    return {
        "task_id": str(task["task_id"]),
        "dataset": _source(task),
        "task_family": family,
        "difficulty": metadata.get("difficulty_score_5"),
        "required_tables": required_tables,
        "candidate_tables": list(
            dict.fromkeys(
                str(value)
                for value in (
                    metadata.get("candidate_tables")
                    or [
                        Path(str(asset.get("path", ""))).stem
                        for asset in task.get("data_assets") or []
                        if asset.get("path")
                    ]
                )
            )
        ),
        "relational_contract": _join_contract(metadata, required_tables),
        "temporal_contract": _temporal_contract(task, metadata, family),
        "required_skills": skills,
        "required_execution_skills": execution_skills,
        "skill_order": skills,
        "skill_execution_order": execution_skills,
        "answer_contract": {
            "type": metadata.get("answer_contract", "json_array"),
            "gold_rows": metadata.get("gold_rows") or [],
            "key_fields": metadata.get("key_fields") or [],
            "output_fields": metadata.get("output_fields") or [],
            "numeric_tolerances": metadata.get("numeric_tolerances") or {},
            "semantic_contract": metadata.get("semantic_contract") or {},
        },
        "gold_provenance": metadata.get("gold_provenance", ""),
    }


def build_contracts(task_json: Path, output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tasks = load_json(task_json)
    contracts = [build_contract(task) for task in tasks]
    issues: list[dict[str, Any]] = []
    for contract in contracts:
        missing = []
        if not contract["required_tables"]:
            missing.append("required_tables")
        answer = contract["answer_contract"]
        if not answer["gold_rows"]:
            missing.append("gold_rows")
        if not answer["key_fields"]:
            missing.append("key_fields")
        if not contract["required_skills"]:
            missing.append("required_skills")
        if missing:
            issues.append({"task_id": contract["task_id"], "missing": missing})

    report = {
        "task_count": len(tasks),
        "contract_count": len(contracts),
        "valid_contract_count": len(contracts) - len(issues),
        "issue_count": len(issues),
        "issues": issues,
    }
    write_jsonl(output_dir / "task_contracts.jsonl", contracts)
    write_json(output_dir / "contract_validation.json", report)
    return contracts, report
