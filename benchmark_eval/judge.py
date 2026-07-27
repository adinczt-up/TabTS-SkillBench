from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from benchmark_eval.utils import load_json, stable_hash, write_json

JUDGE_SYSTEM = """You are a blinded evaluator of table-analysis agent responses.
Do not infer which model, framework, or experimental condition produced an answer.
Evaluate only the supplied question, final answer, and observable evidence summary.
Do not redo the numerical benchmark checker. Return JSON only."""

JUDGE_RUBRIC = """Score each dimension from 1 to 5:
1. instruction_fulfillment: the response follows the requested answer scope and format.
2. logical_coherence: explanation and final conclusion are internally consistent.
3. evidence_faithfulness: claims do not exceed the supplied observable evidence.
4. relevance: the response is focused and avoids irrelevant material.

Return:
{"instruction_fulfillment": int, "logical_coherence": int,
 "evidence_faithfulness": int, "relevance": int,
 "short_reason": "one concise sentence"}"""


def _extract_json(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _question(task: dict[str, Any]) -> str:
    turns = task.get("turns") or []
    values = [
        str(turn.get("question") or "")
        for turn in turns
        if isinstance(turn, dict) and str(turn.get("question") or "").strip()
    ]
    if values:
        return "\n".join(values)
    return str(task.get("minimal_prompt") or task.get("instruction") or "")


def _prompt(task: dict[str, Any], trace: dict[str, Any]) -> str:
    evidence = {
        "tables_read": trace.get("tables_read") or [],
        "join_operation_count": len(trace.get("join_operations") or []),
        "temporal_operations": trace.get("temporal_operations") or [],
        "skill_execution_count": len(
            (trace.get("skill_usage") or {}).get("structured_skills") or []
        ),
        "tool_call_count": len(trace.get("tool_calls") or []),
    }
    return (
        f"{JUDGE_RUBRIC}\n\n"
        f"Question:\n{_question(task)}\n\n"
        f"Final answer:\n{str(trace.get('final_answer') or '')[:12000]}\n\n"
        f"Observable evidence summary:\n"
        f"{json.dumps(evidence, ensure_ascii=False)}"
    )


async def judge_traces(
    *,
    traces: list[dict[str, Any]],
    tasks_by_id: dict[str, dict[str, Any]],
    model_config_path: Path,
    output_dir: Path,
    concurrency: int = 4,
    timeout_seconds: int = 180,
) -> list[dict[str, Any]]:
    from nanobot.providers.factory import load_provider_snapshot

    snapshot = load_provider_snapshot(model_config_path)
    cache_dir = output_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(concurrency)

    async def evaluate(trace: dict[str, Any]) -> dict[str, Any]:
        task_id = str(trace["task_id"])
        task = tasks_by_id[task_id]
        prompt = _prompt(task, trace)
        cache_key = stable_hash(
            {
                "judge_model": snapshot.model,
                "system": JUDGE_SYSTEM,
                "prompt": prompt,
            }
        )
        cache_path = cache_dir / f"{cache_key}.json"
        if cache_path.is_file():
            return load_json(cache_path)

        result: dict[str, Any] = {
            "task_id": task_id,
            "framework": trace["framework"],
            "model": trace["model"],
            "condition": trace["condition"],
            "repeat": trace.get("repeat", 1),
            "judge_model": snapshot.model,
            "status": "error",
        }
        async with semaphore:
            try:
                response = await asyncio.wait_for(
                    snapshot.provider.chat(
                        messages=[
                            {"role": "system", "content": JUDGE_SYSTEM},
                            {"role": "user", "content": prompt},
                        ],
                        model=snapshot.model,
                        max_tokens=500,
                        temperature=0,
                    ),
                    timeout=timeout_seconds,
                )
                parsed = _extract_json(str(response.content or ""))
                if parsed is None:
                    result["error"] = "unparseable_judge_output"
                    result["raw_output"] = response.content
                else:
                    scores = []
                    for field in (
                        "instruction_fulfillment",
                        "logical_coherence",
                        "evidence_faithfulness",
                        "relevance",
                    ):
                        value = int(parsed.get(field, 0))
                        if value < 1 or value > 5:
                            raise ValueError(f"Judge score out of range: {field}={value}")
                        result[field] = value
                        scores.append(value)
                    result["response_quality"] = sum(scores) / (5 * len(scores))
                    result["short_reason"] = str(parsed.get("short_reason") or "")
                    result["status"] = "ok"
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
        write_json(cache_path, result)
        return result

    try:
        return await asyncio.gather(*(evaluate(trace) for trace in traces))
    finally:
        provider = snapshot.provider
        client = getattr(provider, "_client", None)
        close_target = client or provider
        close = getattr(close_target, "aclose", None) or getattr(
            close_target,
            "close",
            None,
        )
        if callable(close):
            value = close()
            if asyncio.iscoroutine(value):
                await value
