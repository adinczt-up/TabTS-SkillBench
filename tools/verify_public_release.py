#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[error] {message}")


def task_ids(rows: list[dict[str, Any]], label: str) -> list[str]:
    values = [str(row.get("task_id") or "") for row in rows]
    require(all(values), f"{label} contains a missing task_id")
    require(len(values) == len(set(values)), f"{label} contains duplicate task_ids")
    return values


def nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            child
            for item in value.values()
            for child in nested_keys(item)
        }
    if isinstance(value, list):
        return {child for item in value for child in nested_keys(item)}
    return set()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    root = args.root.resolve()

    evaluator = load(root / "benchmark/evaluator/tasks_eval_251.json")
    public = load_jsonl(root / "benchmark/tasks/tasks_public_251.jsonl")
    contracts = load_jsonl(root / "benchmark/evaluator/contracts_251.jsonl")
    gold = load_jsonl(root / "benchmark/evaluator/gold_251.jsonl")
    task_set = load(root / "benchmark/manifests/task_set_251.json")

    collections = {
        "evaluator tasks": task_ids(evaluator, "evaluator tasks"),
        "public tasks": task_ids(public, "public tasks"),
        "contracts": task_ids(contracts, "contracts"),
        "gold": task_ids(gold, "gold"),
        "task-set manifest": [str(value) for value in task_set.get("task_ids", [])],
    }
    expected_ids = set(collections["evaluator tasks"])
    require(len(expected_ids) == 251, f"expected 251 evaluator tasks, found {len(expected_ids)}")
    require(task_set.get("task_set") == "TabTS-SkillBench-251", "unexpected task-set name")
    require(task_set.get("task_count") == 251, "task-set manifest count must be 251")
    for label, values in collections.items():
        require(
            set(values) == expected_ids and len(values) == len(expected_ids),
            f"{label} task_ids do not exactly match evaluator tasks",
        )

    forbidden_public_keys = {
        "metadata",
        "skills",
        "supporting_skills",
        "required_execution_skills",
        "gold_rows",
        "oracle_sql",
        "oracle_sql_template",
    }
    for row in public:
        exposed = forbidden_public_keys.intersection(nested_keys(row))
        require(not exposed, f"public task {row['task_id']} exposes {sorted(exposed)}")

    forbidden_evaluator_metadata = {
        "profile_variant",
        "full_gold_verified",
        "semantic_duplicate_check",
        "question_review_status",
        "oracle_validation_status",
        "oracle_validation_report",
        "multi_table_verified",
        "required_skill_count",
        "required_execution_skills",
    }
    for row in evaluator:
        metadata = row.get("metadata") or {}
        exposed = forbidden_evaluator_metadata.intersection(metadata)
        require(
            not exposed,
            f"evaluator task {row['task_id']} exposes internal metadata {sorted(exposed)}",
        )
        require(
            "supporting_skills" not in row,
            f"evaluator task {row['task_id']} exposes supporting Skill annotations",
        )

    forbidden_contract_keys = {"profile_variant", "supporting_skills"}
    for row in contracts:
        exposed = forbidden_contract_keys.intersection(row)
        require(
            not exposed,
            f"contract {row['task_id']} exposes internal metadata {sorted(exposed)}",
        )

    forbidden_gold_keys = {
        "full_gold_verified",
        "semantic_duplicate_check",
        "question_review_status",
        "oracle_validation_status",
        "oracle_validation_report",
    }
    for row in gold:
        exposed = forbidden_gold_keys.intersection(row)
        require(
            not exposed,
            f"Gold record {row['task_id']} exposes internal QA metadata {sorted(exposed)}",
        )

    skill_dirs = sorted(
        path
        for path in (root / "skills").iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )
    require(len(skill_dirs) == 47, f"expected 47 skill modules, found {len(skill_dirs)}")
    with (root / "skills/skill_catalog.csv").open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        catalog = list(reader)
        require(
            reader.fieldnames == ["name", "description", "has_scripts", "has_validator"],
            "skill_catalog.csv must contain release-facing inventory fields only",
        )
    require(
        {row["name"] for row in catalog} == {path.name for path in skill_dirs},
        "skill_catalog.csv does not exactly match the skill directories",
    )

    asset_manifest = load(root / "benchmark/manifests/assets_sha256.json")
    require(isinstance(asset_manifest, list), "asset manifest must be a JSON array")
    manifest_by_path = {str(row.get("path")): row for row in asset_manifest}
    require(len(manifest_by_path) == len(asset_manifest), "asset manifest has duplicate paths")
    for task in public:
        for asset in task.get("data_assets", []):
            path = str(asset.get("path") or "")
            require(path in manifest_by_path, f"task asset is absent from manifest: {path}")
            require(
                asset.get("sha256") == manifest_by_path[path].get("sha256"),
                f"task/manifest SHA-256 mismatch: {path}",
            )

    data_sources = yaml.safe_load(
        (root / "data_sources.yaml").read_text(encoding="utf-8")
    )
    source_records = (data_sources or {}).get("datasets") or {}
    expected_sources = {"azure-pdm", "bdg2", "rel-event", "rel-f1", "rel-hm", "rel-stack"}
    require(
        set(source_records) == expected_sources,
        "data_sources.yaml does not exactly cover benchmark sources",
    )
    for name, record in source_records.items():
        for field in (
            "upstream_url",
            "upstream_version",
            "upstream_commit",
            "upstream_license",
            "license_evidence_url",
            "acquisition_mode",
            "requires_user_acceptance",
            "automatic_download",
            "redistribution_status",
            "required_attribution",
            "transformation_script",
            "output_manifest",
            "source_layout",
            "user_instructions",
        ):
            require(field in record, f"data source {name} is missing {field}")
        require(
            bool((record.get("source_layout") or {}).get("required_globs"))
            or bool((record.get("source_layout") or {}).get("required_paths")),
            f"data source {name} has no machine-checkable source layout",
        )
        require(
            bool(record.get("user_instructions")),
            f"data source {name} has no acquisition instructions",
        )
        if record.get("requires_user_acceptance"):
            require(
                record.get("acquisition_mode") == "user_download_required",
                f"data source {name} must use user_download_required acquisition",
            )
            require(
                record.get("automatic_download") is False,
                f"data source {name} must not be downloaded automatically",
            )
            require(
                bool(record.get("terms_url")),
                f"data source {name} requires a terms URL",
            )

    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project_meta = project.get("project") or {}
    require(
        project_meta.get("name") == "tabts-skillbench",
        "pyproject project name must be tabts-skillbench",
    )
    citation = yaml.safe_load(
        (root / "CITATION.cff").read_text(encoding="utf-8-sig")
    )
    require(
        str(citation.get("version")) == str(project_meta.get("version")),
        "CITATION.cff and pyproject versions differ",
    )
    for path in (
        "BENCHMARK_CARD.md",
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "NOTICE",
        "EVALUATION_PROTOCOL.md",
        "SECURITY.md",
        "docs/FRAMEWORK_ADAPTER.md",
    ):
        require((root / path).is_file(), f"required release document is missing: {path}")

    chunks = []
    for path in root.rglob("*"):
        ignored_parts = {
            ".git",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "build",
            "dist",
            "experiments",
            "runs",
            "sources",
            "standardized",
        }
        if (
            path.is_file()
            and path.name not in {"verify_public_release.py", "verify_paper_results.py"}
            and path.name != ".DS_Store"
            and path.stat().st_size < 20_000_000
            and not ignored_parts.intersection(path.parts)
            and path.suffix not in {".pyc", ".pyo"}
        ):
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    text = "\n".join(chunks)
    secret_patterns = {
        "OpenAI-style key": r"\bsk-[A-Za-z0-9_-]{16,}\b",
        "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
        "Google API key": r"\bAIza[0-9A-Za-z_-]{30,}\b",
        "GitHub token": r"\bgh[oprsu]_[A-Za-z0-9]{20,}\b",
        "Slack token": r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",
    }
    for label, pattern in secret_patterns.items():
        require(not re.search(pattern, text), f"possible {label}")
    machine_path_patterns = (
        r"/Users/[^/\s]+/",
        r"/home/(?!user/)[^/\s]+/",
        r"[A-Za-z]:\\Users\\[^\\\s]+\\",
    )
    require(
        not any(re.search(pattern, text) for pattern in machine_path_patterns),
        "machine-specific user path found",
    )
    gitignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    for ignored_data_path in ("data/sources/", "data/skillmtts/standardized/"):
        require(
            ignored_data_path in gitignore,
            f".gitignore must exclude user-provided data: {ignored_data_path}",
        )

    print(
        f"[ok] tasks={len(expected_ids)} public={len(public)} "
        f"contracts={len(contracts)} gold={len(gold)} "
        f"skills={len(skill_dirs)} assets={len(asset_manifest)}"
    )


if __name__ == "__main__":
    main()
