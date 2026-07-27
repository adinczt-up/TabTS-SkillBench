"""Evaluate isolated nanobot task outputs against task.json score_points.

The evaluator is intentionally file-based:
- reads task definitions from datasets/task.json
- reads model turn outputs from one run directory
- scores every score_point independently
- writes evaluation_result.json and evaluation_report.md

Default judging mode is LLM-based. The old deterministic matcher remains
available via `--judge rule`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_TASK_JSON = REPO_ROOT / "datasets" / "task.json"
RUNS_ROOT = REPO_ROOT / "runs"

BAND_NAMES = ("rush", "steady", "safe")
FIELD_NAMES = ("province", "year", "score", "estimated_rank", "school", "major", "plan", "lowest_rank", "rank_gap")


@dataclass
class PointScore:
    score_point: str
    score: float
    max_score: float
    passed: bool
    matched: list[str]
    missing: list[str]
    note: str


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def safe_name(value: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if ch in bad else ch for ch in value).strip() or "task"


def load_tasks(task_json: Path) -> list[dict[str, Any]]:
    tasks = load_json(task_json)
    if isinstance(tasks, dict):
        return [tasks]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(f"No tasks found in {task_json}")
    valid_tasks = [task for task in tasks if isinstance(task, dict)]
    if not valid_tasks:
        raise ValueError(f"No object tasks found in {task_json}")
    return valid_tasks


def split_task_ids(values: list[str] | None) -> list[str]:
    if not values:
        return []
    task_ids: list[str] = []
    for value in values:
        for item in value.split(","):
            item = item.strip()
            if item:
                task_ids.append(item)
    return list(dict.fromkeys(task_ids))


def task_map(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(task.get("task_id")): task for task in tasks if task.get("task_id")}


def select_task_ids(
    *,
    tasks: list[dict[str, Any]],
    requested_ids: list[str],
    all_tasks: bool,
) -> list[str]:
    by_id = task_map(tasks)
    if all_tasks and requested_ids:
        raise ValueError("Use either --all-tasks or --task-id, not both.")
    if all_tasks:
        return list(by_id.keys())
    if requested_ids:
        missing = [task_id for task_id in requested_ids if task_id not in by_id]
        if missing:
            raise ValueError(f"Task id not found: {', '.join(missing)}")
        return requested_ids
    return []


def load_task(task_json: Path, task_id: str | None) -> dict[str, Any]:
    tasks = load_tasks(task_json)
    if task_id is None:
        return tasks[0]
    by_id = task_map(tasks)
    task = by_id.get(task_id)
    if task is not None:
        return task
    raise ValueError(f"Task id not found: {task_id}")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def extract_json_payload(text: str) -> Any | None:
    stripped = text.strip()
    if not stripped:
        return None
    for marker in ("```json", "```JSON", "```"):
        start = stripped.find(marker)
        if start < 0:
            continue
        body_start = start + len(marker)
        end = stripped.find("```", body_start)
        if end < 0:
            continue
        candidate = stripped[body_start:end].strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for pos, ch in enumerate(stripped):
        if ch not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[pos:])
            return value
        except json.JSONDecodeError:
            continue
    return None


def load_turn_outputs(run_root: Path) -> dict[int, str]:
    """Load turn outputs from responses.jsonl, falling back to response files."""
    outputs: dict[int, str] = {}
    responses_path = run_root / "responses.jsonl"
    if responses_path.is_file():
        with responses_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                idx = int(record["idx"])
                content = record.get("content")
                if isinstance(content, str):
                    outputs[idx] = content
                    continue
                response_path = record.get("response_path")
                if isinstance(response_path, str) and Path(response_path).is_file():
                    outputs[idx] = Path(response_path).read_text(encoding="utf-8")
    if outputs:
        return outputs

    task_result_path = run_root / "task_result.json"
    if task_result_path.is_file():
        result = load_json(task_result_path)
        for record in result.get("turns", []):
            if not isinstance(record, dict) or "idx" not in record:
                continue
            idx = int(record["idx"])
            outputs[idx] = normalize_text(record.get("content", ""))
    if outputs:
        return outputs

    for path in sorted((run_root / "outputs").glob("turn_*.response.md")):
        match = re.search(r"turn_(\d+)\.response\.md$", path.name)
        if match:
            outputs[int(match.group(1))] = path.read_text(encoding="utf-8")
    return outputs


def is_run_root(path: Path) -> bool:
    return (
        (path / "manifest.json").is_file()
        or (path / "task_result.json").is_file()
        or (path / "responses.jsonl").is_file()
        or (path / "outputs").is_dir()
    )


def discover_run_roots_from_path(path: Path) -> list[Path]:
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Run root not found: {path}")
    if path.is_file() and path.name == "manifest.json":
        return [path.parent]
    if path.is_dir() and is_run_root(path):
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"Run root not found: {path}")

    found: set[Path] = set()
    for manifest in path.rglob("manifest.json"):
        found.add(manifest.parent.resolve())
    if not found:
        for task_result in path.rglob("task_result.json"):
            found.add(task_result.parent.resolve())
    return sorted(found)


def read_run_metadata(run_root: Path) -> dict[str, Any]:
    manifest_path = run_root / "manifest.json"
    if manifest_path.is_file():
        manifest = load_json(manifest_path)
        if isinstance(manifest, dict):
            return manifest
    task_result_path = run_root / "task_result.json"
    if task_result_path.is_file():
        result = load_json(task_result_path)
        if isinstance(result, dict):
            return result
    return {}


def infer_task_id_from_run_root(run_root: Path, tasks_by_id: dict[str, dict[str, Any]]) -> str | None:
    metadata = read_run_metadata(run_root)
    task_id = metadata.get("task_id")
    if isinstance(task_id, str) and task_id in tasks_by_id:
        return task_id
    parts = list(run_root.resolve().parts)
    for part in reversed(parts):
        if part in tasks_by_id:
            return part
    return None


def infer_skill_mode_from_run_root(run_root: Path) -> str | None:
    metadata = read_run_metadata(run_root)
    skill_mode = metadata.get("skill_mode")
    if isinstance(skill_mode, str):
        return skill_mode
    parent = run_root.parent.name
    if parent.startswith("skill_"):
        return parent.removeprefix("skill_")
    return None


def resolve_run_roots(
    *,
    explicit_run_roots: list[str],
    runs_root: Path,
    run_id: str | None,
    skill_mode: str | None,
    task_ids: list[str],
    all_task_ids: list[str],
) -> list[Path]:
    modes = ["on", "off"] if skill_mode == "both" else ([skill_mode] if skill_mode else [])
    roots: list[Path] = []

    if explicit_run_roots:
        for raw in explicit_run_roots:
            roots.extend(discover_run_roots_from_path(Path(raw)))
    elif run_id:
        ids = task_ids or all_task_ids
        selected_modes = modes or ["on", "off"]
        for task_id in ids:
            for mode in selected_modes:
                candidate = runs_root / safe_name(task_id) / f"skill_{mode}" / safe_name(run_id)
                if candidate.is_dir():
                    roots.append(candidate.resolve())
    else:
        raise ValueError("Please provide --run-root, or provide --run-id for batch evaluation.")

    unique = list(dict.fromkeys(root.resolve() for root in roots))
    if run_id:
        unique = [root for root in unique if root.name == safe_name(run_id)]
    if modes:
        unique = [
            root
            for root in unique
            if (infer_skill_mode_from_run_root(root) in set(modes))
        ]
    return unique


def field_value_pairs(score_point: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    field_pattern = "|".join(re.escape(name) for name in FIELD_NAMES)
    pattern = re.compile(
        rf"\b({field_pattern})\b\s*(?:为|=)\s*([^，。；;、\n]+)",
        re.IGNORECASE,
    )
    for key, value in pattern.findall(score_point):
        pairs.append((key, value.strip().strip("。；;，,")))
    return pairs


def required_terms_after_colon(score_point: str) -> list[str]:
    terms: list[str] = []
    for pattern in (
        r"(?:包含|包括|保留条件包含|排除条件包含)[：:]\s*([^。；;\n]+)",
        r"三个分档[：:]\s*([^。；;\n]+)",
    ):
        for chunk in re.findall(pattern, score_point):
            for raw in re.split(r"[、,，/]", chunk):
                term = raw.strip().strip("之一").strip()
                if not term:
                    continue
                if len(term) > 30:
                    continue
                terms.append(term)
    return terms


def required_paths(score_point: str) -> list[str]:
    return re.findall(r"datasets/[^\s，。；;]+?\.xls", score_point)


def required_code_tokens(score_point: str) -> list[str]:
    tokens: list[str] = []
    for token in ("A4xx", "rank_gap", "lowest_rank", "estimated_rank", "abs(rank_gap)", "bands.rush", "bands.steady", "bands.safe"):
        if token in score_point:
            tokens.append(token)
    for band in BAND_NAMES:
        if re.search(rf"\b{band}\b", score_point):
            tokens.append(band)
    return tokens


def required_thresholds(score_point: str) -> list[str]:
    thresholds: list[str] = []
    for expr in re.findall(r"-?\d+\s*<=\s*rank_gap\s*<\s*-?\d+", score_point):
        thresholds.append(expr)
    for expr in re.findall(r"-?\d+\s*<=\s*rank_gap\s*<=\s*-?\d+", score_point):
        thresholds.append(expr)
    for expr in re.findall(r"rank_gap\s*>\s*-?\d+", score_point):
        thresholds.append(expr)
    return thresholds


def expected_band_entries(task: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    expected: dict[str, list[dict[str, str]]] = {band: [] for band in BAND_NAMES}
    for turn in task.get("turns", []):
        if not isinstance(turn, dict):
            continue
        for point in turn.get("score_points", []):
            if not isinstance(point, str):
                continue
            match = re.match(r"(rush|steady|safe)\s+第\s*(\d+)\s*项", point)
            if not match:
                continue
            band = match.group(1)
            entry = {key: value for key, value in field_value_pairs(point)}
            if entry:
                entry["_index"] = match.group(2)
                expected[band].append(entry)
    return expected


def contains_value(text: str, value: str) -> bool:
    text_c = compact(text)
    value_c = compact(value)
    if value_c in text_c:
        return True
    # Accept ASCII/Chinese parenthesis variants for major names.
    alt = value_c.replace("(", "（").replace(")", "）")
    if alt in text_c:
        return True
    alt = value_c.replace("（", "(").replace("）", ")")
    return alt in text_c


def check_requirement(text: str, label: str, value: str) -> tuple[bool, str]:
    if contains_value(text, value):
        return True, f"{label}={value}"
    return False, f"{label}={value}"


def token_present(text: str, token: str) -> bool:
    if contains_value(text, token):
        return True
    if "." in token:
        parts = [part for part in token.split(".") if part]
        return all(contains_value(text, part) for part in parts)
    return False


def score_band_entry_point(score_point: str, response_text: str) -> PointScore | None:
    match = re.match(r"(rush|steady|safe)\s+第\s*(\d+)\s*项", score_point)
    if not match:
        return None
    matched: list[str] = []
    missing: list[str] = []
    for key, value in field_value_pairs(score_point):
        ok, label = check_requirement(response_text, key, value)
        (matched if ok else missing).append(label)
    passed = not missing and bool(matched)
    return PointScore(
        score_point=score_point,
        score=1.0 if passed else 0.0,
        max_score=1.0,
        passed=passed,
        matched=matched,
        missing=missing,
        note="band_entry_exact_match",
    )


def score_final_band_point(
    *,
    score_point: str,
    response_text: str,
    expected: dict[str, list[dict[str, str]]],
) -> PointScore | None:
    band_match = re.match(r"(rush|steady|safe)\s+分档三项", score_point)
    if not band_match:
        return None
    band = band_match.group(1)
    matched: list[str] = []
    missing: list[str] = []
    entries = expected.get(band, [])
    for entry in entries:
        idx = entry.get("_index", "?")
        for key in ("school", "major", "plan", "lowest_rank", "rank_gap"):
            value = entry.get(key)
            if not value:
                continue
            ok, label = check_requirement(response_text, f"{band}[{idx}].{key}", value)
            (matched if ok else missing).append(label)
    passed = len(entries) == 3 and not missing
    return PointScore(
        score_point=score_point,
        score=1.0 if passed else 0.0,
        max_score=1.0,
        passed=passed,
        matched=matched,
        missing=missing,
        note="final_band_matches_expected_entries",
    )


def score_generic_point(score_point: str, response_text: str) -> PointScore:
    matched: list[str] = []
    missing: list[str] = []

    for key, value in field_value_pairs(score_point):
        ok, label = check_requirement(response_text, key, value)
        (matched if ok else missing).append(label)

    for path in required_paths(score_point):
        ok_full = contains_value(response_text, path)
        ok_base = contains_value(response_text, Path(path).name)
        label = f"path={path}"
        (matched if ok_full or ok_base else missing).append(label)

    for term in required_terms_after_colon(score_point):
        ok, label = check_requirement(response_text, "term", term)
        (matched if ok else missing).append(label)

    for token in required_code_tokens(score_point):
        label = f"token={token}"
        (matched if token_present(response_text, token) else missing).append(label)

    if "lowest_rank - estimated_rank" in score_point:
        formula_ok = (
            contains_value(response_text, "lowest_rank")
            and contains_value(response_text, "estimated_rank")
            and ("-" in response_text or "减" in response_text)
        )
        (matched if formula_ok else missing).append("formula=lowest_rank-estimated_rank")

    for expr in required_thresholds(score_point):
        expr_c = compact(expr)
        response_c = compact(response_text)
        nums = re.findall(r"-?\d+", expr)
        ok = expr_c in response_c or all(num in response_c for num in nums)
        (matched if ok else missing).append(f"threshold={expr}")

    # Handle exact numeric "必须为 N" when it is not attached to an English key.
    for value in re.findall(r"必须为\s*(-?\d+)", score_point):
        ok, label = check_requirement(response_text, "must_equal", value)
        (matched if ok else missing).append(label)

    # Handle "只保留 3 条" style requirements by checking either text mention or
    # three visible entries. The latter is intentionally conservative.
    if "只保留 3 条" in score_point or "保留前 3" in score_point:
        response_c = compact(response_text)
        ok = "3" in response_c or response_text.count("school") >= 3 or response_text.count("院校") >= 3
        (matched if ok else missing).append("count=3")

    # Remove duplicates while preserving order.
    matched = list(dict.fromkeys(matched))
    missing = [item for item in dict.fromkeys(missing) if item not in matched]

    if not matched and not missing:
        # Last-resort overlap for unusually free-form points.
        important_terms = [
            term
            for term in re.split(r"[，。；;、\s]+", score_point)
            if len(term) >= 2 and not term.startswith("第")
        ]
        hits = [term for term in important_terms if contains_value(response_text, term)]
        matched.extend(hits)
        if len(hits) < max(1, len(important_terms) // 2):
            missing.extend(term for term in important_terms if term not in hits)

    passed = bool(matched) and not missing
    return PointScore(
        score_point=score_point,
        score=1.0 if passed else 0.0,
        max_score=1.0,
        passed=passed,
        matched=matched,
        missing=missing,
        note="generic_rule_match",
    )


def score_point(
    *,
    task: dict[str, Any],
    score_point_text: str,
    response_text: str,
    expected: dict[str, list[dict[str, str]]],
) -> PointScore:
    band_entry = score_band_entry_point(score_point_text, response_text)
    if band_entry is not None:
        return band_entry
    final_band = score_final_band_point(
        score_point=score_point_text,
        response_text=response_text,
        expected=expected,
    )
    if final_band is not None:
        return final_band
    return score_generic_point(score_point_text, response_text)


def evaluate(task: dict[str, Any], outputs: dict[int, str]) -> dict[str, Any]:
    expected = expected_band_entries(task)
    turn_results: list[dict[str, Any]] = []
    total_score = 0.0
    max_score = 0.0

    for turn in task.get("turns", []):
        if not isinstance(turn, dict):
            continue
        idx = int(turn.get("idx", 0))
        response_text = outputs.get(idx, "")
        point_results: list[dict[str, Any]] = []
        turn_score = 0.0
        turn_max = 0.0
        for point in turn.get("score_points", []):
            if not isinstance(point, str):
                continue
            point_score = score_point(
                task=task,
                score_point_text=point,
                response_text=response_text,
                expected=expected,
            )
            point_results.append(
                {
                    "score_point": point_score.score_point,
                    "score": point_score.score,
                    "max_score": point_score.max_score,
                    "passed": point_score.passed,
                    "matched": point_score.matched,
                    "missing": point_score.missing,
                    "note": point_score.note,
                }
            )
            turn_score += point_score.score
            turn_max += point_score.max_score
        total_score += turn_score
        max_score += turn_max
        turn_results.append(
            {
                "idx": idx,
                "question": turn.get("question", ""),
                "score": turn_score,
                "max_score": turn_max,
                "accuracy": turn_score / turn_max if turn_max else 0.0,
                "response_present": bool(response_text.strip()),
                "model_output": response_text,
                "points": point_results,
            }
        )

    return {
        "task_id": task.get("task_id"),
        "score": total_score,
        "max_score": max_score,
        "accuracy": total_score / max_score if max_score else 0.0,
        "turns": turn_results,
    }


def build_llm_judge_prompt(
    *,
    task: dict[str, Any],
    turn: dict[str, Any],
    response_text: str,
) -> str:
    score_points = turn.get("score_points", [])
    points_text = "\n".join(
        f"{i}. {point}"
        for i, point in enumerate(score_points, start=1)
        if isinstance(point, str)
    )
    return f"""你是一个严格但语义鲁棒的 benchmark 评分器。请根据给定任务、当前轮问题、score_points 和模型回答，对每个 score_point 单独评分。

评分原则：
- 每个 score_point 满分 1 分。
- 如果模型回答满足该 score_point 的核心要求，score=1，否则 score=0。
- 可以接受等价表述、JSON 字段、表格、中文/英文字段名混合、实体名前带代码等格式差异。
- 对明确要求的日期、数值、实体名、字段、公式、阈值、文件路径/数据源，必须实质正确。
- 如果 score_point 明确规定计算公式、单位、范围、排序、筛选或排除条件，回答必须满足这些约束。
- 如果 score_point 要求排除某类记录，而回答中保留了被排除项，应判错。
- 不要因为回答没逐字复述 score_point 就扣分；只判断内容是否满足。
- 不要给额外加分。每个点只能是 0 或 1。

全局任务说明：
{task.get("instruction", "")}

当前轮次：{turn.get("idx")}

当前相关数据表：
{json.dumps(turn.get("related_tables", []), ensure_ascii=False)}

当前轮问题：
{turn.get("question", "")}

Score points：
{points_text}

模型回答：
{response_text if response_text.strip() else "(empty response)"}

请只返回 JSON，不要输出 Markdown。JSON 格式必须为：
{{
  "points": [
    {{
      "index": 1,
      "score": 0 或 1,
      "passed": true 或 false,
      "reason": "简短说明为什么通过或失败",
      "evidence": ["回答中支持通过的证据"],
      "missing": ["失败时缺失或错误的要求"]
    }}
  ],
  "turn_summary": "一句话总结本轮评分"
}}
""".strip()


def normalize_llm_point_result(raw: dict[str, Any], score_point_text: str, index: int) -> dict[str, Any]:
    score = raw.get("score", 0)
    try:
        score_f = float(score)
    except (TypeError, ValueError):
        score_f = 0.0
    score_f = 1.0 if score_f >= 0.5 else 0.0
    passed = bool(raw.get("passed", score_f >= 0.5))
    if score_f == 0.0:
        passed = False
    evidence = raw.get("evidence", [])
    missing = raw.get("missing", [])
    if not isinstance(evidence, list):
        evidence = [str(evidence)]
    if not isinstance(missing, list):
        missing = [str(missing)]
    return {
        "score_point": score_point_text,
        "score": score_f,
        "max_score": 1.0,
        "passed": passed,
        "matched": [str(item) for item in evidence if str(item).strip()],
        "missing": [str(item) for item in missing if str(item).strip()],
        "note": "llm_judge",
        "judge_reason": str(raw.get("reason", "")),
        "judge_index": int(raw.get("index", index) or index),
    }


async def judge_turn_with_llm(
    *,
    provider: Any,
    model: str,
    task: dict[str, Any],
    turn: dict[str, Any],
    response_text: str,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    prompt = build_llm_judge_prompt(task=task, turn=turn, response_text=response_text)
    llm_response = await provider.chat_with_retry(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "你是严格的任务测评器，只输出可解析 JSON。",
            },
            {"role": "user", "content": prompt},
        ],
        tools=None,
        tool_choice=None,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if llm_response.finish_reason == "error":
        raise RuntimeError(llm_response.content or "LLM judge returned error")
    raw_content = llm_response.content or ""
    parsed = extract_json_payload(raw_content)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("points"), list):
        print("[judge-repair] LLM judge returned invalid JSON; asking model to repair it.", flush=True)
        repair_response = await provider.chat_with_retry(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You repair malformed JSON. Return only valid JSON, no Markdown. "
                        "Preserve the original meaning and schema exactly. Escape any quotes inside strings."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Repair this malformed judge JSON into valid JSON with keys "
                        "`points` and `turn_summary`:\n\n"
                        f"{raw_content}"
                    ),
                },
            ],
            tools=None,
            tool_choice=None,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        if repair_response.finish_reason == "error":
            raise RuntimeError(repair_response.content or "LLM judge JSON repair returned error")
        parsed = extract_json_payload(repair_response.content or "")
    if not isinstance(parsed, dict) or not isinstance(parsed.get("points"), list):
        raise ValueError(f"LLM judge did not return expected JSON: {raw_content[:500]}")
    return parsed


async def close_provider_client(provider: Any) -> None:
    """Best-effort close for async provider clients to avoid noisy loop shutdown."""
    client = getattr(provider, "_client", None)
    if client is None:
        return
    close = getattr(client, "close", None) or getattr(client, "aclose", None)
    if close is None:
        return
    result = close()
    if hasattr(result, "__await__"):
        await result
    await asyncio.sleep(0)


async def evaluate_llm_async(
    *,
    task: dict[str, Any],
    outputs: dict[int, str],
    config_path: Path,
    judge_model: str | None,
    judge_provider: str | None,
    max_tokens: int,
    temperature: float,
    judge_timeout: int,
    fallback_rule: bool,
) -> dict[str, Any]:
    from nanobot.config.loader import load_config, resolve_config_env_vars, set_config_path
    from nanobot.providers.factory import make_provider

    set_config_path(config_path)
    config = resolve_config_env_vars(load_config(config_path))
    if judge_model:
        config.agents.defaults.model = judge_model
    if judge_provider:
        config.agents.defaults.provider = judge_provider
    provider = make_provider(config)
    model = config.agents.defaults.model

    try:
        rule_result = evaluate(task, outputs) if fallback_rule else None
        turn_results: list[dict[str, Any]] = []
        total_score = 0.0
        max_score = 0.0

        for turn_index, turn in enumerate(task.get("turns", [])):
            if not isinstance(turn, dict):
                continue
            idx = int(turn.get("idx", 0))
            response_text = outputs.get(idx, "")
            score_points = [p for p in turn.get("score_points", []) if isinstance(p, str)]
            try:
                print(
                    f"[judge] {task.get('task_id')} turn {idx}: "
                    f"{len(score_points)} point(s), response_chars={len(response_text)}",
                    flush=True,
                )
                judged = await asyncio.wait_for(
                    judge_turn_with_llm(
                        provider=provider,
                        model=model,
                        task=task,
                        turn=turn,
                        response_text=response_text,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    ),
                    timeout=judge_timeout,
                )
                raw_points = judged.get("points", [])
                raw_by_index: dict[int, dict[str, Any]] = {}
                for item in raw_points:
                    if isinstance(item, dict):
                        try:
                            raw_by_index[int(item.get("index"))] = item
                        except (TypeError, ValueError):
                            continue
                point_results: list[dict[str, Any]] = []
                for i, point_text in enumerate(score_points, start=1):
                    raw = raw_by_index.get(i, {})
                    point_results.append(normalize_llm_point_result(raw, point_text, i))
                turn_note = str(judged.get("turn_summary", ""))
            except Exception as exc:
                if not fallback_rule or rule_result is None:
                    raise
                fallback_turn = rule_result["turns"][turn_index]
                point_results = []
                for point in fallback_turn["points"]:
                    cloned = dict(point)
                    cloned["note"] = f"rule_fallback_after_llm_error: {type(exc).__name__}: {exc}"
                    point_results.append(cloned)
                turn_note = f"LLM judge failed; used rule fallback: {type(exc).__name__}: {exc}"

            turn_score = sum(float(point.get("score", 0.0)) for point in point_results)
            turn_max = sum(float(point.get("max_score", 1.0)) for point in point_results)
            total_score += turn_score
            max_score += turn_max
            turn_results.append(
                {
                    "idx": idx,
                    "question": turn.get("question", ""),
                    "score": turn_score,
                    "max_score": turn_max,
                    "accuracy": turn_score / turn_max if turn_max else 0.0,
                    "response_present": bool(response_text.strip()),
                    "model_output": response_text,
                    "judge": "llm",
                    "judge_model": model,
                    "turn_summary": turn_note,
                    "points": point_results,
                }
            )

        return {
            "task_id": task.get("task_id"),
            "judge": "llm",
            "judge_model": model,
            "score": total_score,
            "max_score": max_score,
            "accuracy": total_score / max_score if max_score else 0.0,
            "turns": turn_results,
        }
    finally:
        await close_provider_client(provider)


def evaluate_llm(
    *,
    task: dict[str, Any],
    outputs: dict[int, str],
    config_path: Path,
    judge_model: str | None,
    judge_provider: str | None,
    max_tokens: int,
    temperature: float,
    judge_timeout: int,
    fallback_rule: bool,
) -> dict[str, Any]:
    return asyncio.run(
        evaluate_llm_async(
            task=task,
            outputs=outputs,
            config_path=config_path,
            judge_model=judge_model,
            judge_provider=judge_provider,
            max_tokens=max_tokens,
            temperature=temperature,
            judge_timeout=judge_timeout,
            fallback_rule=fallback_rule,
        )
    )


def make_markdown_report(result: dict[str, Any]) -> str:
    lines = [
        f"# Evaluation Report: {result.get('task_id')}",
        "",
        f"- Total score: {result['score']:.2f} / {result['max_score']:.2f}",
        f"- Accuracy: {result['accuracy']:.2%}",
        "",
    ]
    for turn in result["turns"]:
        lines.extend(
            [
                f"## Turn {turn['idx']}",
                "",
                f"- Score: {turn['score']:.2f} / {turn['max_score']:.2f}",
                f"- Accuracy: {turn['accuracy']:.2%}",
                "",
                "<details><summary>Model output evaluated for this turn</summary>",
                "",
                "````markdown",
                str(turn.get("model_output", "")),
                "````",
                "",
                "</details>",
                "",
            ]
        )
        for i, point in enumerate(turn["points"], start=1):
            status = "PASS" if point["passed"] else "FAIL"
            lines.append(f"### {i}. {status}")
            lines.append("")
            lines.append(point["score_point"])
            lines.append("")
            if point.get("judge_reason"):
                lines.append(f"Reason: {point['judge_reason']}")
                lines.append("")
            if point["matched"]:
                lines.append("Matched:")
                lines.extend(f"- {item}" for item in point["matched"])
                lines.append("")
            if point["missing"]:
                lines.append("Missing:")
                lines.extend(f"- {item}" for item in point["missing"])
                lines.append("")
    return "\n".join(lines)


def make_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Evaluation Summary",
        "",
        f"- Runs: {summary['run_count']}",
        f"- Total score: {summary['score']:.2f} / {summary['max_score']:.2f}",
        f"- Accuracy: {summary['accuracy']:.2%}",
        "",
        "| Task | Skill | Run | Score | Accuracy |",
        "|---|---:|---|---:|---:|",
    ]
    for item in summary["runs"]:
        lines.append(
            "| {task_id} | {skill_mode} | {run_id} | {score:.2f}/{max_score:.2f} | {accuracy:.2%} |".format(
                task_id=item.get("task_id", ""),
                skill_mode=item.get("skill_mode", ""),
                run_id=item.get("run_id", ""),
                score=float(item.get("score", 0.0)),
                max_score=float(item.get("max_score", 0.0)),
                accuracy=float(item.get("accuracy", 0.0)),
            )
        )
    return "\n".join(lines)


def common_parent(paths: list[Path]) -> Path:
    if not paths:
        return RUNS_ROOT
    try:
        return Path(os.path.commonpath([str(path) for path in paths]))
    except Exception:
        return RUNS_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score isolated nanobot run outputs against task.json score_points.",
    )
    parser.add_argument("--task-json", default=str(DEFAULT_TASK_JSON))
    parser.add_argument(
        "--task-id",
        action="append",
        default=None,
        help="Task id to evaluate. Can be repeated or comma-separated. If omitted with --run-root, inferred from manifest.json.",
    )
    parser.add_argument("--all-tasks", action="store_true", help="Use all task ids when resolving --run-id batch runs.")
    parser.add_argument(
        "--run-root",
        action="append",
        default=None,
        help="Run directory containing responses.jsonl/task_result.json. Can be repeated; parent dirs are searched recursively.",
    )
    parser.add_argument("--runs-root", default=str(RUNS_ROOT), help="Root containing runs/<task_id>/skill_<mode>/<run_id>.")
    parser.add_argument("--run-id", default=None, help="Evaluate this run id for selected tasks under --runs-root.")
    parser.add_argument("--skill-mode", choices=["on", "off", "both"], default=None, help="Filter or construct run roots by skill mode.")
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    parser.add_argument("--judge", choices=["llm", "rule"], default="llm")
    parser.add_argument("--judge-config", default=None, help="Config for the LLM judge. Defaults to <run-root>/config.json.")
    parser.add_argument("--judge-model", default=None, help="Override judge model.")
    parser.add_argument("--judge-provider", default=None, help="Override judge provider.")
    parser.add_argument("--judge-max-tokens", type=int, default=4096)
    parser.add_argument("--judge-temperature", type=float, default=0.0)
    parser.add_argument("--judge-timeout", type=int, default=180, help="Maximum seconds for each LLM judge turn.")
    parser.add_argument("--rule-fallback", action="store_true", help="Use generic rule fallback if LLM judging fails.")
    parser.add_argument("--no-rule-fallback", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of independent run roots to evaluate in parallel. Turns inside one run remain sequential.",
    )
    return parser.parse_args()


def evaluate_run_target(
    *,
    run_root: Path,
    task: dict[str, Any],
    metadata: dict[str, Any],
    args: argparse.Namespace,
    multiple: bool,
    fallback_rule: bool,
) -> dict[str, Any]:
    outputs = load_turn_outputs(run_root)
    print(f"[evaluate] {task.get('task_id')} at {run_root}", flush=True)
    if args.judge == "rule":
        result = evaluate(task, outputs)
        result["judge"] = "rule"
    else:
        judge_config = (
            Path(args.judge_config).expanduser().resolve()
            if args.judge_config
            else run_root / "config.json"
        )
        if not judge_config.is_file():
            raise FileNotFoundError(f"Judge config not found: {judge_config}")
        result = evaluate_llm(
            task=task,
            outputs=outputs,
            config_path=judge_config,
            judge_model=args.judge_model,
            judge_provider=args.judge_provider,
            max_tokens=args.judge_max_tokens,
            temperature=args.judge_temperature,
            judge_timeout=args.judge_timeout,
            fallback_rule=fallback_rule,
        )

    result["run_root"] = str(run_root)
    result["skill_mode"] = metadata.get("skill_mode") or infer_skill_mode_from_run_root(run_root)
    result["run_id"] = metadata.get("run_id") or run_root.name
    result["outputs_count"] = len(outputs)

    output_json = (
        Path(args.output_json).expanduser().resolve()
        if args.output_json and not multiple
        else run_root / "evaluation_result.json"
    )
    output_md = (
        Path(args.output_md).expanduser().resolve()
        if args.output_md and not multiple
        else run_root / "evaluation_report.md"
    )
    write_json(output_json, result)
    write_text(output_md, make_markdown_report(result))

    item = {
        "task_id": result.get("task_id"),
        "run_root": str(run_root),
        "skill_mode": result.get("skill_mode"),
        "run_id": result.get("run_id"),
        "judge": result.get("judge"),
        "judge_model": result.get("judge_model"),
        "score": float(result.get("score", 0.0)),
        "max_score": float(result.get("max_score", 0.0)),
        "accuracy": float(result.get("accuracy", 0.0)),
        "evaluation_result_json": str(output_json),
        "evaluation_report_md": str(output_md),
    }
    print(
        f"[score] {item['task_id']} {item['skill_mode']} {item['run_id']}: "
        f"{item['score']:.2f}/{item['max_score']:.2f} ({item['accuracy']:.2%})",
        flush=True,
    )
    print(f"[wrote] {output_json}", flush=True)
    print(f"[wrote] {output_md}", flush=True)
    return item


def main() -> int:
    args = parse_args()
    task_json = Path(args.task_json).expanduser().resolve()
    tasks = load_tasks(task_json)
    tasks_by_id = task_map(tasks)
    requested_task_ids = split_task_ids(args.task_id)
    selected_task_ids = select_task_ids(
        tasks=tasks,
        requested_ids=requested_task_ids,
        all_tasks=args.all_tasks,
    )
    all_task_ids = selected_task_ids or list(tasks_by_id.keys())
    run_roots = resolve_run_roots(
        explicit_run_roots=args.run_root or [],
        runs_root=Path(args.runs_root).expanduser().resolve(),
        run_id=args.run_id,
        skill_mode=args.skill_mode,
        task_ids=selected_task_ids,
        all_task_ids=all_task_ids,
    )
    if not run_roots:
        raise FileNotFoundError("No run roots matched the requested task/run filters.")

    eval_targets: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    for run_root in run_roots:
        inferred_task_id = infer_task_id_from_run_root(run_root, tasks_by_id)
        if selected_task_ids and inferred_task_id and inferred_task_id not in selected_task_ids:
            continue
        if inferred_task_id is None:
            if len(selected_task_ids) == 1:
                inferred_task_id = selected_task_ids[0]
            else:
                raise ValueError(
                    f"Could not infer task_id for {run_root}. "
                    "Pass --task-id, or make sure the run has manifest.json."
                )
        task = tasks_by_id.get(inferred_task_id)
        if task is None:
            raise ValueError(f"Task id from run is not present in task.json: {inferred_task_id}")
        eval_targets.append((run_root, task, read_run_metadata(run_root)))

    if not eval_targets:
        raise FileNotFoundError("No run roots remained after task filters.")

    multiple = len(eval_targets) > 1
    fallback_rule = args.rule_fallback and not args.no_rule_fallback
    summary_items: list[dict[str, Any]] = []
    total_score = 0.0
    max_score = 0.0
    concurrency = max(1, int(args.concurrency))

    def add_summary_item(item: dict[str, Any]) -> None:
        nonlocal total_score, max_score
        summary_items.append(item)
        total_score += item["score"]
        max_score += item["max_score"]

    if concurrency == 1:
        for run_root, task, metadata in eval_targets:
            item = evaluate_run_target(
                run_root=run_root,
                task=task,
                metadata=metadata,
                args=args,
                multiple=multiple,
                fallback_rule=fallback_rule,
            )
            add_summary_item(item)
    else:
        print(f"[parallel] evaluating up to {concurrency} independent run(s) at a time", flush=True)
        target_iter = iter(eval_targets)
        active: dict[Any, tuple[Path, dict[str, Any], dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            def submit_next() -> bool:
                try:
                    run_root, task, metadata = next(target_iter)
                except StopIteration:
                    return False
                future = executor.submit(
                    evaluate_run_target,
                    run_root=run_root,
                    task=task,
                    metadata=metadata,
                    args=args,
                    multiple=multiple,
                    fallback_rule=fallback_rule,
                )
                active[future] = (run_root, task, metadata)
                return True

            for _ in range(concurrency):
                if not submit_next():
                    break

            while active:
                done, _ = wait(active.keys(), return_when=FIRST_COMPLETED)
                for future in done:
                    active.pop(future)
                    item = future.result()
                    add_summary_item(item)
                    submit_next()

    summary_items.sort(
        key=lambda item: (
            str(item.get("task_id", "")),
            str(item.get("skill_mode", "")),
            str(item.get("run_id", "")),
        )
    )

    if multiple or args.output_json or args.output_md:
        summary = {
            "run_count": len(summary_items),
            "score": total_score,
            "max_score": max_score,
            "accuracy": total_score / max_score if max_score else 0.0,
            "runs": summary_items,
        }
        if multiple:
            default_summary_dir = common_parent([root for root, _, _ in eval_targets])
            summary_json = (
                Path(args.output_json).expanduser().resolve()
                if args.output_json
                else default_summary_dir / "evaluation_summary.json"
            )
            summary_md = (
                Path(args.output_md).expanduser().resolve()
                if args.output_md
                else default_summary_dir / "evaluation_summary.md"
            )
            write_json(summary_json, summary)
            write_text(summary_md, make_summary_markdown(summary))
            print(f"[summary] {summary['score']:.2f}/{summary['max_score']:.2f} ({summary['accuracy']:.2%})")
            print(f"[wrote] {summary_json}")
            print(f"[wrote] {summary_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
