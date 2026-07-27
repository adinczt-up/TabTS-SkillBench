from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from benchmark_eval.adapters.base import FrameworkAdapter
from benchmark_eval.config import make_run_id
from benchmark_eval.schema import RunLocator
from benchmark_eval.utils import safe_name


class ExternalCommandAdapter(FrameworkAdapter):
    """Adapter for Codex, Claude Code, or another framework via a wrapper command.

    The wrapper receives environment variables and must write one
    ``task_result.json`` under each requested run root using the Nanobot-compatible
    final-output fields. Framework-specific trace files may be added beside it.
    """

    def __init__(self, *, framework: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.framework = framework

    def _options(self) -> dict[str, Any]:
        options = self.experiment_config.get("framework_options") or {}
        return dict(options.get(self.framework) or {})

    def _run_id(
        self,
        model_name: str,
        condition: str,
        condition_config: dict[str, Any],
        repeat: int,
    ) -> str:
        if condition_config.get("run_id"):
            return safe_name(
                str(condition_config["run_id"]).format(
                    repeat=repeat,
                    model=model_name,
                )
            )
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
        run_id = self._run_id(model_name, condition, condition_config, repeat)
        root = self.experiment_root / "external_runs" / self.framework
        return [
            RunLocator(
                task_id=task_id,
                framework=self.framework,
                model=model_name,
                condition=condition,
                repeat=repeat,
                run_id=run_id,
                run_root=str(root / safe_name(task_id) / run_id),
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
        locators = self.locate(
            model_name=model_name,
            condition=condition,
            condition_config=condition_config,
            repeat=repeat,
            task_ids=task_ids,
        )
        if condition_config.get("execute", True) is False:
            return locators
        command = self._options().get("command")
        if not command:
            raise ValueError(
                f"framework_options.{self.framework}.command is required. "
                "Point it to a wrapper implementing docs/FRAMEWORK_ADAPTER.md."
            )
        environment = os.environ.copy()
        environment.update(
            {
                "BENCHMARK_FRAMEWORK": self.framework,
                "BENCHMARK_MODEL": str(model_profile.get("model", model_name)),
                "BENCHMARK_MODEL_PROFILE": model_name,
                "BENCHMARK_CONDITION": condition,
                "BENCHMARK_REPEAT": str(repeat),
                "BENCHMARK_TASK_JSON": str(self.task_json),
                "BENCHMARK_TASK_IDS": ",".join(task_ids),
                "BENCHMARK_DATA_ROOT": str(self.data_root),
                "BENCHMARK_SKILLS_ROOT": str(self.skills_root),
                "BENCHMARK_OUTPUT_ROOT": str(
                    self.experiment_root / "external_runs" / self.framework
                ),
                "BENCHMARK_RUN_ID": locators[0].run_id if locators else "",
            }
        )
        log = (
            self.experiment_root
            / "logs"
            / self.framework
            / f"{safe_name(model_name)}_{safe_name(condition)}_r{repeat:02d}.log"
        )
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            result = subprocess.run(
                str(command),
                shell=True,
                cwd=self.repo_root,
                env=environment,
                stdout=handle,
                stderr=handle,
                check=False,
            )
        if result.returncode != 0:
            raise RuntimeError(
                f"{self.framework} wrapper failed with exit {result.returncode}; see {log}"
            )
        return locators
