"""Run dataset tasks in fresh, skill-controlled nanobot workspaces.

This runner prepares isolated workspaces for tasks declared in datasets/task.json
and can optionally execute each turn. It writes unified benchmark outputs in
addition to logs so downstream evaluators do not need to parse terminal text.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_TASK_JSON = REPO_ROOT / "datasets" / "task.json"
RUNS_ROOT = REPO_ROOT / "runs"
FILE_READER_SKILL = "benchmark-file-reader"

AGENT_DEFAULT_KEYS_TO_COPY = {
    "model",
    "provider",
    "maxTokens",
    "contextWindowTokens",
    "contextBlockLimit",
    "temperature",
    "maxToolIterations",
    "maxConcurrentSubagents",
    "maxToolResultChars",
    "providerRetryMode",
    "toolHintMaxLength",
    "reasoningEffort",
    "botName",
    "botIcon",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


TRANSIENT_WINDOWS_IO_RETRIES = 8
TRANSIENT_WINDOWS_IO_BASE_DELAY_SECONDS = 0.05


def _is_transient_windows_io_error(exc: OSError) -> bool:
    return os.name == "nt" and isinstance(exc, PermissionError)


def _with_transient_io_retry(action: Any) -> Any:
    for attempt in range(TRANSIENT_WINDOWS_IO_RETRIES):
        try:
            return action()
        except PermissionError as exc:
            if not _is_transient_windows_io_error(exc) or attempt == TRANSIENT_WINDOWS_IO_RETRIES - 1:
                raise
            time.sleep(TRANSIENT_WINDOWS_IO_BASE_DELAY_SECONDS * (attempt + 1))
    raise RuntimeError("unreachable transient IO retry state")


def write_json(path: Path, payload: Any) -> None:
    def action() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")

    _with_transient_io_retry(action)


def write_text(path: Path, text: str) -> None:
    def action() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    _with_transient_io_retry(action)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_system_prompt_snapshot(
    *,
    run_root: Path,
    idx: int,
    system_prompt: str,
) -> Path:
    """Persist the system prompt sent context for audit/debugging."""
    path = run_root / "system_prompts" / f"turn_{idx:02d}.system.md"
    write_text(path, system_prompt)
    return path


def timestamp_run_id() -> str:
    return datetime.now().strftime("run_%Y%m%d_%H%M%S")


def safe_name(value: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if ch in bad else ch for ch in value).strip() or "task"


def discover_builtin_skills() -> list[str]:
    skills_dir = REPO_ROOT / "nanobot" / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(
        child.name
        for child in skills_dir.iterdir()
        if child.is_dir() and (child / "SKILL.md").is_file()
    )


def discover_dataset_skills(skills_root: Path | None = None) -> list[str]:
    skills_dir = skills_root or (REPO_ROOT / "datasets" / "skills")
    if not skills_dir.is_dir():
        return []
    return sorted(
        child.name
        for child in skills_dir.iterdir()
        if child.is_dir() and (child / "SKILL.md").is_file()
    )


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


def select_tasks(
    *,
    task_json: Path,
    task_ids: list[str],
    all_tasks: bool,
) -> list[dict[str, Any]]:
    tasks = load_tasks(task_json)
    by_id = {str(task.get("task_id")): task for task in tasks if task.get("task_id")}
    if all_tasks and task_ids:
        raise ValueError("Use either --all-tasks or --task-id, not both.")
    if all_tasks:
        return tasks
    if task_ids:
        selected: list[dict[str, Any]] = []
        missing: list[str] = []
        for task_id in task_ids:
            task = by_id.get(task_id)
            if task is None:
                missing.append(task_id)
            else:
                selected.append(task)
        if missing:
            raise ValueError(f"Task id not found: {', '.join(missing)}")
        return selected
    task = tasks[0]
    if not isinstance(task, dict):
        raise ValueError("First task entry is not an object")
    return [task]


def default_base_config_path() -> Path | None:
    candidate = Path.home() / ".nanobot" / "config.json"
    return candidate if candidate.is_file() else None


def load_base_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"Base config not found: {path}")
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Base config must be a JSON object: {path}")
    return data


def build_config(
    *,
    base_config: dict[str, Any],
    workspace: Path,
    allowed_skills: list[str],
    skills_root: Path,
    skill_mode: str,
    timezone: str,
    max_tool_iterations: int | None,
    sandbox: str,
) -> dict[str, Any]:
    base_defaults = (
        base_config.get("agents", {}).get("defaults", {})
        if isinstance(base_config.get("agents"), dict)
        else {}
    )
    copied_defaults = {
        key: value
        for key, value in base_defaults.items()
        if key in AGENT_DEFAULT_KEYS_TO_COPY
    }

    disabled = set(discover_builtin_skills())
    disabled.update(skill for skill in discover_dataset_skills(skills_root) if skill not in allowed_skills)
    defaults: dict[str, Any] = {
        **copied_defaults,
        "workspace": str(workspace),
        "timezone": timezone,
        "unifiedSession": False,
        "idleCompactAfterMinutes": 0,
        "maxMessages": 200,
        "disabledSkills": sorted(disabled),
        "dream": {
            "intervalH": 999999,
            "maxBatchSize": 1,
            "maxIterations": 1,
            "annotateLineAges": False,
        },
    }
    if max_tool_iterations is not None:
        defaults["maxToolIterations"] = max_tool_iterations

    return {
        "providers": base_config.get("providers", {}),
        "agents": {"defaults": defaults},
        "channels": {
            "sendProgress": False,
            "sendToolHints": False,
            "sendMaxRetries": 1,
        },
        "tools": {
            "restrictToWorkspace": True,
            "exec": {"sandbox": "" if sandbox == "none" else sandbox},
            "web": {"enable": False},
            "my": {"enable": False, "allowSet": False},
            "imageGeneration": {"enabled": False},
            "mcpServers": {},
        },
    }


def stage_task_assets(
    task: dict[str, Any],
    workspace: Path,
    data_root: Path,
    asset_mode: str,
) -> list[dict[str, str]]:
    copied: list[dict[str, str]] = []
    for asset in task.get("data_assets", []):
        if not isinstance(asset, dict):
            continue
        src_rel = asset.get("path")
        env_rel = asset.get("env_path")
        if not isinstance(src_rel, str) or not isinstance(env_rel, str):
            raise ValueError(f"Invalid data asset entry: {asset}")
        src = data_root / src_rel
        dst = workspace / env_rel
        if not src.is_file():
            raise FileNotFoundError(f"Task asset not found: {src}")
        expected_sha256 = asset.get("sha256")
        if expected_sha256 and sha256_file(src) != expected_sha256:
            raise ValueError(f"Task asset SHA-256 mismatch: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if asset_mode == "copy":
            _with_transient_io_retry(lambda: shutil.copy2(src, dst))
        elif asset_mode == "hardlink":
            try:
                _with_transient_io_retry(lambda: os.link(src, dst))
            except OSError as exc:
                raise OSError(
                    f"Could not hard-link task asset {src} to {dst}. "
                    "Hard-link mode requires data_root and runs/ to be on the same filesystem. "
                    "Move the shared datasets under the project filesystem or use --asset-mode copy."
                ) from exc
        else:
            raise ValueError(f"Unsupported asset mode: {asset_mode}")
        if expected_sha256 and sha256_file(dst) != expected_sha256:
            raise ValueError(f"Staged task asset SHA-256 mismatch: {dst}")
        copied.append(
            {
                "source": str(src),
                "destination": str(dst),
                "mode": asset_mode,
                "sha256": str(expected_sha256 or sha256_file(dst)),
            }
        )
    return copied


def copy_allowed_skills(
    *,
    allowed_skills: list[str],
    workspace: Path,
    skills_root: Path,
    extra_skill_sources: dict[str, Path] | None,
    skill_mode: str,
    skill_policy: str,
) -> list[dict[str, str]]:
    if skill_mode == "off" and not allowed_skills:
        (workspace / "skills").mkdir(parents=True, exist_ok=True)
        return []

    copied: list[dict[str, str]] = []
    source_root = skills_root
    target_root = workspace / "skills"
    target_root.mkdir(parents=True, exist_ok=True)
    extra_skill_sources = extra_skill_sources or {}
    for skill in allowed_skills:
        src = extra_skill_sources.get(skill, source_root / skill)
        dst = target_root / skill
        src_skill = src / "SKILL.md"
        if not src_skill.is_file():
            raise FileNotFoundError(f"Allowed skill not found: {src}")
        if dst.exists():
            _with_transient_io_retry(lambda: shutil.rmtree(dst))
        # Interpreter caches are not Skill assets and their expanded filenames
        # can exceed the Windows path limit inside deeply nested run roots.
        _with_transient_io_retry(
            lambda: shutil.copytree(
                src,
                dst,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
        )
        system_prompt_loaded = "false"
        if skill_policy == "force-use":
            # Legacy compatibility: force-use makes Nanobot load full skill bodies
            # into Active Skills. The new required experiment mode instead records
            # explicit read_file usage and does not rely on always=true.
            force_skill_into_system_prompt(dst / "SKILL.md")
            system_prompt_loaded = "true"
        copied.append(
            {
                "source": str(src),
                "destination": str(dst),
                "description_only": "false",
                "system_prompt_loaded": system_prompt_loaded,
            }
        )
    return copied


def force_skill_into_system_prompt(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", content, re.DOTALL)
    force_lines = ["always: true", "benchmark_force_use: true"]
    if match:
        frontmatter = match.group(1)
        body = content[match.end():]
        kept = [
            line
            for line in frontmatter.splitlines()
            if not re.match(r"^\s*(always|benchmark_force_use)\s*:", line)
        ]
        new_frontmatter = "\n".join([*kept, *force_lines]).strip()
        write_text(path, f"---\n{new_frontmatter}\n---\n\n{body.lstrip()}")
        return
    write_text(path, f"---\n{chr(10).join(force_lines)}\n---\n\n{content}")


def extract_skill_description(path: Path, fallback: str = "") -> str:
    if not path.is_file():
        return fallback
    content = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\r?\n(.*?)\r?\n---", content, re.DOTALL)
    if match:
        frontmatter = match.group(1)
        desc_match = re.search(
            r"^description\s*:\s*(.+?)\s*$",
            frontmatter,
            re.MULTILINE,
        )
        if desc_match:
            return desc_match.group(1).strip().strip("\"'")
    return fallback


def write_description_only_skill(path: Path, skill: str, description: str) -> None:
    safe_description = description.replace("\\", "\\\\").replace('"', '\\"')
    write_text(
        path,
        f"""---
name: "{skill}"
description: "{safe_description}"
benchmark_description_only: true
---

# {skill}

Description-only benchmark skill stub.

This isolated benchmark exposes only this skill description:

{description}
""",
    )


def skill_description(workspace: Path, skill: str) -> str:
    path = workspace / "skills" / skill / "SKILL.md"
    return extract_skill_description(path, fallback=skill)


def build_skill_description_text(workspace: Path, allowed_skills: list[str]) -> str:
    lines = []
    for skill in allowed_skills:
        description = skill_description(workspace, skill)
        if description:
            lines.append(f"- {skill}: {description}")
        else:
            lines.append(f"- {skill}")
    return "\n".join(lines)


def _build_turn_prompt_legacy_corrupted(
    *,
    task: dict[str, Any],
    turn: dict[str, Any],
    skill_mode: str,
    allowed_skills: list[str],
    skill_policy: str,
    skill_description_text: str = "",
    preloaded_skill_context: str = "",
    required_skills: list[str] | None = None,
    skill_experiment_mode: str = "correct",
) -> str:
    required_skills = required_skills or []
    if task.get("minimal_prompt") and skill_mode == "off":
        instruction = str(task.get("instruction", "")).strip()
        question = str(turn.get("question", "")).strip()
        return f"{instruction}\n\n{question}".strip()

    if allowed_skills:
        skill_list = "、".join(allowed_skills)
        required_list = "、".join(required_skills)
        required_paths = "、".join(f"skills/{name}/SKILL.md" for name in required_skills)
        if skill_policy == "force-use":
            skill_text = (
                f"本次 run 的完整 skill 已作为 Active Skills 注入系统提示词：{skill_list}。"
                "这是旧版 force-use 策略；仍然只允许使用这些 skill。"
            )
        elif skill_experiment_mode == "required":
            skill_text = (
                f"本次 run 暴露的 workspace skills 为：{skill_list}。\n"
                f"任务声明的必需 skills 为：{required_list}。\n"
                f"在正式分析和回答前，必须先用 read_file 读取这些必需 skill 文件：{required_paths}。\n"
                "系统提示词中的 skill 列表只提供 name 与 description；读取完整 SKILL.md 后再按其中步骤执行。\n"
                "对每个 required skill，必须调用该 skill 自带的确定性脚本，并把主结构化证据写到 "
                "skill_evidence/<skill-name>.json。若该 skill 的 scripts 目录含 validate*.py，还必须运行 validator，"
                "把结果写到 skill_evidence/<skill-name>.validation.json，并确认 status=ok 后才能回答。\n"
                "先按题面确定参数和准备中间表；证据文件中不得写入标准答案、预期获胜实体或题面未给出的答案提示。"
            )
        elif skill_experiment_mode == "all":
            skill_text = (
                f"本次 run 暴露全部候选 workspace skills：{skill_list}。\n"
                f"{skill_description_text}\n"
                "先根据每个 skill 的 description 判断是否适用；只有决定使用某个 skill 时，才用 read_file 读取对应 SKILL.md。"
            )
        else:
            skill_text = (
                f"本次 run 只暴露任务声明的正确候选 skills：{skill_list}。\n"
                f"{skill_description_text}\n"
                "先根据每个 skill 的 description 判断是否适用；只有决定使用某个 skill 时，才用 read_file 读取对应 SKILL.md。"
            )
    else:
        skill_text = "本次 run 禁止使用任何 skill；不要读取 workspace/skills 下的内容。"

    related = turn.get("related_tables") or []
    related_text = "\n".join(f"- {item}" for item in related if isinstance(item, str))
    if not related_text:
        related_text = "- 无"

    return f"""你正在执行一个隔离的 nanobot benchmark 任务。请严格遵守任务说明，直接回答当前轮问题。

全局任务说明：{task.get("instruction", "")}

隔离与工具约束：
- 只能使用当前 workspace 内的本地文件。
- 数据文件路径以 workspace 为根目录，例如 datasets/example.xlsx。
- 禁止联网；不要调用 web_search 或 web_fetch。
- 禁止安装、创建、修改或保存新的 skill。
- {skill_text}
- 如果 skill 内容和本任务说明、当前问题或本地数据冲突，以任务说明、当前问题和本地数据为准。

当前轮次：{turn.get("idx")}
当前相关数据表：
{related_text}

当前问题：{turn.get("question", "")}
{preloaded_skill_context}
""".strip()


def build_turn_prompt(
    *,
    task: dict[str, Any],
    turn: dict[str, Any],
    skill_mode: str,
    allowed_skills: list[str],
    skill_policy: str,
    skill_description_text: str = "",
    preloaded_skill_context: str = "",
    required_skills: list[str] | None = None,
    required_read_skills: list[str] | None = None,
    skill_experiment_mode: str = "correct",
) -> str:
    """Build a compact benchmark prompt with an ASCII-only runner wrapper."""
    required_skills = required_skills or []
    required_read_skills = required_read_skills or required_skills
    instruction = str(task.get("instruction", "")).strip()
    question = str(turn.get("question", "")).strip()
    if task.get("minimal_prompt") and skill_mode == "off":
        prompt = f"{instruction}\n\n{question}".strip()
        if "\ufffd" in prompt:
            raise UnicodeError(
                "Benchmark prompt contains Unicode replacement characters; "
                "fix the source encoding before execution."
            )
        return prompt

    if not allowed_skills:
        skill_text = "Skills are disabled for this run. Do not read workspace/skills."
    else:
        skill_list = ", ".join(allowed_skills)
        required_list = ", ".join(required_skills)
        required_read_list = ", ".join(required_read_skills)
        required_paths = ", ".join(
            f"skills/{name}/SKILL.md" for name in required_read_skills
        )
        if skill_policy == "force-use":
            skill_text = (
                f"You must use these Skills: {skill_list}. Read each SKILL.md and "
                "follow its input contract, execution steps, and validation rules."
            )
        elif skill_experiment_mode == "required":
            skill_text = (
                f"Available workspace Skills: {skill_list}.\n"
                f"Skills selected for this task: {required_read_list or 'none'}.\n"
                f"Skills requiring structured execution: {required_list or 'none'}.\n"
                f"Before analysis, use read_file to read: {required_paths or 'none'}.\n"
                "For each Skill requiring structured execution, fill runtime parameters "
                "only from the task and data. Run its deterministic script when present. "
                "Write primary evidence to skill_evidence/<skill-name>.json. If validate*.py "
                "exists, run it and write skill_evidence/<skill-name>.validation.json. "
                "Only validated structured evidence may support the final answer. Evidence "
                "must not contain the gold answer or entities not supplied by the task or data."
            )
        else:
            mode_text = "all candidate" if skill_experiment_mode == "all" else "task-candidate"
            skill_text = (
                f"This run provides {mode_text} Skills: {skill_list}.\n"
                f"{skill_description_text}\n"
                "Decide applicability from each description. Read a Skill's SKILL.md only "
                "after selecting that Skill."
            )

    prompt = f"""You are executing an isolated Nanobot benchmark task.

Task instruction:
{instruction}

Execution constraints:
- Use only local files in the current workspace.
- Do not access the internet, install dependencies, or create or modify Skills.
- {skill_text}
- If a Skill conflicts with the task or local data, follow the task and local data.

Current turn: {turn.get("idx")}
Question:
{question}
{preloaded_skill_context}
""".strip()
    if "\ufffd" in prompt:
        raise UnicodeError(
            "Benchmark prompt contains Unicode replacement characters; "
            "fix the source encoding before execution."
        )
    return prompt


def _build_preloaded_skill_context_legacy_corrupted(
    *,
    workspace: Path,
    allowed_skills: list[str],
    skill_mode: str,
    skill_policy: str,
) -> str:
    if skill_policy != "preload" or not allowed_skills:
        return ""

    parts: list[str] = []
    for skill in allowed_skills:
        path = workspace / "skills" / skill / "SKILL.md"
        if not path.is_file():
            raise FileNotFoundError(f"Allowed skill not found for preload: {path}")
        description = skill_description(workspace, skill)
        parts.append(f"## Skill Description: {skill}\n\n{description}")
    return "\n\n预加载 skill description：\n" + "\n\n---\n\n".join(parts)


def build_preloaded_skill_context(
    *,
    workspace: Path,
    allowed_skills: list[str],
    skill_mode: str,
    skill_policy: str,
) -> str:
    if skill_policy != "preload" or not allowed_skills:
        return ""
    parts: list[str] = []
    for skill in allowed_skills:
        path = workspace / "skills" / skill / "SKILL.md"
        if not path.is_file():
            raise FileNotFoundError(f"Allowed skill not found for preload: {path}")
        parts.append(
            f"## Skill Description: {skill}\n\n"
            f"{skill_description(workspace, skill)}"
        )
    return "\n\nPreloaded Skill descriptions:\n" + "\n\n---\n\n".join(parts)


def assert_allowed_skills(workspace: Path, allowed_skills: list[str], skill_mode: str) -> None:
    skills_dir = workspace / "skills"
    if not skills_dir.exists():
        return
    expected = set(allowed_skills)
    actual = {child.name for child in skills_dir.iterdir() if child.is_dir()}
    extra = sorted(actual - expected)
    if extra:
        raise RuntimeError(
            "Unexpected skill directory created or copied: "
            + ", ".join(extra)
            + f" under {skills_dir}"
        )


def _normalize_tool_path(value: str) -> str:
    return value.replace("\\", "/").strip().lower()


def detect_skill_usage(manifest: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(manifest["workspace"])
    allowed_skills = list(manifest.get("allowed_skills", []))
    usage = {
        "skill_mode": manifest.get("skill_mode"),
        "skill_policy": manifest.get("skill_policy", "available"),
        "skill_experiment_mode": manifest.get("skill_experiment_mode", "correct"),
        "allowed_skills": allowed_skills,
        "available_skills": list(manifest.get("available_skills", allowed_skills)),
        "required_skills": list(manifest.get("required_skills", [])),
        "required_read_skills": list(
            manifest.get("required_read_skills", manifest.get("required_skills", []))
        ),
        "description_only_skills": False,
        "skill_ablation_view": manifest.get("skill_ablation_view", "full"),
        "validation_disabled_by_ablation": manifest.get("skill_ablation_view")
        in {"description_only", "text_only", "no_validator"},
        "system_prompt_loaded": bool(allowed_skills) and manifest.get("skill_policy") == "force-use",
        "description_preloaded": manifest.get("skill_policy") == "preload" and bool(allowed_skills),
        "description_presented": bool(allowed_skills),
        "skills": {
            skill: {
                "read_file_called": False,
                "read_file_lines": [],
                "read_file_paths": [],
                "script_called": False,
                "script_required": False,
                "script_call_lines": [],
                "script_call_commands": [],
                "evidence_level": "presented_only",
                "structured_evidence_path": None,
                "structured_evidence_valid": False,
                "validation_required": False,
                "validation_path": None,
                "validation_valid": False,
                "structured_execution_compliant": False,
            }
            for skill in allowed_skills
        },
        "session_files": [],
    }
    if manifest.get("skill_mode") == "off":
        usage.update(
            {
                "any_skill_read": None,
                "required_skills_all_read": None,
                "required_skills_missing_reads": None,
                "script_skills": None,
                "any_skill_script_called": None,
                "required_skills_with_script_calls": None,
                "structured_skills": None,
                "required_skills_all_structured": None,
                "required_skills_missing_structured_evidence": None,
            }
        )
        return usage
    sessions_dir = workspace / "sessions"
    if not sessions_dir.is_dir():
        usage["any_skill_read"] = False
        usage["required_skills_all_read"] = not usage["required_read_skills"]
        usage["required_skills_missing_reads"] = list(usage["required_read_skills"])
        usage["script_skills"] = []
        usage["any_skill_script_called"] = False
        usage["required_skills_with_script_calls"] = []
        usage["structured_skills"] = []
        usage["required_skills_all_structured"] = not usage["required_skills"]
        usage["required_skills_missing_structured_evidence"] = list(usage["required_skills"])
        usage["selected_skills"] = (
            list(usage.get("allowed_skills") or [])
            if usage.get("skill_experiment_mode") == "required"
            else []
        )
        return usage

    expected_paths = {
        skill: f"skills/{skill}/skill.md".lower()
        for skill in allowed_skills
    }
    for session_path in sorted(sessions_dir.glob("*.jsonl")):
        usage["session_files"].append(str(session_path))
        with session_path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for tool_call in event.get("tool_calls") or []:
                    function = tool_call.get("function") or {}
                    function_name = str(function.get("name", ""))
                    raw_args = function.get("arguments") or "{}"
                    if isinstance(raw_args, dict):
                        args = raw_args
                    else:
                        try:
                            args = json.loads(raw_args)
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                    if function_name == "read_file":
                        path_value = args.get("path", "")
                        if isinstance(path_value, str):
                            normalized = _normalize_tool_path(path_value)
                            for skill, expected in expected_paths.items():
                                if normalized.endswith(expected):
                                    usage["skills"][skill]["read_file_called"] = True
                                    usage["skills"][skill]["read_file_lines"].append(line_no)
                                    usage["skills"][skill]["read_file_paths"].append(path_value)
                    if function_name in {"exec", "shell", "run_command"}:
                        command = args.get("command", args.get("cmd", ""))
                        if not isinstance(command, str):
                            continue
                        normalized_command = _normalize_tool_path(command)
                        for skill in allowed_skills:
                            script_pattern = (
                                rf"(?:^|[\s\"'=])(?:\./)?skills/{re.escape(skill.lower())}/"
                                rf"scripts/[^\s\"';&|]+\.py(?:[\s\"';&|]|$)"
                            )
                            if re.search(script_pattern, normalized_command):
                                usage["skills"][skill]["script_called"] = True
                                usage["skills"][skill]["script_call_lines"].append(line_no)
                                usage["skills"][skill]["script_call_commands"].append(command)
    read_skills = [
        skill for skill, item in usage["skills"].items()
        if item.get("read_file_called")
    ]
    required = list(usage.get("required_skills", []))
    required_reads = list(usage.get("required_read_skills", required))
    usage["read_skills"] = read_skills
    usage["any_skill_read"] = bool(read_skills)
    usage["required_skills_all_read"] = all(
        usage["skills"].get(skill, {}).get("read_file_called")
        for skill in required_reads
    )
    usage["required_skills_missing_reads"] = [
        skill for skill in required_reads
        if not usage["skills"].get(skill, {}).get("read_file_called")
    ]
    script_skills = [
        skill for skill, item in usage["skills"].items()
        if item.get("script_called")
    ]
    evidence_root = workspace / "skill_evidence"
    for skill, item in usage["skills"].items():
        evidence_path = evidence_root / f"{skill}.json"
        validation_path = evidence_root / f"{skill}.validation.json"
        scripts_dir = workspace / "skills" / skill / "scripts"
        validator_required = any(scripts_dir.glob("validate*.py"))
        script_required = any(
            path.is_file() and not path.name.startswith("validate")
            for path in scripts_dir.glob("*.py")
        )
        item["script_required"] = script_required
        item["validation_required"] = validator_required
        if evidence_path.is_file():
            item["structured_evidence_path"] = str(evidence_path)
            try:
                evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
                item["structured_evidence_valid"] = bool(
                    evidence.get("status") == "ok" or evidence.get("valid") is True
                )
            except (OSError, json.JSONDecodeError, AttributeError):
                item["structured_evidence_valid"] = False
        if validation_path.is_file():
            item["validation_path"] = str(validation_path)
            try:
                validation = json.loads(validation_path.read_text(encoding="utf-8-sig"))
                item["validation_valid"] = bool(
                    validation.get("status") == "ok" or validation.get("valid") is True
                )
            except (OSError, json.JSONDecodeError, AttributeError):
                item["validation_valid"] = False
        evidence_proves_execution = bool(
            item.get("structured_evidence_valid")
            and (not validator_required or item.get("validation_valid"))
        )
        if script_required and not item.get("script_called") and evidence_proves_execution:
            item["script_called"] = True
            item["execution_detection_source"] = "validated_evidence_fallback"
        elif item.get("script_called"):
            item["execution_detection_source"] = "command_trace"
        item["structured_execution_compliant"] = bool(
            item.get("read_file_called")
            and (not script_required or item.get("script_called"))
            and item.get("structured_evidence_valid")
            and (not validator_required or item.get("validation_valid"))
        )
        if item["structured_execution_compliant"]:
            item["evidence_level"] = "structured_validated"
        elif item.get("script_called"):
            item["evidence_level"] = "script_executed"
        elif item.get("read_file_called"):
            item["evidence_level"] = "body_read"
    script_skills = [
        skill for skill, item in usage["skills"].items()
        if item.get("script_called")
    ]
    usage["script_skills"] = script_skills
    usage["any_skill_script_called"] = bool(script_skills)
    usage["required_skills_with_script_calls"] = [
        skill for skill in required
        if usage["skills"].get(skill, {}).get("script_called")
    ]
    usage["structured_skills"] = [
        skill for skill, item in usage["skills"].items()
        if item.get("structured_execution_compliant")
    ]
    usage["required_skills_all_structured"] = all(
        usage["skills"].get(skill, {}).get("structured_execution_compliant")
        for skill in required
    )
    usage["required_skills_missing_structured_evidence"] = [
        skill for skill in required
        if not usage["skills"].get(skill, {}).get("structured_execution_compliant")
    ]
    if usage.get("skill_experiment_mode") == "required":
        usage["selected_skills"] = list(usage.get("allowed_skills") or [])
    else:
        usage["selected_skills"] = list(read_skills)
    return usage


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    def action() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    _with_transient_io_retry(action)


def detect_agent_error(content: str) -> str | None:
    stripped = content.strip()
    lowered = stripped.lower()
    if stripped.startswith("Error:") or lowered.startswith("error:"):
        return stripped.splitlines()[0][:1000]
    for token in (
        "invalidsubscription",
        "does not have a valid codingplan subscription",
        "llm returned error",
        "maximum number of tool call iterations",
        "max tool iterations",
        "without completing the task",
    ):
        if token in lowered:
            return stripped.splitlines()[0][:1000] if stripped else token
    return None


INFRASTRUCTURE_ERROR_PATTERNS: tuple[tuple[str, str], ...] = (
    ("request timed out", "llm_timeout"),
    ("timed out after", "llm_timeout"),
    ("timeouterror", "llm_timeout"),
    ("timeout expired", "llm_timeout"),
    ("error calling llm", "llm_provider_error"),
    ("api connection error", "llm_connection_error"),
    ("connection reset", "llm_connection_error"),
    ("connection refused", "llm_connection_error"),
    ("service unavailable", "llm_service_unavailable"),
    ("rate limit", "llm_rate_limit"),
    ("limit_burst_rate", "llm_rate_limit"),
    ("request rate increased too quickly", "llm_rate_limit"),
    ("data_inspection_failed", "llm_content_filter"),
    ("inappropriate content", "llm_content_filter"),
    ("too many requests", "llm_rate_limit"),
    ("http 429", "llm_rate_limit"),
    ("event loop is closed", "runtime_event_loop_error"),
    ("no api key configured", "configuration_error"),
)


def detect_infrastructure_error(content: str) -> str | None:
    """Classify transient/provider failures that must not be scored as ability errors."""
    lowered = str(content or "").strip().casefold()
    for pattern, code in INFRASTRUCTURE_ERROR_PATTERNS:
        if pattern in lowered:
            return code
    return None


def extract_json_payload(text: str) -> Any | None:
    """Best-effort extraction of a JSON object/array from a model response."""
    stripped = text.strip()
    if not stripped:
        return None

    fence_markers = ("```json", "```JSON", "```")
    for marker in fence_markers:
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


FINAL_ANSWER_REPAIR_TIMEOUT_SECONDS = 120
FINAL_OPTION_RE = re.compile(
    r"(?:final\s+answer|answer|choice|option|\u6700\u7ec8\u7b54\u6848|\u7b54\u6848)"
    r"\s*[:\uff1a]?\s*\(?([A-Z])\)?(?:[.\u3001\uff1a:\s]|$)",
    re.I,
)


def _normalized_answer_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def task_answer_options(task: dict[str, Any]) -> list[str]:
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    raw = metadata.get("options") or task.get("options") or []
    return [str(value).strip() for value in raw if str(value).strip()]


def final_answer_issue(content: str, task: dict[str, Any]) -> str | None:
    """Return a format/completion issue without consulting benchmark gold."""
    stripped = str(content or "").strip()
    if not stripped:
        return "empty_output"
    agent_error = detect_agent_error(stripped)
    if agent_error:
        return "agent_error"
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    contract = str(metadata.get("answer_contract") or "").casefold()
    if contract in {"json_array", "json_object"}:
        parsed = extract_json_payload(stripped)
        if contract == "json_array" and isinstance(parsed, list):
            return None
        if contract == "json_object" and isinstance(parsed, dict):
            return None
        return f"missing_or_invalid_{contract}"
    if stripped[:1] in {"[", "{"}:
        try:
            json.loads(stripped)
            return "nonanswer_payload"
        except json.JSONDecodeError:
            pass

    options = task_answer_options(task)
    if not options:
        return None
    tail = stripped[-1600:]
    explicit = FINAL_OPTION_RE.findall(tail)
    valid_labels = {
        chr(ord("A") + index)
        for index in range(len(options))
    }
    if explicit and explicit[-1].upper() in valid_labels:
        return None
    normalized_tail = _normalized_answer_text(tail)
    matched = [
        option
        for option in options
        if _normalized_answer_text(option)
        and _normalized_answer_text(option) in normalized_tail
    ]
    if len(matched) == 1:
        return None
    return "missing_or_ambiguous_final_option"


def build_final_answer_repair_prompt(task: dict[str, Any], issue: str) -> str:
    """Ask for one format-only repair without exposing gold or a solution method."""
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    answer_contract = str(metadata.get("answer_contract") or "").casefold()
    output_fields = [str(field) for field in metadata.get("output_fields", [])]
    field_text = ", ".join(output_fields)
    if answer_contract == "json_array":
        contract = (
            "Output only one valid JSON array with no Markdown fence or commentary. "
            f"Each result object must contain exactly these fields: {field_text}."
        )
    elif answer_contract == "json_object":
        contract = (
            "Output only one valid JSON object with no Markdown fence or commentary. "
            f"The object must contain exactly these fields: {field_text}."
        )
    elif task_answer_options(task):
        contract = (
            "For a multiple-choice question, output exactly one line in the form "
            "'Final Answer: <option label>. <option text>' using one original option."
        )
    else:
        contract = (
            "Output exactly one line beginning 'Final Answer:' followed by the requested "
            "number, label, or concise answer."
        )
    return (
        "Your previous response did not satisfy the final-answer contract "
        f"({issue}). Do not call any tools, inspect files, recompute, or add new analysis. "
        "Use only evidence already present in this session and answer the original question. "
        f"{contract}"
    )


def write_unified_outputs(
    *,
    manifest: dict[str, Any],
    task: dict[str, Any],
    records: list[dict[str, Any]],
) -> None:
    """Write evaluator-friendly outputs for the run."""
    run_root = Path(manifest["run_root"])
    skill_usage = detect_skill_usage(manifest)
    skill_usage_path = run_root / "skill_usage.json"
    write_json(skill_usage_path, skill_usage)

    content_records = [record for record in records if isinstance(record.get("content"), str)]
    successful = [record for record in content_records if record.get("returncode") == 0]
    last_content = content_records[-1]["content"] if content_records else ""
    if successful and successful[-1].get("content", "").strip():
        final_content = successful[-1]["content"]
        final_output_source = "successful_turn"
    elif last_content:
        final_content = last_content
        final_output_source = "failed_turn"
    else:
        final_content = ""
        final_output_source = "empty"
    pre_repair_final_content = final_content
    for record in reversed(content_records):
        original_path = record.get("original_response_path")
        if record.get("final_answer_repair_attempted") and original_path:
            path = Path(str(original_path))
            if path.is_file():
                pre_repair_final_content = path.read_text(encoding="utf-8")
            break

    final_md_path = run_root / "final_output.md"
    last_md_path = run_root / "last_output.md"
    write_text(final_md_path, final_content)
    write_text(last_md_path, last_content)

    failure_reason = ""
    for record in reversed(records):
        if isinstance(record.get("error"), str) and record["error"].strip():
            failure_reason = record["error"].strip()
            break
        if isinstance(record.get("content"), str):
            detected = detect_agent_error(record["content"])
            if detected:
                failure_reason = detected
                break
    failure_reason_path: str | None = None
    if failure_reason:
        path = run_root / "failure_reason.txt"
        write_text(path, failure_reason)
        failure_reason_path = str(path)

    parsed = extract_json_payload(final_content)
    final_json_path: str | None = None
    if parsed is not None:
        path = run_root / "final_output.json"
        write_json(path, parsed)
        final_json_path = str(path)

    infrastructure_errors: list[str] = []
    for record in records:
        candidates = (record.get("error"), record.get("content"))
        for candidate in candidates:
            if isinstance(candidate, str):
                code = detect_infrastructure_error(candidate)
                if code:
                    infrastructure_errors.append(code)
                    break
    completed = (
        bool(records)
        and all(r.get("returncode") == 0 for r in records)
        and not infrastructure_errors
        and not failure_reason
    )
    result_status = (
        "completed"
        if completed
        else "infrastructure_error"
        if infrastructure_errors
        else "failed"
    )
    repair_attempts = [
        record for record in records
        if record.get("final_answer_repair_attempted")
    ]
    repair_successes = [
        record for record in repair_attempts
        if record.get("final_answer_repair_succeeded")
    ]
    task_result = {
        "task_id": task.get("task_id"),
        "skill_mode": manifest.get("skill_mode"),
        "run_id": manifest.get("run_id"),
        "status": result_status,
        "failure_type": infrastructure_errors[0] if infrastructure_errors else "agent_error" if failure_reason else "",
        "failure_reason": failure_reason,
        "failure_reason_path": failure_reason_path,
        "final_output_md": str(final_md_path),
        "last_output_md": str(last_md_path),
        "final_output_source": final_output_source,
        "final_output_json": final_json_path,
        "final_output_parseable_json": parsed is not None,
        "final_output": final_content,
        "pre_repair_final_output": pre_repair_final_content,
        "final_answer_repair_attempt_count": len(repair_attempts),
        "final_answer_repair_success_count": len(repair_successes),
        "final_answer_repair_all_succeeded": (
            bool(repair_attempts) and len(repair_attempts) == len(repair_successes)
        ),
        "skill_policy": manifest.get("skill_policy", "available"),
        "skill_experiment_mode": manifest.get("skill_experiment_mode"),
        "skill_usage_json": str(skill_usage_path),
        "skill_usage": skill_usage,
        "turns": records,
    }
    write_json(run_root / "task_result.json", task_result)


def list_all_experiment_skills(skills_root: Path) -> list[str]:
    return [
        name
        for name in discover_dataset_skills(skills_root)
        if name.startswith("tableagent-")
    ]


def resolve_allowed_and_required_skills(
    *,
    task: dict[str, Any],
    skill_mode: str,
    skills_root: Path,
    skill_experiment_mode: str,
    excluded_skills: list[str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    excluded = set(excluded_skills or [])
    declared = [
        str(skill)
        for skill in (task.get("skills") or task.get("required_skills") or task.get("allowed_skills") or [])
    ]
    declared = [
        skill for skill in dict.fromkeys(declared)
        if skill not in excluded
    ]
    if skill_mode == "off":
        return [], declared, []
    if skill_experiment_mode == "all":
        allowed = [
            skill for skill in list_all_experiment_skills(skills_root)
            if skill not in excluded
        ]
    else:
        allowed = declared
    execution_declared = [
        str(skill)
        for skill in (
            task.get("required_execution_skills")
            or (task.get("metadata") or {}).get("required_execution_skills")
            or declared
        )
    ]
    execution_declared = [
        skill for skill in dict.fromkeys(execution_declared)
        if skill in declared
    ]
    required = execution_declared if skill_experiment_mode == "required" else []
    return allowed, declared, required


def prepare_run(
    *,
    task: dict[str, Any],
    skill_mode: str,
    skill_policy: str,
    skill_experiment_mode: str,
    run_id: str,
    base_config: dict[str, Any],
    timezone: str,
    max_tool_iterations: int | None,
    data_root: Path,
    asset_mode: str,
    skills_root: Path,
    extra_skill_paths: list[Path],
    extra_skill_scope: str,
    file_reader_skill: bool,
    excluded_skills: list[str] | None,
    skill_view: str,
    sandbox: str,
    overwrite: bool,
) -> dict[str, Any]:
    task_id = str(task["task_id"])
    run_root = RUNS_ROOT / safe_name(task_id) / f"skill_{skill_mode}" / safe_name(run_id)
    workspace = run_root / "workspace"
    config_path = run_root / "config.json"

    if run_root.exists():
        if not overwrite:
            raise FileExistsError(f"Run directory already exists: {run_root}")
        _with_transient_io_retry(lambda: shutil.rmtree(run_root))

    workspace.mkdir(parents=True, exist_ok=True)
    allowed_skills, task_declared_skills, required_skills = resolve_allowed_and_required_skills(
        task=task,
        skill_mode=skill_mode,
        skills_root=skills_root,
        skill_experiment_mode=skill_experiment_mode,
        excluded_skills=excluded_skills,
    )
    helper_skills: list[str] = []
    extra_skill_sources: dict[str, Path] = {}
    if file_reader_skill and skill_mode == "on" and FILE_READER_SKILL not in allowed_skills:
        allowed_skills.append(FILE_READER_SKILL)
        helper_skills.append(FILE_READER_SKILL)
    use_extra_skills = skill_mode == "on" or extra_skill_scope == "both"
    if use_extra_skills:
        for skill_path in extra_skill_paths:
            skill_name = skill_path.name
            if skill_name not in allowed_skills:
                allowed_skills.append(skill_name)
            if skill_name not in helper_skills:
                helper_skills.append(skill_name)
            extra_skill_sources[skill_name] = skill_path
    assets = stage_task_assets(task, workspace, data_root, asset_mode)
    skills = copy_allowed_skills(
        allowed_skills=allowed_skills,
        workspace=workspace,
        skills_root=skills_root,
        extra_skill_sources=extra_skill_sources,
        skill_mode=skill_mode,
        skill_policy=skill_policy,
    )
    config = build_config(
        base_config=base_config,
        workspace=workspace,
        allowed_skills=allowed_skills,
        skills_root=skills_root,
        skill_mode=skill_mode,
        timezone=timezone,
        max_tool_iterations=max_tool_iterations,
        sandbox=sandbox,
    )
    write_json(config_path, config)

    prompts_dir = run_root / "prompts"
    preloaded_skill_context = build_preloaded_skill_context(
        workspace=workspace,
        allowed_skills=allowed_skills,
        skill_mode=skill_mode,
        skill_policy=skill_policy,
    )
    skill_description_text = build_skill_description_text(workspace, allowed_skills)
    for turn in task.get("turns", []):
        if isinstance(turn, dict):
            prompt = build_turn_prompt(
                task=task,
                turn=turn,
                skill_mode=skill_mode,
                allowed_skills=allowed_skills,
                skill_policy=skill_policy,
                skill_description_text=skill_description_text,
                preloaded_skill_context=preloaded_skill_context,
                required_skills=required_skills,
                required_read_skills=(
                    task_declared_skills
                    if skill_experiment_mode == "required"
                    else required_skills
                ),
                skill_experiment_mode=skill_experiment_mode,
            )
            write_text(prompts_dir / f"turn_{int(turn.get('idx', 0)):02d}.txt", prompt)

    manifest = {
        "task_id": task_id,
        "skill_mode": skill_mode,
        "skill_policy": skill_policy if allowed_skills else "off",
        "skill_experiment_mode": skill_experiment_mode if allowed_skills else "off",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(),
        "repo_root": str(REPO_ROOT),
        "data_root": str(data_root),
        "asset_mode": asset_mode,
        "sandbox": sandbox,
        "skills_root": str(skills_root),
        "extra_skill_paths": [str(path) for path in extra_skill_paths],
        "extra_skill_scope": extra_skill_scope,
        "run_root": str(run_root),
        "workspace": str(workspace),
        "config": str(config_path),
        "allowed_skills": allowed_skills,
        "available_skills": allowed_skills,
        "required_skills": required_skills,
        "required_read_skills": (
            task_declared_skills
            if skill_experiment_mode == "required"
            else required_skills
        ),
        "task_declared_skills": task_declared_skills,
        "excluded_skills": sorted(set(excluded_skills or [])),
        "skill_ablation_view": skill_view,
        "helper_skills": helper_skills,
        "copied_assets": assets,
        "copied_skills": skills,
    }
    write_json(run_root / "manifest.json", manifest)
    assert_allowed_skills(workspace, allowed_skills, skill_mode)
    return manifest


async def run_turns_direct_async(
    *,
    manifest: dict[str, Any],
    task: dict[str, Any],
    keep_going: bool,
    continue_turns_on_error: bool,
    turn_timeout_seconds: int,
) -> int:
    """Execute turns in-process and capture clean assistant content."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.loader import load_config, resolve_config_env_vars, set_config_path
    from nanobot.cron.service import CronService
    from nanobot.utils.helpers import sync_workspace_templates

    run_root = Path(manifest["run_root"])
    config_path = Path(manifest["config"])
    workspace = Path(manifest["workspace"])
    task_id = str(task["task_id"])
    session_id = f"bench:{task_id}:{manifest.get('skill_mode')}:{manifest.get('run_id')}"
    responses_path = run_root / "responses.jsonl"
    records: list[dict[str, Any]] = []
    exit_code = 0

    if responses_path.exists():
        responses_path.unlink()

    set_config_path(config_path)
    config = resolve_config_env_vars(load_config(config_path))
    sync_workspace_templates(config.workspace_path, silent=True)
    bus = MessageBus()
    cron = CronService(config.workspace_path / "cron" / "jobs.json")
    agent_loop = AgentLoop.from_config(config, bus, cron_service=cron)
    pending_system_prompt_path: Path | None = None
    original_build_messages = agent_loop.context.build_messages

    def capture_build_messages(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        messages = original_build_messages(*args, **kwargs)
        if pending_system_prompt_path and messages:
            first = messages[0]
            if first.get("role") == "system":
                write_text(pending_system_prompt_path, str(first.get("content", "")))
        return messages

    agent_loop.context.build_messages = capture_build_messages  # type: ignore[method-assign]

    try:
        for turn in task.get("turns", []):
            if not isinstance(turn, dict):
                continue
            idx = int(turn.get("idx", 0))
            prompt_path = run_root / "prompts" / f"turn_{idx:02d}.txt"
            prompt = prompt_path.read_text(encoding="utf-8")
            response_path = run_root / "outputs" / f"turn_{idx:02d}.response.md"
            error_path = run_root / "outputs" / f"turn_{idx:02d}.error.txt"

            record: dict[str, Any] = {
                "idx": idx,
                "prompt_path": str(prompt_path),
                "response_path": str(response_path),
                "returncode": 0,
                "content": "",
            }
            turn_started = time.perf_counter()
            turn_usage: dict[str, int] = {}

            def accumulate_last_usage() -> None:
                raw = getattr(agent_loop, "_last_usage", None) or {}
                for key, value in raw.items():
                    if isinstance(value, (int, float)):
                        turn_usage[key] = turn_usage.get(key, 0) + int(value)

            system_prompt_path = write_system_prompt_snapshot(
                run_root=run_root,
                idx=idx,
                system_prompt=agent_loop.context.build_system_prompt(channel="bench"),
            )
            record["system_prompt_path"] = str(system_prompt_path)
            try:
                pending_system_prompt_path = system_prompt_path
                response = await asyncio.wait_for(
                    agent_loop.process_direct(
                        content=prompt,
                        session_key=session_id,
                        channel="bench",
                        chat_id=task_id,
                    ),
                    timeout=turn_timeout_seconds,
                )
                accumulate_last_usage()
                pending_system_prompt_path = None
                content = response.content if response else ""
                pre_repair_error = detect_agent_error(content)
                infrastructure_code = detect_infrastructure_error(content)
                issue = final_answer_issue(content, task)
                if issue and not pre_repair_error and not infrastructure_code:
                    original_path = run_root / "outputs" / f"turn_{idx:02d}.original.md"
                    repair_prompt_path = run_root / "prompts" / f"turn_{idx:02d}.repair.txt"
                    repair_response_path = run_root / "outputs" / f"turn_{idx:02d}.repair.response.md"
                    repair_prompt = build_final_answer_repair_prompt(task, issue)
                    write_text(original_path, content)
                    write_text(repair_prompt_path, repair_prompt)
                    record.update({
                        "final_answer_repair_attempted": True,
                        "final_answer_repair_issue": issue,
                        "original_response_path": str(original_path),
                        "repair_prompt_path": str(repair_prompt_path),
                        "repair_response_path": str(repair_response_path),
                    })
                    try:
                        repair_response = await asyncio.wait_for(
                            agent_loop.process_direct(
                                content=repair_prompt,
                                session_key=session_id,
                                channel="bench",
                                chat_id=task_id,
                            ),
                            timeout=min(turn_timeout_seconds, FINAL_ANSWER_REPAIR_TIMEOUT_SECONDS),
                        )
                        accumulate_last_usage()
                        repair_content = repair_response.content if repair_response else ""
                        write_text(repair_response_path, repair_content)
                        repair_issue = final_answer_issue(repair_content, task)
                        record["final_answer_repair_succeeded"] = repair_issue is None
                        record["final_answer_repair_remaining_issue"] = repair_issue
                        if repair_content.strip():
                            content = repair_content
                    except Exception as repair_exc:
                        record["final_answer_repair_succeeded"] = False
                        record["final_answer_repair_error"] = (
                            f"{type(repair_exc).__name__}: {repair_exc}"
                        )
                else:
                    record["final_answer_repair_attempted"] = False
                infrastructure_code = (
                    infrastructure_code or detect_infrastructure_error(content)
                )
                remaining_contract_issue = final_answer_issue(content, task)
                record["content"] = content
                write_text(response_path, content)
                agent_error = pre_repair_error or detect_agent_error(content)
                turn_failure = agent_error
                if not turn_failure and remaining_contract_issue:
                    turn_failure = f"final_answer_contract_error:{remaining_contract_issue}"
                    record["final_answer_contract_issue"] = remaining_contract_issue
                if turn_failure:
                    exit_code = 1
                    record["returncode"] = 1
                    record["error"] = turn_failure
                    if infrastructure_code:
                        record["failure_type"] = infrastructure_code
                    write_text(error_path, turn_failure)
                    record["error_path"] = str(error_path)
                assert_allowed_skills(
                    workspace,
                    list(manifest.get("allowed_skills", [])),
                    str(manifest["skill_mode"]),
                )
                if turn_failure and not continue_turns_on_error:
                    record["usage"] = turn_usage
                    record["duration_seconds"] = time.perf_counter() - turn_started
                    records.append(record)
                    append_jsonl(responses_path, record)
                    break
            except Exception as exc:
                exit_code = 1
                record["returncode"] = 1
                record["error"] = f"{type(exc).__name__}: {exc}"
                write_text(error_path, record["error"])
                record["error_path"] = str(error_path)
                pending_system_prompt_path = None
                if not continue_turns_on_error:
                    record["usage"] = turn_usage
                    record["duration_seconds"] = time.perf_counter() - turn_started
                    records.append(record)
                    append_jsonl(responses_path, record)
                    break

            record["usage"] = turn_usage
            record["duration_seconds"] = time.perf_counter() - turn_started
            records.append(record)
            append_jsonl(responses_path, record)
    finally:
        await agent_loop.close_mcp()
        provider = getattr(agent_loop, "provider", None)
        provider_client = getattr(provider, "_client", None)
        close_target = provider_client or provider
        close_method = (
            getattr(close_target, "aclose", None)
            or getattr(close_target, "close", None)
        )
        if callable(close_method):
            try:
                close_result = close_method()
                if inspect.isawaitable(close_result):
                    await close_result
            except Exception as exc:
                print(
                    f"[cleanup-warning] provider close failed: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
        # Let Windows proactor transports process connection_lost callbacks
        # before asyncio.run() closes the event loop.
        if os.name == "nt":
            await asyncio.sleep(0)

    write_unified_outputs(manifest=manifest, task=task, records=records)
    return exit_code


def run_turns_direct(
    *,
    manifest: dict[str, Any],
    task: dict[str, Any],
    keep_going: bool,
    continue_turns_on_error: bool,
    turn_timeout_seconds: int,
) -> int:
    return asyncio.run(
        run_turns_direct_async(
            manifest=manifest,
            task=task,
            keep_going=keep_going,
            continue_turns_on_error=continue_turns_on_error,
            turn_timeout_seconds=turn_timeout_seconds,
        )
    )


def extract_cli_response(stdout: str) -> str:
    """Extract response text from nanobot CLI output when using --backend cli."""
    marker = "nanobot"
    pos = stdout.rfind(marker)
    if pos < 0:
        return stdout.strip()
    return stdout[pos + len(marker):].strip()


def run_turns_cli(
    *,
    manifest: dict[str, Any],
    task: dict[str, Any],
    python_exe: str,
    keep_going: bool,
    continue_turns_on_error: bool,
    turn_timeout_seconds: int,
) -> int:
    run_root = Path(manifest["run_root"])
    config_path = Path(manifest["config"])
    workspace = Path(manifest["workspace"])
    task_id = str(task["task_id"])
    session_id = f"bench:{task_id}:{manifest.get('skill_mode')}:{manifest.get('run_id')}"
    responses_path = run_root / "responses.jsonl"
    records: list[dict[str, Any]] = []
    exit_code = 0

    if responses_path.exists():
        responses_path.unlink()

    for turn in task.get("turns", []):
        if not isinstance(turn, dict):
            continue
        idx = int(turn.get("idx", 0))
        prompt_path = run_root / "prompts" / f"turn_{idx:02d}.txt"
        prompt = prompt_path.read_text(encoding="utf-8")
        cmd = [
            python_exe,
            "-m",
            "nanobot",
            "agent",
            "--config",
            str(config_path),
            "--workspace",
            str(workspace),
            "--session",
            session_id,
            "--message",
            prompt,
            "--no-markdown",
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=turn_timeout_seconds,
            )
            content = extract_cli_response(result.stdout)
            returncode = result.returncode
            error_text = ""
            timed_out = False
            stdout_text = result.stdout
            stderr_text = result.stderr
        except subprocess.TimeoutExpired as exc:
            stdout_text = exc.stdout or ""
            stderr_text = exc.stderr or ""
            if isinstance(stdout_text, bytes):
                stdout_text = stdout_text.decode("utf-8", errors="replace")
            if isinstance(stderr_text, bytes):
                stderr_text = stderr_text.decode("utf-8", errors="replace")
            content = f"Error: turn timed out after {turn_timeout_seconds} seconds"
            returncode = 1
            error_text = content
            timed_out = True

        stdout_path = run_root / "outputs" / f"turn_{idx:02d}.stdout.txt"
        stderr_path = run_root / "outputs" / f"turn_{idx:02d}.stderr.txt"
        response_path = run_root / "outputs" / f"turn_{idx:02d}.response.md"
        repair_record: dict[str, Any] = {"final_answer_repair_attempted": False}
        pre_repair_error = detect_agent_error(content)
        infrastructure_code = detect_infrastructure_error(error_text or content)
        issue = final_answer_issue(content, task)
        if issue and not timed_out and not pre_repair_error and not infrastructure_code:
            original_path = run_root / "outputs" / f"turn_{idx:02d}.original.md"
            repair_prompt_path = run_root / "prompts" / f"turn_{idx:02d}.repair.txt"
            repair_stdout_path = run_root / "outputs" / f"turn_{idx:02d}.repair.stdout.txt"
            repair_stderr_path = run_root / "outputs" / f"turn_{idx:02d}.repair.stderr.txt"
            repair_response_path = run_root / "outputs" / f"turn_{idx:02d}.repair.response.md"
            repair_prompt = build_final_answer_repair_prompt(task, issue)
            write_text(original_path, content)
            write_text(repair_prompt_path, repair_prompt)
            repair_record.update({
                "final_answer_repair_attempted": True,
                "final_answer_repair_issue": issue,
                "original_response_path": str(original_path),
                "repair_prompt_path": str(repair_prompt_path),
                "repair_stdout_path": str(repair_stdout_path),
                "repair_stderr_path": str(repair_stderr_path),
                "repair_response_path": str(repair_response_path),
            })
            repair_cmd = list(cmd)
            repair_cmd[-1] = repair_prompt
            try:
                repair_result = subprocess.run(
                    repair_cmd,
                    cwd=REPO_ROOT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=min(turn_timeout_seconds, FINAL_ANSWER_REPAIR_TIMEOUT_SECONDS),
                )
                repair_content = extract_cli_response(repair_result.stdout)
                write_text(repair_stdout_path, repair_result.stdout)
                write_text(repair_stderr_path, repair_result.stderr)
                write_text(repair_response_path, repair_content)
                repair_issue = final_answer_issue(repair_content, task)
                repair_record["final_answer_repair_succeeded"] = (
                    repair_result.returncode == 0 and repair_issue is None
                )
                repair_record["final_answer_repair_remaining_issue"] = repair_issue
                repair_record["final_answer_repair_returncode"] = repair_result.returncode
                if repair_content.strip():
                    content = repair_content
                    returncode = repair_result.returncode
                    error_text = ""
            except subprocess.TimeoutExpired:
                repair_record["final_answer_repair_succeeded"] = False
                repair_record["final_answer_repair_error"] = (
                    f"repair timed out after {min(turn_timeout_seconds, FINAL_ANSWER_REPAIR_TIMEOUT_SECONDS)} seconds"
                )
        write_text(stdout_path, stdout_text)
        write_text(stderr_path, stderr_text)
        write_text(response_path, content)

        record = {
            "idx": idx,
            "returncode": returncode,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "response_path": str(response_path),
            "content": content,
        }
        record.update(repair_record)
        if timed_out:
            record["error"] = error_text
        infrastructure_code = infrastructure_code or detect_infrastructure_error(content)
        agent_error = pre_repair_error or detect_agent_error(content)
        remaining_contract_issue = final_answer_issue(content, task)
        turn_failure = agent_error
        if not turn_failure and remaining_contract_issue:
            turn_failure = f"final_answer_contract_error:{remaining_contract_issue}"
            record["final_answer_contract_issue"] = remaining_contract_issue
        if turn_failure and record["returncode"] == 0:
            record["returncode"] = 1
            record["error"] = turn_failure
            exit_code = 1
        if infrastructure_code:
            record["failure_type"] = infrastructure_code
        records.append(record)
        append_jsonl(responses_path, record)

        try:
            assert_allowed_skills(
                workspace,
                list(manifest.get("allowed_skills", [])),
                str(manifest["skill_mode"]),
            )
        except RuntimeError:
            exit_code = 2
            if not keep_going:
                raise

        if record["returncode"] != 0:
            exit_code = int(record["returncode"])
            if not continue_turns_on_error:
                break

    write_unified_outputs(manifest=manifest, task=task, records=records)
    return exit_code


def run_turns(
    *,
    manifest: dict[str, Any],
    task: dict[str, Any],
    python_exe: str,
    keep_going: bool,
    continue_turns_on_error: bool,
    backend: str,
    turn_timeout_seconds: int,
) -> int:
    if backend == "direct":
        return run_turns_direct(
            manifest=manifest,
            task=task,
            keep_going=keep_going,
            continue_turns_on_error=continue_turns_on_error,
            turn_timeout_seconds=turn_timeout_seconds,
        )
    return run_turns_cli(
        manifest=manifest,
        task=task,
        python_exe=python_exe,
        keep_going=keep_going,
        continue_turns_on_error=continue_turns_on_error,
        turn_timeout_seconds=turn_timeout_seconds,
    )


def execute_prepared_run(
    *,
    task: dict[str, Any],
    manifest: dict[str, Any],
    python_exe: str,
    keep_going: bool,
    continue_turns_on_error: bool,
    backend: str,
    turn_timeout_seconds: int,
) -> int:
    print(f"[execute] {manifest['task_id']} {manifest['skill_mode']}: {manifest['run_root']}", flush=True)
    code = run_turns(
        manifest=manifest,
        task=task,
        python_exe=python_exe,
        keep_going=keep_going,
        continue_turns_on_error=continue_turns_on_error,
        backend=backend,
        turn_timeout_seconds=turn_timeout_seconds,
    )
    print(f"[done] {manifest['task_id']} {manifest['skill_mode']}: exit={code}", flush=True)
    return code


def execute_prepared_run_subprocess(
    *,
    manifest: dict[str, Any],
    task_json: Path,
    python_exe: str,
    keep_going: bool,
    continue_turns_on_error: bool,
    backend: str,
    turn_timeout_seconds: int,
) -> int:
    print(f"[execute] {manifest['task_id']} {manifest['skill_mode']}: {manifest['run_root']}", flush=True)
    cmd = [
        python_exe,
        str(Path(__file__).resolve()),
        "--task-json",
        str(task_json),
        "--execute-manifest",
        str(Path(manifest["run_root"]) / "manifest.json"),
        "--backend",
        backend,
        "--turn-timeout",
        str(turn_timeout_seconds),
    ]
    if keep_going:
        cmd.append("--keep-going")
    if continue_turns_on_error:
        cmd.append("--continue-turns-on-error")
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(f"[done] {manifest['task_id']} {manifest['skill_mode']}: exit={result.returncode}", flush=True)
    return int(result.returncode)


def repeated_run_id(base_run_id: str, repeat_index: int, repeat_count: int) -> str:
    if repeat_count <= 1:
        return base_run_id
    width = max(2, len(str(repeat_count)))
    return f"{base_run_id}_rep{repeat_index:0{width}d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and optionally execute isolated nanobot dataset tasks.",
    )
    parser.add_argument("--task-json", default=str(DEFAULT_TASK_JSON))
    parser.add_argument(
        "--task-id",
        action="append",
        default=None,
        help="Task id to run. Can be repeated or comma-separated. Defaults to the first task for compatibility.",
    )
    parser.add_argument("--all-tasks", action="store_true", help="Run every task in task.json.")
    parser.add_argument("--list-tasks", action="store_true", help="List task ids and exit.")
    parser.add_argument("--skill-mode", choices=["on", "off", "both"], default="both")
    parser.add_argument(
        "--skill-experiment-mode",
        choices=["correct", "all", "required"],
        default="correct",
        help=(
            "Skill exposure for skill_on runs: correct exposes only task-declared skills; "
            "all exposes every tableagent-* dataset skill; required exposes task-declared skills "
            "and instructs the agent to read all required SKILL.md files before answering."
        ),
    )
    parser.add_argument(
        "--skill-policy",
        choices=["available", "required-read", "force-use", "preload"],
        default="available",
        help=(
            "How skill_on exposes task skills: available only lists them, "
            "required-read asks the model to read SKILL.md, force-use requires using it, "
            "preload injects SKILL.md into prompts."
        ),
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help=(
            "Repeat each selected task/skill-mode this many times. "
            "When greater than 1, run ids become <run-id>_rep01, <run-id>_rep02, ..."
        ),
    )
    parser.add_argument("--base-config", default=None)
    parser.add_argument(
        "--data-root",
        default=str(REPO_ROOT / "datasets"),
        help="Root used to resolve each data_assets[].path. Defaults to repo datasets/.",
    )
    parser.add_argument(
        "--asset-mode",
        choices=["copy", "hardlink"],
        default="copy",
        help=(
            "How task assets are staged in each workspace. copy preserves legacy behavior; "
            "hardlink stores no duplicate data blocks and requires data_root and runs/ "
            "to be on the same filesystem."
        ),
    )
    parser.add_argument(
        "--sandbox",
        choices=["none", "bwrap"],
        default="none",
        help=(
            "OS-level sandbox for agent shell commands. Formal benchmark runs should "
            "use bwrap; execution fails closed when the requested backend is unavailable."
        ),
    )
    parser.add_argument(
        "--skills-root",
        default=str(REPO_ROOT / "datasets" / "skills"),
        help="Root used to resolve task skill directories. Defaults to repo datasets/skills/.",
    )
    parser.add_argument(
        "--exclude-skill",
        action="append",
        default=None,
        help=(
            "Skill name to remove from the visible, required-read, and structured-execution "
            "sets for this run. Can be repeated or comma-separated."
        ),
    )
    parser.add_argument(
        "--skill-view",
        default="full",
        help="Audit label for the Skill content view used by this run.",
    )
    parser.add_argument(
        "--extra-skill-path",
        action="append",
        default=None,
        help=(
            "Additional skill directory with SKILL.md to append to skill_on runs. "
            "Can be repeated. Useful for optional helper skills such as table-access."
        ),
    )
    parser.add_argument(
        "--extra-skill-scope",
        choices=["on", "both"],
        default="on",
        help=(
            "Scope for --extra-skill-path. Default 'on' keeps previous behavior; "
            "'both' adds these helper skills to skill_on and skill_off runs."
        ),
    )
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--execute-manifest", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of independent task runs to execute in parallel. Turns inside one run remain sequential.",
    )
    parser.add_argument(
        "--submission-delay",
        type=float,
        default=0.0,
        help=(
            "Minimum seconds between starting independent task workers. "
            "Use a positive value to avoid provider burst-rate limits."
        ),
    )
    parser.add_argument(
        "--file-reader-skill",
        action="store_true",
        help=(
            "Add the optional benchmark-file-reader helper skill to skill_on runs. "
            "Default is off so original skill_on/skill_off comparisons are unchanged."
        ),
    )
    parser.add_argument(
        "--continue-turns-on-error",
        action="store_true",
        help="Continue later turns inside the same task after a failed turn. Not recommended for dependent multi-turn benchmarks.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help=(
            "Resume an existing run id: skip completed runs, reuse prepared runs, "
            "and rebuild only runs that started but did not produce task_result.json."
        ),
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--turn-timeout",
        type=int,
        default=600,
        help="Maximum seconds to wait for each task turn before marking it failed.",
    )
    parser.add_argument(
        "--max-tool-iterations",
        type=int,
        default=25,
        help="Maximum agent tool/LLM loop iterations per turn. Use 0 to keep the base config value.",
    )
    parser.add_argument(
        "--backend",
        choices=["direct", "cli"],
        default="direct",
        help="Execution backend. direct captures clean response.content; cli captures terminal output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.overwrite and args.resume_existing:
        raise ValueError("--overwrite and --resume-existing cannot be used together.")
    if args.execute and args.sandbox == "bwrap":
        if os.name == "nt":
            raise RuntimeError("The bwrap sandbox is not supported on Windows.")
        if shutil.which("bwrap") is None:
            raise RuntimeError(
                "The formal benchmark requires Bubblewrap, but 'bwrap' was not found. "
                "Install Bubblewrap or prepare without --execute; do not run Gold-sensitive "
                "evaluation unsandboxed."
            )
    task_json = Path(args.task_json).expanduser().resolve()
    if args.execute_manifest:
        manifest = load_json(Path(args.execute_manifest).expanduser().resolve())
        tasks_by_id = {str(task.get("task_id")): task for task in load_tasks(task_json)}
        task = tasks_by_id.get(str(manifest.get("task_id")))
        if task is None:
            raise ValueError(f"Task id from manifest is not present in task.json: {manifest.get('task_id')}")
        return run_turns(
            manifest=manifest,
            task=task,
            python_exe=args.python,
            keep_going=args.keep_going,
            continue_turns_on_error=args.continue_turns_on_error,
            backend=args.backend,
            turn_timeout_seconds=args.turn_timeout,
        )

    task_ids = split_task_ids(args.task_id)
    if args.list_tasks:
        for task in load_tasks(task_json):
            print(task.get("task_id", ""))
        return 0
    repeat_count = max(1, int(args.repeat))
    tasks = select_tasks(task_json=task_json, task_ids=task_ids, all_tasks=args.all_tasks)
    run_id = args.run_id or timestamp_run_id()

    base_config_path = (
        Path(args.base_config).expanduser().resolve()
        if args.base_config
        else default_base_config_path()
    )
    base_config = load_base_config(base_config_path)
    max_tool_iterations = args.max_tool_iterations if args.max_tool_iterations > 0 else None
    data_root = Path(args.data_root).expanduser().resolve()
    skills_root = Path(args.skills_root).expanduser().resolve()
    excluded_skills = split_task_ids(args.exclude_skill)
    extra_skill_paths = [
        Path(value).expanduser().resolve()
        for value in (args.extra_skill_path or [])
    ]
    if not data_root.is_dir():
        raise FileNotFoundError(f"Data root not found: {data_root}")
    if not skills_root.is_dir():
        raise FileNotFoundError(f"Skills root not found: {skills_root}")
    for skill_path in extra_skill_paths:
        if not (skill_path / "SKILL.md").is_file():
            raise FileNotFoundError(f"Extra skill must be a directory containing SKILL.md: {skill_path}")

    modes = ["on", "off"] if args.skill_mode == "both" else [args.skill_mode]
    runs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for repeat_index in range(1, repeat_count + 1):
        current_run_id = repeated_run_id(run_id, repeat_index, repeat_count)
        for task in tasks:
            for mode in modes:
                run_root = (
                    RUNS_ROOT
                    / safe_name(str(task["task_id"]))
                    / f"skill_{mode}"
                    / safe_name(current_run_id)
                )
                manifest_path = run_root / "manifest.json"
                result_path = run_root / "task_result.json"
                resume_overwrite = False
                if args.resume_existing and run_root.exists():
                    if result_path.is_file():
                        existing_result = load_json(result_path)
                        if existing_result.get("status") == "completed":
                            existing_issue = final_answer_issue(
                                str(existing_result.get("final_output") or ""),
                                task,
                            )
                            if existing_issue is None:
                                print(f"[resume-skip] {task.get('task_id')} {mode}: completed result exists")
                                continue
                            print(
                                f"[resume-reset] {task.get('task_id')} {mode}: "
                                f"completed result violates answer contract ({existing_issue})"
                            )
                        resume_overwrite = True
                        print(f"[resume-reset] {task.get('task_id')} {mode}: failed result will be rebuilt")
                    session_dir = run_root / "workspace" / "sessions"
                    started = (run_root / "responses.jsonl").exists() or (
                        session_dir.is_dir() and any(session_dir.glob("*.jsonl"))
                    )
                    if manifest_path.is_file() and not started and not resume_overwrite:
                        manifest = load_json(manifest_path)
                        existing_asset_mode = str(manifest.get("asset_mode", "copy"))
                        if existing_asset_mode == args.asset_mode:
                            runs.append((task, manifest))
                            print(f"[resume-ready] {task.get('task_id')} {mode}: {run_root}")
                            continue
                        resume_overwrite = True
                        print(
                            f"[resume-reset] {task.get('task_id')} {mode}: "
                            f"asset mode changed from {existing_asset_mode} to {args.asset_mode}"
                        )
                    resume_overwrite = True
                    print(f"[resume-reset] {task.get('task_id')} {mode}: incomplete run will be rebuilt")
                manifest = prepare_run(
                    task=task,
                    skill_mode=mode,
                    skill_policy=args.skill_policy,
                    skill_experiment_mode=args.skill_experiment_mode,
                    run_id=current_run_id,
                    base_config=base_config,
                    timezone=args.timezone,
                    max_tool_iterations=max_tool_iterations,
                    data_root=data_root,
                    asset_mode=args.asset_mode,
                    skills_root=skills_root,
                    extra_skill_paths=extra_skill_paths,
                    extra_skill_scope=args.extra_skill_scope,
                    file_reader_skill=args.file_reader_skill,
                    excluded_skills=excluded_skills,
                    skill_view=str(args.skill_view),
                    sandbox=args.sandbox,
                    overwrite=args.overwrite or resume_overwrite,
                )
                manifest["base_run_id"] = run_id
                manifest["repeat_index"] = repeat_index
                manifest["repeat_count"] = repeat_count
                write_json(Path(manifest["run_root"]) / "manifest.json", manifest)
                runs.append((task, manifest))
                repeat_label = f" repeat={repeat_index}/{repeat_count}" if repeat_count > 1 else ""
                print(f"[prepared] {task.get('task_id')} {mode}/{manifest.get('skill_experiment_mode')}{repeat_label}: {manifest['run_root']}")

    if not args.execute:
        print(f"Prepared {len(runs)} run(s). Re-run with --execute to call nanobot.")
        return 0

    final_code = 0
    concurrency = max(1, int(args.concurrency))
    submission_delay = max(0.0, float(args.submission_delay))
    if concurrency == 1:
        for task, manifest in runs:
            code = execute_prepared_run(
                task=task,
                manifest=manifest,
                python_exe=args.python,
                keep_going=args.keep_going,
                continue_turns_on_error=args.continue_turns_on_error,
                backend=args.backend,
                turn_timeout_seconds=args.turn_timeout,
            )
            final_code = final_code or code
            if code != 0 and not args.keep_going:
                print("Stopped after run error. Re-run with --keep-going to continue later runs after failures.")
                break
        return final_code

    print(f"[parallel] executing up to {concurrency} independent run(s) at a time", flush=True)
    run_iter = iter(runs)
    active: dict[Any, tuple[dict[str, Any], dict[str, Any]]] = {}
    next_submission_at = 0.0
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        def submit_next() -> bool:
            nonlocal next_submission_at
            try:
                task, manifest = next(run_iter)
            except StopIteration:
                return False
            if submission_delay:
                wait_seconds = next_submission_at - time.monotonic()
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
            future = executor.submit(
                execute_prepared_run_subprocess,
                manifest=manifest,
                task_json=task_json,
                python_exe=args.python,
                keep_going=args.keep_going,
                continue_turns_on_error=args.continue_turns_on_error,
                backend=args.backend,
                turn_timeout_seconds=args.turn_timeout,
            )
            active[future] = (task, manifest)
            next_submission_at = time.monotonic() + submission_delay
            return True

        for _ in range(concurrency):
            if not submit_next():
                break

        while active:
            done, _ = wait(active.keys(), return_when=FIRST_COMPLETED)
            for future in done:
                task, manifest = active.pop(future)
                try:
                    code = int(future.result())
                except Exception as exc:
                    code = 1
                    print(
                        f"[done] {manifest['task_id']} {manifest['skill_mode']}: "
                        f"exit=1 ({type(exc).__name__}: {exc})",
                        flush=True,
                    )
                final_code = final_code or code
                if code != 0 and not args.keep_going:
                    for pending in active:
                        pending.cancel()
                    print("Stopped after run error. Re-run with --keep-going to continue later runs after failures.")
                    return final_code
                submit_next()
    return final_code


if __name__ == "__main__":
    raise SystemExit(main())
