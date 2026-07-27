from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MetricValue:
    value: float | int | bool | None
    quality: str = "measured"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunLocator:
    task_id: str
    framework: str
    model: str
    condition: str
    repeat: int
    run_id: str
    run_root: str


@dataclass
class TraceRecord:
    locator: RunLocator
    status: str
    failure_reason: str
    final_answer: str
    answer_source: str
    pre_repair_final_answer: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    tables_read: list[str] = field(default_factory=list)
    join_operations: list[dict[str, Any]] = field(default_factory=list)
    temporal_operations: list[str] = field(default_factory=list)
    temporal_operation_sequence: list[str] = field(default_factory=list)
    temporal_granularities: list[str] = field(default_factory=list)
    temporal_parameters: list[str] = field(default_factory=list)
    timestamps_used: list[str] = field(default_factory=list)
    skill_usage: dict[str, Any] = field(default_factory=dict)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    duration_seconds: float | None = None
    final_answer_repair_attempt_count: int = 0
    final_answer_repair_success_count: int = 0
    whole_task_attempt_count: int = 1
    infrastructure_retry_count: int = 0
    raw_result_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.update(value.pop("locator"))
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TraceRecord":
        locator = RunLocator(
            task_id=str(value["task_id"]),
            framework=str(value["framework"]),
            model=str(value["model"]),
            condition=str(value["condition"]),
            repeat=int(value.get("repeat", 1)),
            run_id=str(value.get("run_id", "")),
            run_root=str(value.get("run_root", "")),
        )
        field_names = {
            "status",
            "failure_reason",
            "final_answer",
            "pre_repair_final_answer",
            "answer_source",
            "tool_calls",
            "commands",
            "tables_read",
            "join_operations",
            "temporal_operations",
            "temporal_operation_sequence",
            "temporal_granularities",
            "temporal_parameters",
            "timestamps_used",
            "skill_usage",
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "duration_seconds",
            "final_answer_repair_attempt_count",
            "final_answer_repair_success_count",
            "whole_task_attempt_count",
            "infrastructure_retry_count",
            "raw_result_path",
        }
        kwargs = {key: value[key] for key in field_names if key in value}
        return cls(locator=locator, **kwargs)
