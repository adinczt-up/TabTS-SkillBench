from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from benchmark_eval.adapters import make_adapter
from benchmark_eval.config import (
    condition_config,
    generated_model_config,
    load_experiment,
    load_models,
    selected_names,
    write_experiment_manifest,
    write_runner_tasks,
)
from benchmark_eval.contracts import build_contracts
from benchmark_eval.data_cli import add_data_parser, data_command
from benchmark_eval.judge import judge_traces
from benchmark_eval.metric_audit import static_metric_applicability
from benchmark_eval.metrics import score_trace
from benchmark_eval.report import METRICS, generate_reports
from benchmark_eval.schema import RunLocator, TraceRecord
from benchmark_eval.trace import normalize_run
from benchmark_eval.utils import (
    load_json,
    read_jsonl,
    sha256_file,
    write_csv,
    write_json,
    write_jsonl,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _context(args: argparse.Namespace):
    experiment_path = Path(args.experiment).resolve()
    models_path = Path(args.models_config).resolve()
    config, paths = load_experiment(experiment_path, REPO_ROOT)
    write_runner_tasks(paths)
    runtime = config.setdefault("runtime", {})
    for argument, key in (
        ("repeats", "repeats"),
        ("concurrency", "concurrency"),
        ("batch_size", "batch_size"),
        ("submission_delay", "submission_delay_seconds"),
    ):
        value = getattr(args, argument, None)
        if value is not None:
            runtime[key] = value
    models = load_models(models_path)
    write_experiment_manifest(
        config=config,
        paths=paths,
        models=models,
        experiment_path=experiment_path,
        models_path=models_path,
    )
    return config, paths, models


def _tasks(paths) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    tasks = load_json(paths.task_json)
    return tasks, {str(task["task_id"]): task for task in tasks}


def _filtered_names(
    configured: list[str],
    override: list[str] | None,
) -> list[str]:
    if not override:
        return configured
    requested = [
        part.strip()
        for value in override
        for part in value.split(",")
        if part.strip()
    ]
    missing = sorted(set(requested) - set(configured))
    if missing:
        raise ValueError(f"Not configured: {', '.join(missing)}")
    return requested


def _matrix(args: argparse.Namespace, config, paths, models):
    tasks, _ = _tasks(paths)
    if args.task_limit:
        tasks = tasks[: args.task_limit]
    task_ids = [str(task["task_id"]) for task in tasks]
    frameworks = _filtered_names(
        selected_names(config, "frameworks"),
        args.framework,
    )
    model_names = _filtered_names(selected_names(config, "models"), args.model)
    conditions = _filtered_names(
        selected_names(config, "conditions"),
        args.condition,
    )
    default_repeats = int((config.get("runtime") or {}).get("repeats", 1))
    repeat_counts = {
        condition: int(
            args.repeats
            if args.repeats is not None
            else condition_config(config, condition).get("repeats", default_repeats)
        )
        for condition in conditions
    }
    invalid = [name for name, value in repeat_counts.items() if value < 1]
    if invalid:
        raise ValueError(
            "Condition repeat count must be positive: " + ", ".join(invalid)
        )
    return task_ids, frameworks, model_names, conditions, repeat_counts


def _model_configs(config, paths, models, model_names) -> dict[str, Path]:
    return {
        name: generated_model_config(
            repo_root=paths.repo_root,
            experiment_root=paths.experiment_root,
            profile_name=name,
            profile=models[name],
        )
        for name in model_names
    }


def validate_command(args: argparse.Namespace) -> int:
    config, paths, models = _context(args)
    tasks, _ = _tasks(paths)
    contracts, contract_report = build_contracts(
        paths.task_json,
        paths.experiment_root / "contracts",
    )
    skill_dirs = [
        path
        for path in paths.skills_root.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    ]
    inventory = []
    for path in sorted(skill_dirs):
        scripts = sorted(
            item.name
            for item in (path / "scripts").glob("*.py")
            if item.is_file()
        )
        inventory.append(
            {
                "skill": path.name,
                "script_count": len(scripts),
                "scripts": scripts,
                "skill_sha256": sha256_file(path / "SKILL.md"),
            }
        )
    report = {
        "task_count": len(tasks),
        "skill_count": len(skill_dirs),
        "contracts": contract_report,
        "models": selected_names(config, "models"),
        "frameworks": selected_names(config, "frameworks"),
        "conditions": selected_names(config, "conditions"),
        "skills": inventory,
    }
    write_json(paths.experiment_root / "validation.json", report)
    write_csv(paths.experiment_root / "contracts" / "skill_inventory.csv", inventory)
    metric_applicability = static_metric_applicability(contracts, METRICS)
    write_json(
        paths.experiment_root / "contracts" / "metric_applicability.json",
        {"metrics": metric_applicability},
    )
    write_csv(
        paths.experiment_root / "contracts" / "metric_applicability.csv",
        metric_applicability,
    )
    print(
        f"Validated tasks={len(tasks)} contracts={len(contracts)} "
        f"skills={len(skill_dirs)} issues={contract_report['issue_count']}"
    )
    return 1 if contract_report["issue_count"] else 0


def _adapter(config, paths, framework: str):
    return make_adapter(
        framework,
        repo_root=paths.repo_root,
        experiment_root=paths.experiment_root,
        task_json=paths.runner_task_json,
        data_root=paths.data_root,
        skills_root=paths.skills_root,
        runs_root=paths.runs_root,
        experiment_config=config,
    )


def run_command(args: argparse.Namespace) -> int:
    config, paths, models = _context(args)
    task_ids, frameworks, model_names, conditions, repeat_counts = _matrix(
        args,
        config,
        paths,
        models,
    )
    model_configs = _model_configs(config, paths, models, model_names)
    locators: list[RunLocator] = []
    for framework in frameworks:
        adapter = _adapter(config, paths, framework)
        for model_name in model_names:
            for condition in conditions:
                for repeat in range(1, repeat_counts[condition] + 1):
                    cc = condition_config(config, condition)
                    print(
                        f"[run] framework={framework} model={model_name} "
                        f"condition={condition} repeat={repeat} tasks={len(task_ids)}",
                        flush=True,
                    )
                    if args.dry_run:
                        current = adapter.locate(
                            model_name=model_name,
                            condition=condition,
                            condition_config=cc,
                            repeat=repeat,
                            task_ids=task_ids,
                        )
                    else:
                        current = adapter.execute(
                            model_name=model_name,
                            model_profile=models[model_name],
                            model_config_path=model_configs[model_name],
                            condition=condition,
                            condition_config=cc,
                            repeat=repeat,
                            task_ids=task_ids,
                        )
                    locators.extend(current)
                    write_json(
                        paths.experiment_root / "run_index.json",
                        [locator.__dict__ for locator in locators],
                    )
    print(f"Run index contains {len(locators)} task-condition records")
    return 0


def _locators(args: argparse.Namespace, config, paths, models) -> list[RunLocator]:
    index_path = paths.experiment_root / "run_index.json"
    task_ids, frameworks, model_names, conditions, repeat_counts = _matrix(
        args,
        config,
        paths,
        models,
    )
    values = []
    for framework in frameworks:
        adapter = _adapter(config, paths, framework)
        for model_name in model_names:
            for condition in conditions:
                for repeat in range(1, repeat_counts[condition] + 1):
                    values.extend(
                        adapter.locate(
                            model_name=model_name,
                            condition=condition,
                            condition_config=condition_config(config, condition),
                            repeat=repeat,
                            task_ids=task_ids,
                        )
                    )
    write_json(
        index_path,
        [locator.__dict__ for locator in values],
    )
    return values


def collect_command(args: argparse.Namespace) -> int:
    config, paths, models = _context(args)
    _, tasks_by_id = _tasks(paths)
    locators = _locators(args, config, paths, models)
    traces = [
        normalize_run(locator, tasks_by_id[locator.task_id])
        for locator in locators
    ]
    output = paths.experiment_root / "normalized" / "traces.jsonl"
    write_jsonl(output, (trace.to_dict() for trace in traces))
    counts = Counter(trace.status for trace in traces)
    print(f"Collected {len(traces)} traces: {dict(counts)}")
    return 0


def _contracts(paths) -> dict[str, dict[str, Any]]:
    path = paths.experiment_root / "contracts" / "task_contracts.jsonl"
    if not path.is_file():
        build_contracts(paths.task_json, path.parent)
    return {row["task_id"]: row for row in read_jsonl(path)}


def score_command(args: argparse.Namespace) -> int:
    config, paths, models = _context(args)
    tasks, tasks_by_id = _tasks(paths)
    contracts = _contracts(paths)
    trace_path = paths.experiment_root / "normalized" / "traces.jsonl"
    if not trace_path.is_file():
        collect_command(args)
    traces = [TraceRecord.from_dict(row) for row in read_jsonl(trace_path)]
    metrics = [
        score_trace(
            trace,
            tasks_by_id[trace.locator.task_id],
            contracts[trace.locator.task_id],
        )
        for trace in traces
    ]
    judge_path = paths.experiment_root / "judge" / "scores.jsonl"
    if judge_path.is_file():
        judge = {
            (
                row["task_id"],
                row["framework"],
                row["model"],
                row["condition"],
                int(row.get("repeat", 1)),
            ): row
            for row in read_jsonl(judge_path)
            if row.get("status") == "ok"
        }
        for row in metrics:
            key = (
                row["task_id"],
                row["framework"],
                row["model"],
                row["condition"],
                int(row.get("repeat", 1)),
            )
            if key in judge:
                row["response_quality"] = judge[key]["response_quality"]
                row["judge_scores"] = judge[key]
            else:
                row["response_quality"] = None
    else:
        for row in metrics:
            row["response_quality"] = None
    output = paths.experiment_root / "normalized" / "task_metrics.jsonl"
    write_jsonl(output, metrics)
    write_csv(paths.experiment_root / "normalized" / "task_metrics.csv", metrics)
    print(
        f"Scored {len(metrics)} records; passed="
        f"{sum(bool(row['passed']) for row in metrics)}"
    )
    return 0


def judge_command(args: argparse.Namespace) -> int:
    config, paths, models = _context(args)
    judge_config = config.get("judge") or {}
    if not judge_config.get("enabled", False) and not args.force_judge:
        print("LLM Judge disabled; set judge.enabled=true or pass --force-judge")
        return 0
    profile_name = str(judge_config.get("model_profile") or selected_names(config, "models")[0])
    if profile_name not in models:
        raise ValueError(f"Judge model profile not found: {profile_name}")
    model_config = generated_model_config(
        repo_root=paths.repo_root,
        experiment_root=paths.experiment_root,
        profile_name=f"judge_{profile_name}",
        profile=models[profile_name],
    )
    tasks, tasks_by_id = _tasks(paths)
    trace_path = paths.experiment_root / "normalized" / "traces.jsonl"
    if not trace_path.is_file():
        collect_command(args)
    traces = read_jsonl(trace_path)
    scores = asyncio.run(
        judge_traces(
            traces=traces,
            tasks_by_id=tasks_by_id,
            model_config_path=model_config,
            output_dir=paths.experiment_root / "judge",
            concurrency=int(judge_config.get("concurrency", 4)),
            timeout_seconds=int(judge_config.get("timeout", 180)),
        )
    )
    write_jsonl(paths.experiment_root / "judge" / "scores.jsonl", scores)
    print(
        f"Judged {len(scores)} records; ok="
        f"{sum(row.get('status') == 'ok' for row in scores)}"
    )
    return 0


def report_command(args: argparse.Namespace) -> int:
    config, paths, models = _context(args)
    metric_path = paths.experiment_root / "normalized" / "task_metrics.jsonl"
    if not metric_path.is_file():
        score_command(args)
    rows = read_jsonl(metric_path)
    statistics = config.get("statistics") or {}
    result = generate_reports(
        rows,
        paths.experiment_root / "reports",
        bootstrap_samples=int(statistics.get("bootstrap_samples", 10000)),
        confidence=float(statistics.get("confidence", 0.95)),
        comparison_baselines={
            condition: str(
                condition_config(config, condition).get(
                    "comparison_baseline",
                    "baseline",
                )
            )
            for condition in selected_names(config, "conditions")
        },
    )
    for row in result["overall"]:
        print(
            f"{row['framework']} | {row['model']} | {row['condition']} | "
            f"passed={row['passed']}/{row['task_count']} | "
            f"Avg@{row.get('avg_at_k_k') or 'k'}={row['avg_at_k']:.4f}"
        )
    return 0


def status_command(args: argparse.Namespace) -> int:
    config, paths, models = _context(args)
    locators = _locators(args, config, paths, models)
    groups: Counter[tuple[str, str, str]] = Counter()
    completed: Counter[tuple[str, str, str]] = Counter()
    for locator in locators:
        key = (locator.framework, locator.model, locator.condition)
        groups[key] += 1
        result = Path(locator.run_root) / "task_result.json"
        if result.is_file():
            completed[key] += 1
    for key in sorted(groups):
        print(
            f"{key[0]} | {key[1]} | {key[2]} | "
            f"{completed[key]}/{groups[key]}"
        )
    return 0


def pipeline_command(args: argparse.Namespace) -> int:
    stages = [
        value.strip()
        for value in args.stages.split(",")
        if value.strip()
    ]
    functions = {
        "validate": validate_command,
        "run": run_command,
        "collect": collect_command,
        "score": score_command,
        "judge": judge_command,
        "report": report_command,
    }
    for stage in stages:
        if stage not in functions:
            raise ValueError(f"Unknown pipeline stage: {stage}")
        print(f"[stage] {stage}", flush=True)
        code = functions[stage](args)
        if code and stage != "validate":
            return code
        if stage == "judge":
            score_command(args)
    return 0


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--experiment", required=True)
    common.add_argument("--models-config", required=True)
    common.add_argument("--framework", action="append")
    common.add_argument("--model", action="append")
    common.add_argument("--condition", action="append")
    common.add_argument("--task-limit", type=int)
    common.add_argument("--repeats", type=int, help="Override independent repeat count k")
    common.add_argument("--concurrency", type=int, help="Override agent concurrency")
    common.add_argument(
        "--submission-delay",
        type=float,
        help="Override seconds between starting independent agent workers",
    )
    common.add_argument("--batch-size", type=int, help="Override tasks per runner batch")
    common.add_argument("--dry-run", action="store_true")
    common.add_argument("--force-judge", action="store_true")
    common.add_argument(
        "--stages",
        default="validate,run,collect,score,judge,report",
    )
    root = argparse.ArgumentParser(description="Unified benchmark experiment pipeline")
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("validate", "run", "collect", "score", "judge", "report", "status"):
        sub.add_parser(name, parents=[common])
    sub.add_parser("pipeline", parents=[common])
    add_data_parser(sub)
    return root


def main() -> int:
    args = parser().parse_args()
    function = {
        "validate": validate_command,
        "run": run_command,
        "collect": collect_command,
        "score": score_command,
        "judge": judge_command,
        "report": report_command,
        "status": status_command,
        "pipeline": pipeline_command,
        "data": data_command,
    }[args.command]
    try:
        return function(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"[fatal] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
