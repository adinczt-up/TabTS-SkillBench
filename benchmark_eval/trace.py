from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from benchmark_eval.contracts import _temporal_parameter_tokens
from benchmark_eval.schema import RunLocator, TraceRecord
from benchmark_eval.utils import load_json, read_jsonl

DATE_RE = re.compile(r"\b(?:19|20)\d{2}-\d{2}(?:-\d{2})?\b")
JOIN_RE = re.compile(r"\b(join|merge)\b|\.merge\s*\(|\.join\s*\(", re.I)

TEMPORAL_PATTERNS: dict[str, tuple[str, ...]] = {
    "filter": ("between(", "datetime >=", "datetime <", "timestamp >=", "timestamp <"),
    "period_aggregate": ("date_trunc", "to_period(", "resample(", ".dt.floor", ".dt.to_period"),
    "rolling_window": ("rolling(", "rows between", "range between"),
    "shift": (".shift(", " lag(", "lead(", "crosscorr", "cross-correlation"),
    "forecast": ("forecast", "predict(", "extrapolat"),
    "interpolation": ("interpolate(", "linear interpolation"),
    "forward_fill": ("ffill(", "fillna(method='ffill", 'fillna(method="ffill'),
    "quantile": ("quantile(", "percentile", "p90", "p10", "iqr"),
    "regression": ("linregress", "linearregression", "ols(", "polyfit("),
    "event_detection": ("change_point", "changepoint", "threshold", "spike"),
    "correlation": ("corr(", "correlation", "acf(", "autocorr"),
    "ranking": ("rank(", "dense_rank", "nlargest(", "nsmallest("),
    "robust_scale": ("median_absolute_deviation", "median absolute deviation", "--method mad"),
}

TEMPORAL_GRANULARITY_PATTERNS: dict[str, tuple[str, ...]] = {
    "hour": (
        r"date_trunc\(\s*['\"]hour",
        r"(?:resample|floor|to_period)\(\s*['\"]h",
        r"['\"](?:frequency|granularity|period)['\"]\s*:\s*['\"]hour",
        r"\bhourly\b",
    ),
    "day": (
        r"date_trunc\(\s*['\"]day",
        r"(?:resample|floor|to_period)\(\s*['\"]d",
        r"['\"](?:frequency|granularity|period)['\"]\s*:\s*['\"]day",
        r"\b(?:daily|machine-day|building-day)\b",
    ),
    "week": (
        r"date_trunc\(\s*['\"]week",
        r"(?:resample|floor|to_period)\(\s*['\"]w",
        r"['\"](?:frequency|granularity|period)['\"]\s*:\s*['\"]week",
        r"\b(?:weekly|weekday|weekend)\b",
    ),
    "month": (
        r"date_trunc\(\s*['\"]month",
        r"(?:resample|floor|to_period)\(\s*['\"]m",
        r"['\"](?:frequency|granularity|period)['\"]\s*:\s*['\"]month",
        r"\bmonthly\b",
    ),
    "quarter": (
        r"date_trunc\(\s*['\"]quarter",
        r"(?:resample|floor|to_period)\(\s*['\"]q",
        r"['\"](?:frequency|granularity|period)['\"]\s*:\s*['\"]quarter",
        r"\bquarterly\b",
    ),
    "year": (
        r"date_trunc\(\s*['\"]year",
        r"(?:resample|floor|to_period)\(\s*['\"]y",
        r"['\"](?:frequency|granularity|period)['\"]\s*:\s*['\"]year",
        r"\b(?:yearly|annual)\b",
    ),
    "season": (r"\bseason(?:al)?\b",),
    "event": (r"\b(?:event|race|transaction|post)(?:-level)?\b",),
}

for _granularity in tuple(TEMPORAL_GRANULARITY_PATTERNS):
    TEMPORAL_GRANULARITY_PATTERNS[_granularity] += (
        rf"--(?:frequency|granularity|period)(?:=|\s+){_granularity}\b",
    )

SKILL_OPERATION_PATTERNS: dict[str, tuple[str, ...]] = {
    "period_aggregate": (
        "tableagent-period-bucket-aggregation",
        "tableagent-grouped-period-volatility",
        "tableagent-weekpart-contrast",
        "tableagent-seasonal-median-holdout",
        "tableagent-two-period-volatility-change",
    ),
    "filter": (
        "tableagent-time-window-coverage",
        "tableagent-grouped-two-period-aggregate",
        "tableagent-two-period-rank-reversal",
        "tableagent-event-period-response",
        "tableagent-consecutive-state-runs",
    ),
    "rolling_window": ("rolling", "backtest"),
    "shift": (
        "tableagent-lag-direction-validation",
        "tableagent-temporal-alignment",
        "tableagent-grouped-ols-regression",
        "tableagent-event-period-response",
        "tableagent-calendar-lag-correlation",
        "tableagent-linear-interpolation-holdout",
        "tableagent-seasonal-naive-holdout",
    ),
    "forecast": (
        "tableagent-one-step-linear-trend-forecast",
        "tableagent-rolling-origin-model-selection",
    ),
    "interpolation": ("tableagent-linear-interpolation-holdout",),
    "forward_fill": ("tableagent-forward-fill-imputation",),
    "quantile": (
        "tableagent-quantile-range",
        "tableagent-grouped-anomaly-scoring",
    ),
    "regression": (
        "tableagent-grouped-linear-trend",
        "tableagent-one-step-linear-trend-forecast",
        "tableagent-grouped-ols-regression",
    ),
    "event_detection": (
        "tableagent-temporal-event-segmentation",
        "tableagent-robust-change-candidates",
        "tableagent-grouped-anomaly-scoring",
        "tableagent-two-level-change-point",
        "tableagent-consecutive-state-runs",
        "tableagent-grouped-event-contrast",
        "tableagent-two-period-volatility-change",
    ),
    "correlation": (
        "cross_correlation",
        "autocorrelation",
        "tableagent-lag-direction-validation",
        "tableagent-calendar-lag-correlation",
    ),
    "ranking": (
        "tableagent-ranking-filtering",
        "tableagent-two-period-rank-reversal",
        "tableagent-two-stage-peak-selection",
        "tableagent-rolling-origin-model-selection",
        "tableagent-seasonal-naive-holdout",
    ),
}

SKILL_OPERATION_PATTERNS["rolling_window"] += (
    "tableagent-trailing-window-threshold",
    "tableagent-rolling-origin-model-selection",
)


def _load_result(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = load_json(path)
    return value if isinstance(value, dict) else None


def _session_paths(run_root: Path, result: dict[str, Any]) -> list[Path]:
    paths = list((run_root / "workspace" / "sessions").glob("*.jsonl"))
    if paths:
        return paths
    usage = result.get("skill_usage") or {}
    for value in usage.get("session_files") or []:
        candidate = Path(str(value))
        if candidate.is_file():
            paths.append(candidate)
    return paths


def _tool_calls(session_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = {
        str(row.get("tool_call_id")): str(row.get("content") or "")
        for row in session_rows
        if row.get("role") == "tool" and row.get("tool_call_id")
    }
    calls: list[dict[str, Any]] = []
    for line_number, row in enumerate(session_rows, start=1):
        for raw in row.get("tool_calls") or []:
            function = raw.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = {"_raw": raw_arguments}
            call_id = str(raw.get("id") or "")
            result = results.get(call_id, "")
            exit_match = re.search(r"(?:Exit code|Process exited with code):\s*(-?\d+)", result)
            calls.append(
                {
                    "line": line_number,
                    "id": call_id,
                    "name": function.get("name") or raw.get("name"),
                    "arguments": arguments,
                    "result": result,
                    "exit_code": int(exit_match.group(1)) if exit_match else None,
                }
            )
    return calls


def _commands(calls: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for call in calls:
        if call.get("name") not in {"exec", "shell", "run_command"}:
            continue
        arguments = call.get("arguments") or {}
        value = arguments.get("command", arguments.get("cmd", ""))
        if isinstance(value, str) and value.strip():
            values.append(value)
    return values


def _tables_read(
    task: dict[str, Any],
    calls: list[dict[str, Any]],
    commands: list[str],
) -> list[str]:
    assets: dict[str, list[str]] = {}
    for asset in task.get("data_assets") or []:
        path = str(asset.get("path") or "")
        env_path = str(asset.get("env_path") or "")
        table = Path(path or env_path).stem
        if table:
            assets[table] = [
                token.casefold().replace("\\", "/")
                for token in {path, env_path, Path(path).name, Path(env_path).name}
                if token
            ]
    observed_text = "\n".join(commands).casefold().replace("\\", "/")
    for call in calls:
        if call.get("name") == "read_file":
            observed_text += "\n" + str(
                (call.get("arguments") or {}).get("path", "")
            ).casefold().replace("\\", "/")
    found = []
    for table, tokens in assets.items():
        if any(token and token in observed_text for token in tokens):
            found.append(table)
    return sorted(found)


def _join_operations(commands: list[str]) -> list[dict[str, Any]]:
    operations = []
    for index, command in enumerate(commands):
        if not JOIN_RE.search(command):
            continue
        using = re.findall(r"\bUSING\s*\(([^)]+)\)", command, re.I)
        on_keys = re.findall(
            r"([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)",
            command,
            re.I,
        )
        merge_keys = re.findall(
            r"(?:on|left_on|right_on)\s*=\s*['\"]([^'\"]+)['\"]",
            command,
            re.I,
        )
        for value in re.findall(
            r"(?:on|left_on|right_on)\s*=\s*\[([^\]]+)\]",
            command,
            re.I,
        ):
            merge_keys.extend(re.findall(r"['\"]([^'\"]+)['\"]", value))
        sql_join_count = len(re.findall(r"\bJOIN\b", command, re.I))
        pandas_join_count = len(re.findall(r"\.\s*(?:merge|join)\s*\(", command, re.I))
        operations.append(
            {
                "command_index": index,
                "using_keys": [
                    key.strip().strip('"`[]')
                    for value in using
                    for key in value.split(",")
                    if key.strip()
                ],
                "on_edges": [list(value) for value in on_keys],
                "merge_keys": merge_keys,
                "join_count": max(sql_join_count + pandas_join_count, 1),
                "quality": "command_observed",
            }
        )
    return operations


def _temporal_operations(commands: list[str]) -> list[str]:
    return list(dict.fromkeys(_temporal_operation_sequence(commands)))


def _temporal_operation_sequence(commands: list[str]) -> list[str]:
    """Return operations in first-observed command order.

    This is command-observed evidence, not an inference from the final answer.
    Repeated adjacent operations are collapsed while later revisits are kept.
    """
    sequence: list[str] = []
    for command in commands:
        text = command.casefold().replace(" ", "")
        hits: list[tuple[int, str]] = []
        for operation, patterns in TEMPORAL_PATTERNS.items():
            positions = [
                text.find(pattern.casefold().replace(" ", ""))
                for pattern in patterns
            ]
            positions = [position for position in positions if position >= 0]
            if positions:
                hits.append((min(positions), operation))
        for operation, patterns in SKILL_OPERATION_PATTERNS.items():
            positions = [
                text.find(pattern.casefold().replace(" ", ""))
                for pattern in patterns
            ]
            positions = [position for position in positions if position >= 0]
            if positions:
                hits.append((min(positions), operation))
        for _, operation in sorted(set(hits)):
            if not sequence or sequence[-1] != operation:
                sequence.append(operation)
    return sequence


def _temporal_parameters(commands: list[str]) -> list[str]:
    text = "\n".join(commands)
    tokens = set(_temporal_parameter_tokens(text))
    for match in re.finditer(r"\.shift\(\s*(-?\d+)\s*\)", text, re.I):
        tokens.add(f"offset:{int(match.group(1))}:period")
    for match in re.finditer(r"\.rolling\(\s*(?:window\s*=\s*)?(\d+)", text, re.I):
        tokens.add(f"parameter:{int(match.group(1))}:period")
    for match in re.finditer(r"\b(?:lag|horizon)\s*=\s*(\d+)", text, re.I):
        tokens.add(f"parameter:{int(match.group(1))}:period")
    for match in re.finditer(
        r"--(?:window|window-size|rolling-window|lag|lag-periods|horizon)"
        r"(?:=|\s+)(-?\d+)(?:\s+(hour|day|week|month|quarter|year)s?)?",
        text,
        re.I,
    ):
        tokens.add(
            f"parameter:{int(match.group(1))}:{(match.group(2) or 'period').casefold()}"
        )
    for match in re.finditer(
        r"--lags(?:=|\s+)([\d,\s-]+).*?--frequency(?:=|\s+)"
        r"(hour|day|week|month|quarter|year)",
        text,
        re.I | re.S,
    ):
        unit = match.group(2).casefold()
        for value in re.findall(r"-?\d+", match.group(1)):
            tokens.add(f"parameter:{int(value)}:{unit}")
    for match in re.finditer(
        r"--(?:validation-periods|adjacency-steps|recovery-window|seasonal-lag)"
        r"(?:=|\s+)(\d+)",
        text,
        re.I,
    ):
        tokens.add(f"parameter:{int(match.group(1))}:period")
    return sorted(tokens)


def _temporal_granularities(commands: list[str]) -> list[str]:
    text = "\n".join(commands).casefold()
    return [
        granularity
        for granularity, patterns in TEMPORAL_GRANULARITY_PATTERNS.items()
        if any(re.search(pattern, text, re.I) for pattern in patterns)
    ]


def _usage(result: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    prompt = completion = cached = 0
    observed = False
    candidates = [result.get("usage") or {}]
    candidates.extend(
        turn.get("usage") or {}
        for turn in result.get("turns") or []
        if isinstance(turn, dict)
    )
    for usage in candidates:
        if not isinstance(usage, dict) or not usage:
            continue
        observed = True
        prompt += int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        completion += int(
            usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
        )
        cached += int(usage.get("cached_tokens", 0) or 0)
    return (prompt, completion, cached) if observed else (None, None, None)


def normalize_run(locator: RunLocator, task: dict[str, Any]) -> TraceRecord:
    run_root = Path(locator.run_root)
    result_path = run_root / "task_result.json"
    result = _load_result(result_path)
    if result is None:
        return TraceRecord(
            locator=locator,
            status="missing_run",
            failure_reason="task_result.json not found",
            final_answer="",
            answer_source="missing",
            raw_result_path=str(result_path),
        )

    explicit = result.get("benchmark_trace") or {}
    if not isinstance(explicit, dict):
        explicit = {}
    rows = []
    for path in _session_paths(run_root, result):
        rows.extend(read_jsonl(path))
    calls = list(explicit.get("tool_calls") or _tool_calls(rows))
    commands = list(explicit.get("commands") or _commands(calls))
    tables = list(explicit.get("tables_read") or _tables_read(task, calls, commands))
    joins = list(explicit.get("join_operations") or _join_operations(commands))
    temporal_sequence = list(
        explicit.get("temporal_operation_sequence")
        or _temporal_operation_sequence(commands)
    )
    temporal = list(
        explicit.get("temporal_operations")
        or dict.fromkeys(temporal_sequence)
    )
    granularities = list(
        explicit.get("temporal_granularities")
        or _temporal_granularities(commands)
    )
    temporal_parameters = list(
        explicit.get("temporal_parameters")
        or _temporal_parameters(commands)
    )
    timestamps = sorted(
        set(
            explicit.get("timestamps_used")
            or DATE_RE.findall("\n".join(commands))
        )
    )
    prompt, completion, cached = _usage(result)
    durations = [
        float(turn["duration_seconds"])
        for turn in result.get("turns") or []
        if isinstance(turn, dict) and turn.get("duration_seconds") is not None
    ]
    duration = sum(durations) if durations else result.get("duration_seconds")
    answer = str(result.get("final_output") or "")
    source = str(result.get("final_output_source") or "final_output")
    if not answer:
        for turn in reversed(result.get("turns") or []):
            if isinstance(turn, dict) and str(turn.get("content") or "").strip():
                answer = str(turn["content"])
                source = "last_turn_content"
                break
    raw_status = str(result.get("status") or "failed")
    status = raw_status if raw_status in {
        "completed", "failed", "infrastructure_error", "empty_output"
    } else "failed"
    if status == "completed" and not answer.strip():
        status = "empty_output"
    return TraceRecord(
        locator=locator,
        status=status,
        failure_reason=str(result.get("failure_reason") or ""),
        final_answer=answer,
        pre_repair_final_answer=str(
            result.get("pre_repair_final_output") or answer
        ),
        answer_source=source,
        tool_calls=calls,
        commands=commands,
        tables_read=tables,
        join_operations=joins,
        temporal_operations=temporal,
        temporal_operation_sequence=temporal_sequence,
        temporal_granularities=granularities,
        temporal_parameters=temporal_parameters,
        timestamps_used=timestamps,
        skill_usage=dict(explicit.get("skill_usage") or result.get("skill_usage") or {}),
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=cached,
        duration_seconds=float(duration) if duration is not None else None,
        final_answer_repair_attempt_count=int(
            result.get("final_answer_repair_attempt_count") or 0
        ),
        final_answer_repair_success_count=int(
            result.get("final_answer_repair_success_count") or 0
        ),
        whole_task_attempt_count=int(result.get("whole_task_attempt_count") or 1),
        infrastructure_retry_count=int(
            result.get("infrastructure_retry_count") or 0
        ),
        raw_result_path=str(result_path),
    )
