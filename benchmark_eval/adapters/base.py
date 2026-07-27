from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from benchmark_eval.schema import RunLocator


class FrameworkAdapter(ABC):
    def __init__(
        self,
        *,
        repo_root: Path,
        experiment_root: Path,
        task_json: Path,
        data_root: Path,
        skills_root: Path,
        runs_root: Path,
        experiment_config: dict[str, Any],
    ) -> None:
        self.repo_root = repo_root
        self.experiment_root = experiment_root
        self.task_json = task_json
        self.data_root = data_root
        self.skills_root = skills_root
        self.runs_root = runs_root
        self.experiment_config = experiment_config

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def locate(
        self,
        *,
        model_name: str,
        condition: str,
        condition_config: dict[str, Any],
        repeat: int,
        task_ids: list[str],
    ) -> list[RunLocator]:
        raise NotImplementedError
