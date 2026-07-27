from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from benchmark_eval.adapters.base import FrameworkAdapter
from benchmark_eval.config import make_run_id
from benchmark_eval.schema import RunLocator
from benchmark_eval.utils import safe_name

CONDITION_FLAGS = {
    "baseline": ("off", "correct", "available"),
    "self_route": ("on", "all", "available"),
    "oracle_skill": ("on", "required", "preload"),
    "required_read": ("on", "required", "required-read"),
    "force_use": ("on", "required", "force-use"),
    "description_only": ("on", "correct", "preload"),
}


class NanobotAdapter(FrameworkAdapter):
    framework = "nanobot"

    @staticmethod
    def _condition_flags(
        condition: str,
        condition_config: dict[str, Any],
    ) -> tuple[str, str, str]:
        base_condition = str(condition_config.get("base_condition") or condition)
        if base_condition not in CONDITION_FLAGS:
            raise ValueError(
                f"Unsupported Nanobot base condition: {base_condition} "
                f"(configured for {condition})"
            )
        return CONDITION_FLAGS[base_condition]

    def _condition_skills_root(
        self,
        condition_config: dict[str, Any],
    ) -> Path:
        configured = condition_config.get("skills_root")
        if not configured:
            return self.skills_root
        path = Path(os.path.expanduser(str(configured)))
        path = path if path.is_absolute() else self.repo_root / path
        if not path.is_dir():
            raise FileNotFoundError(f"Condition skills root not found: {path}")
        return path

    @staticmethod
    def _retryable_tasks(
        locators_by_task: dict[str, RunLocator],
        task_ids: list[str],
    ) -> list[str]:
        retryable = []
        for task_id in task_ids:
            result_path = Path(locators_by_task[task_id].run_root) / "task_result.json"
            try:
                result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                retryable.append(task_id)
                continue
            if result.get("status") == "infrastructure_error":
                retryable.append(task_id)
        return retryable

    @staticmethod
    def _record_attempt_count(locator: RunLocator, attempt_count: int) -> None:
        result_path = Path(locator.run_root) / "task_result.json"
        try:
            result = json.loads(result_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return
        result["whole_task_attempt_count"] = attempt_count
        result["infrastructure_retry_count"] = max(attempt_count - 1, 0)
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _run_id(
        self,
        *,
        model_name: str,
        condition: str,
        condition_config: dict[str, Any],
        repeat: int,
    ) -> str:
        configured = condition_config.get("run_id")
        if configured:
            return safe_name(str(configured).format(repeat=repeat, model=model_name))
        return make_run_id(
            str(self.experiment_config["experiment_id"]),
            self.framework,
            model_name,
            condition,
            repeat,
        )

    def locate(
        self,
        *,
        model_name: str,
        condition: str,
        condition_config: dict[str, Any],
        repeat: int,
        task_ids: list[str],
    ) -> list[RunLocator]:
        run_id = self._run_id(
            model_name=model_name,
            condition=condition,
            condition_config=condition_config,
            repeat=repeat,
        )
        skill_mode = self._condition_flags(condition, condition_config)[0]
        return [
            RunLocator(
                task_id=task_id,
                framework=self.framework,
                model=model_name,
                condition=condition,
                repeat=repeat,
                run_id=run_id,
                run_root=str(
                    self.runs_root
                    / safe_name(task_id)
                    / f"skill_{skill_mode}"
                    / safe_name(run_id)
                ),
            )
            for task_id in task_ids
        ]

    def execute(
        self,
        *,
        model_name: str,
        model_profile: dict[str, Any],
        model_config_path: Path,
        condition: str,
        condition_config: dict[str, Any],
        repeat: int,
        task_ids: list[str],
    ) -> list[RunLocator]:
        skill_mode, experiment_mode, policy = self._condition_flags(
            condition,
            condition_config,
        )
        locators = self.locate(
            model_name=model_name,
            condition=condition,
            condition_config=condition_config,
            repeat=repeat,
            task_ids=task_ids,
        )
        if condition_config.get("execute", True) is False:
            return locators

        runtime = self.experiment_config.get("runtime") or {}
        python_exe = str(
            model_profile.get("python")
            or runtime.get("python")
            or sys.executable
        )
        skills_root = self._condition_skills_root(condition_config)
        excluded_skills = condition_config.get("exclude_skills") or []
        if isinstance(excluded_skills, str):
            excluded_skills = [excluded_skills]
        excluded_skills = [str(value) for value in excluded_skills]
        skill_view = str(condition_config.get("skill_view") or "full")
        run_id = locators[0].run_id if locators else self._run_id(
            model_name=model_name,
            condition=condition,
            condition_config=condition_config,
            repeat=repeat,
        )
        batch_size = int(runtime.get("batch_size", 24))
        log_dir = self.experiment_root / "logs" / self.framework / safe_name(model_name)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{safe_name(condition)}_r{repeat:02d}.log"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(self.repo_root) + (
            os.pathsep + environment["PYTHONPATH"]
            if environment.get("PYTHONPATH")
            else ""
        )
        environment["NANOBOT_LLM_TIMEOUT_S"] = str(
            model_profile.get("llm_timeout", runtime.get("llm_timeout", 600))
        )
        locators_by_task = {locator.task_id: locator for locator in locators}
        max_task_attempts = max(int(runtime.get("max_task_attempts", 3)), 1)
        retry_backoff = max(float(runtime.get("retry_backoff_seconds", 15)), 0.0)
        task_concurrency = int(
            condition_config.get("concurrency", runtime.get("concurrency", 8))
        )
        submission_delay = float(
            condition_config.get(
                "submission_delay_seconds",
                runtime.get("submission_delay_seconds", 0.0),
            )
        )

        for start in range(0, len(task_ids), batch_size):
            batch = task_ids[start : start + batch_size]
            attempt_counts = {task_id: 1 for task_id in batch}
            print(
                f"[progress] framework=nanobot model={model_name} "
                f"condition={condition} repeat={repeat} "
                f"start={start} size={len(batch)}",
                flush=True,
            )
            command = [
                python_exe,
                "-B",
                str(self.repo_root / "isolated_benchmark_runner" / "run_isolated_task.py"),
                "--python",
                python_exe,
                "--task-json",
                str(self.task_json),
                "--data-root",
                str(self.data_root),
                "--asset-mode",
                str(runtime.get("asset_mode", "copy")),
                "--sandbox",
                str(runtime.get("sandbox", "none")),
                "--skills-root",
                str(skills_root),
                "--base-config",
                str(model_config_path),
                "--skill-mode",
                skill_mode,
                "--skill-experiment-mode",
                experiment_mode,
                "--skill-policy",
                policy,
                "--run-id",
                run_id,
                "--execute",
                "--backend",
                str(runtime.get("backend", "direct")),
                "--concurrency",
                str(task_concurrency),
                "--submission-delay",
                str(submission_delay),
                "--max-tool-iterations",
                str(runtime.get("max_tool_iterations", 80)),
                "--turn-timeout",
                str(runtime.get("turn_timeout", 1800)),
                "--keep-going",
                "--resume-existing",
            ]
            for excluded_skill in excluded_skills:
                command.extend(["--exclude-skill", excluded_skill])
            command.extend(["--skill-view", skill_view])
            base_command = list(command)
            for task_id in batch:
                command.extend(["--task-id", task_id])

            with log_path.open("a", encoding="utf-8") as log:
                log.write(
                    f"[batch] condition={condition} repeat={repeat} "
                    f"start={start} size={len(batch)}\n"
                )
                log.flush()
                result = subprocess.run(
                    command,
                    cwd=self.repo_root,
                    env=environment,
                    stdout=log,
                    stderr=log,
                    check=False,
                )
                log.write(f"[batch-done] exit={result.returncode}\n")
            pending = self._retryable_tasks(locators_by_task, batch)
            for attempt in range(2, max_task_attempts + 1):
                if not pending:
                    break
                delay = retry_backoff * (2 ** (attempt - 2))
                print(
                    f"[retry] framework=nanobot model={model_name} "
                    f"condition={condition} repeat={repeat} attempt={attempt} "
                    f"tasks={len(pending)} backoff={delay:.1f}s",
                    flush=True,
                )
                if delay:
                    time.sleep(delay)
                retry_command = list(base_command)
                for task_id in pending:
                    attempt_counts[task_id] += 1
                    retry_command.extend(["--task-id", task_id])
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(
                        f"[retry] attempt={attempt} tasks={len(pending)}\n"
                    )
                    retry_result = subprocess.run(
                        retry_command,
                        cwd=self.repo_root,
                        env=environment,
                        stdout=log,
                        stderr=log,
                        check=False,
                    )
                    log.write(
                        f"[retry-done] attempt={attempt} "
                        f"exit={retry_result.returncode}\n"
                    )
                pending = self._retryable_tasks(locators_by_task, pending)
            for task_id in batch:
                self._record_attempt_count(
                    locators_by_task[task_id],
                    attempt_counts[task_id],
                )
            if pending:
                print(
                    f"[retry-exhausted] framework=nanobot model={model_name} "
                    f"condition={condition} repeat={repeat} tasks={len(pending)}",
                    flush=True,
                )
                if runtime.get("fail_on_retry_exhausted", False):
                    raise RuntimeError(
                        "Retryable infrastructure/output failures remain after "
                        f"{max_task_attempts} attempts: {len(pending)} task(s). "
                        "The experiment is stopped so invalid runs cannot enter the report."
                    )
            if result.returncode not in {0, 1} and not runtime.get("keep_going", True):
                raise RuntimeError(
                    f"Nanobot batch failed with exit {result.returncode}; see {log_path}"
                )
            print(
                f"[progress-done] framework=nanobot model={model_name} "
                f"condition={condition} repeat={repeat} "
                f"start={start} exit={result.returncode}",
                flush=True,
            )
            if runtime.get("prune_workspace_datasets", False):
                prune_command = [
                    python_exe,
                    "-B",
                    str(self.repo_root / "tools" / "prune_run_workspace_datasets.py"),
                    "--runs-root",
                    str(self.runs_root),
                    "--run-id",
                    run_id,
                    "--skill-mode",
                    skill_mode,
                    "--execute",
                ]
                with log_path.open("a", encoding="utf-8") as log:
                    prune_result = subprocess.run(
                        prune_command,
                        cwd=self.repo_root,
                        env=environment,
                        stdout=log,
                        stderr=log,
                        check=False,
                    )
                    log.write(f"[batch-prune] exit={prune_result.returncode}\n")
                print(
                    f"[progress-prune] framework=nanobot model={model_name} "
                    f"condition={condition} repeat={repeat} "
                    f"start={start} exit={prune_result.returncode}",
                    flush=True,
                )
                artifact_command = [
                    python_exe,
                    "-B",
                    str(self.repo_root / "tools" / "prune_run_oversized_artifacts.py"),
                    "--runs-root",
                    str(self.runs_root),
                    "--run-id",
                    run_id,
                    "--skill-mode",
                    skill_mode,
                    "--execute",
                ]
                with log_path.open("a", encoding="utf-8") as log:
                    artifact_result = subprocess.run(
                        artifact_command,
                        cwd=self.repo_root,
                        env=environment,
                        stdout=log,
                        stderr=log,
                        check=False,
                    )
                    log.write(f"[batch-artifact-prune] exit={artifact_result.returncode}\n")
                print(
                    f"[progress-artifact-prune] framework=nanobot model={model_name} "
                    f"condition={condition} repeat={repeat} "
                    f"start={start} exit={artifact_result.returncode}",
                    flush=True,
                )
        return locators
