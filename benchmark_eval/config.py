from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from benchmark_eval.utils import expand_env, load_json, safe_name, stable_hash, write_json


@dataclass(frozen=True)
class ProjectPaths:
    repo_root: Path
    experiment_root: Path
    task_json: Path
    runner_task_json: Path
    skills_root: Path
    data_root: Path
    runs_root: Path


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML object: {path}")
    return expand_env(data)


def resolve_path(repo_root: Path, value: str | Path) -> Path:
    path = Path(os.path.expanduser(str(value)))
    return path if path.is_absolute() else repo_root / path


def load_experiment(experiment_path: Path, repo_root: Path) -> tuple[dict[str, Any], ProjectPaths]:
    config = load_yaml(experiment_path)
    experiment_id = safe_name(str(config.get("experiment_id") or experiment_path.stem))
    experiment_root = resolve_path(
        repo_root,
        config.get("output_root", f"experiments/{experiment_id}"),
    )
    paths = ProjectPaths(
        repo_root=repo_root,
        experiment_root=experiment_root,
        task_json=resolve_path(repo_root, config["task_json"]),
        runner_task_json=experiment_root / "runner" / "tasks_runner.json",
        skills_root=resolve_path(repo_root, config.get("skills_root", "datasets/skills")),
        data_root=resolve_path(repo_root, config.get("data_root", "datasets")),
        runs_root=resolve_path(repo_root, config.get("runs_root", "runs")),
    )
    config["experiment_id"] = experiment_id
    return config, paths


def write_runner_tasks(paths: ProjectPaths) -> Path:
    """Write the minimum task view needed by an agent runner.

    Evaluator-only metadata, including Gold and Oracle fields, must never be
    handed to framework wrappers or mounted into an agent workspace.
    """
    tasks = load_json(paths.task_json)
    runner_tasks = []
    top_level_fields = (
        "task_id",
        "minimal_prompt",
        "instruction",
        "data_assets",
        "turns",
        "options",
        "skills",
        "supporting_skills",
        "required_execution_skills",
    )
    metadata_fields = ("answer_contract", "output_fields", "options")
    for task in tasks:
        runner_task = {
            field: copy.deepcopy(task[field])
            for field in top_level_fields
            if field in task
        }
        metadata = task.get("metadata")
        if isinstance(metadata, dict):
            safe_metadata = {
                field: copy.deepcopy(metadata[field])
                for field in metadata_fields
                if field in metadata
            }
            if safe_metadata:
                runner_task["metadata"] = safe_metadata
        runner_tasks.append(runner_task)
    write_json(paths.runner_task_json, runner_tasks)
    return paths.runner_task_json


def load_models(models_path: Path) -> dict[str, dict[str, Any]]:
    data = load_yaml(models_path)
    models = data.get("models", data)
    if not isinstance(models, dict):
        raise ValueError(f"Expected models mapping: {models_path}")
    return {str(name): dict(value) for name, value in models.items()}


def selected_names(config: dict[str, Any], key: str) -> list[str]:
    value = config.get(key, [])
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [str(name) for name, enabled in value.items() if enabled is not False]
    return [str(item) for item in value]


def condition_config(config: dict[str, Any], name: str) -> dict[str, Any]:
    raw = config.get("conditions", [])
    if isinstance(raw, dict):
        value = raw.get(name, {})
        return dict(value) if isinstance(value, dict) else {}
    return {}


def make_run_id(
    experiment_id: str,
    framework: str,
    model_name: str,
    condition: str,
    repeat: int,
) -> str:
    return safe_name(
        f"{experiment_id}__{framework}__{model_name}__{condition}__r{repeat:02d}"
    )


def generated_model_config(
    *,
    repo_root: Path,
    experiment_root: Path,
    profile_name: str,
    profile: dict[str, Any],
) -> Path:
    source = resolve_path(
        repo_root,
        profile.get("base_config", "~/.nanobot/config.json"),
    )
    if not source.is_file():
        raise FileNotFoundError(f"Nanobot base config not found: {source}")
    data = load_json(source)
    defaults = data.setdefault("agents", {}).setdefault("defaults", {})
    if profile.get("model"):
        defaults["model"] = profile["model"]
    if profile.get("provider"):
        defaults["provider"] = profile["provider"]
    for source_key, target_key in (
        ("temperature", "temperature"),
        ("max_tokens", "maxTokens"),
        ("reasoning_effort", "reasoningEffort"),
        ("context_window_tokens", "contextWindowTokens"),
        ("provider_retry_mode", "providerRetryMode"),
    ):
        if source_key in profile:
            defaults[target_key] = profile[source_key]

    provider_name = profile.get("provider")
    if provider_name:
        providers = data.setdefault("providers", {})
        provider = providers.setdefault(provider_name, {})
        if profile.get("api_base"):
            provider["apiBase"] = profile["api_base"]
        if profile.get("api_key_env"):
            provider["apiKey"] = "${" + str(profile["api_key_env"]) + "}"

    output = experiment_root / "generated_configs" / f"{safe_name(profile_name)}.json"
    write_json(output, data)
    try:
        output.chmod(0o600)
    except OSError:
        pass
    return output


def write_experiment_manifest(
    *,
    config: dict[str, Any],
    paths: ProjectPaths,
    models: dict[str, dict[str, Any]],
    experiment_path: Path,
    models_path: Path,
) -> Path:
    payload = {
        "experiment_id": config["experiment_id"],
        "experiment_config": str(experiment_path.resolve()),
        "models_config": str(models_path.resolve()),
        "config_hash": stable_hash(config),
        "task_json": str(paths.task_json.resolve()),
        "runner_task_json": str(paths.runner_task_json.resolve()),
        "skills_root": str(paths.skills_root.resolve()),
        "data_root": str(paths.data_root.resolve()),
        "frameworks": selected_names(config, "frameworks"),
        "models": selected_names(config, "models"),
        "conditions": selected_names(config, "conditions"),
        "model_profiles": {
            name: {
                key: value
                for key, value in copy.deepcopy(models[name]).items()
                if key not in {"api_key", "apiKey"}
            }
            for name in selected_names(config, "models")
        },
    }
    output = paths.experiment_root / "manifest.json"
    write_json(output, payload)
    return output
