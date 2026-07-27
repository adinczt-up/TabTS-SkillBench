#!/usr/bin/env python3
"""Remove copied dataset files from terminal benchmark run workspaces.

The benchmark outputs, traces, prompts, skills, and task results are preserved.
Dry-run is the default; pass --execute to perform deletion.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = REPO_ROOT / "runs"
TERMINAL_STATUSES = {"completed", "failed"}


@dataclass
class Candidate:
    run_root: str
    datasets_path: str
    task_id: str
    skill_mode: str
    run_id: str
    status: str
    file_count: int
    bytes: int
    action: str
    reason: str = ""


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def tree_size(path: Path) -> tuple[int, int]:
    files = 0
    size = 0
    for root, _, names in os.walk(path):
        for name in names:
            file_path = Path(root) / name
            try:
                size += file_path.stat().st_size
                files += 1
            except OSError:
                continue
    return files, size


def safe_dataset_path(path: Path, runs_root: Path) -> bool:
    if path.name != "datasets" or path.parent.name != "workspace":
        return False
    if path.is_symlink():
        return False
    try:
        path.resolve().relative_to(runs_root.resolve())
    except (OSError, ValueError):
        return False
    return True


def remove_with_retry(path: Path, attempts: int = 8) -> None:
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (2**attempt))


def discover_run_roots(runs_root: Path) -> list[Path]:
    roots = []
    for result_path in runs_root.glob("*/skill_*/*/task_result.json"):
        roots.append(result_path.parent)
    # Include incomplete runs in the report so skipped storage is visible.
    for datasets_path in runs_root.glob("*/skill_*/*/workspace/datasets"):
        run_root = datasets_path.parents[1]
        if run_root not in roots:
            roots.append(run_root)
    return sorted(set(roots))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--execute", action="store_true", help="Delete eligible workspace/datasets directories.")
    parser.add_argument("--include-incomplete", action="store_true", help="Also delete runs without a terminal task_result.json. Unsafe while a run is active.")
    parser.add_argument("--run-id", action="append", help="Only inspect these run IDs; repeatable or comma-separated.")
    parser.add_argument("--task-id", action="append", help="Only inspect these task IDs; repeatable or comma-separated.")
    parser.add_argument("--skill-mode", choices=("on", "off"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    runs_root = args.runs_root.expanduser().resolve()
    if not runs_root.is_dir() or runs_root.name != "runs":
        raise ValueError(f"runs root must be an existing directory named 'runs': {runs_root}")

    def split(values: list[str] | None) -> set[str]:
        return {
            part.strip()
            for value in (values or [])
            for part in value.split(",")
            if part.strip()
        }

    run_ids = split(args.run_id)
    task_ids = split(args.task_id)
    rows: list[Candidate] = []

    for run_root in discover_run_roots(runs_root):
        try:
            task_id = run_root.parents[1].name
            skill_dir = run_root.parent.name
            run_id = run_root.name
        except IndexError:
            continue
        skill_mode = skill_dir.removeprefix("skill_")
        if run_ids and run_id not in run_ids:
            continue
        if task_ids and task_id not in task_ids:
            continue
        if args.skill_mode and skill_mode != args.skill_mode:
            continue

        datasets_path = run_root / "workspace" / "datasets"
        if not datasets_path.is_dir():
            continue
        if not safe_dataset_path(datasets_path, runs_root):
            rows.append(Candidate(str(run_root), str(datasets_path), task_id, skill_mode, run_id, "unknown", 0, 0, "skipped", "unsafe_path"))
            continue

        result = load_json(run_root / "task_result.json")
        status = str((result or {}).get("status") or "incomplete")
        terminal = status in TERMINAL_STATUSES
        files, size = tree_size(datasets_path)
        if not terminal and not args.include_incomplete:
            rows.append(Candidate(str(run_root), str(datasets_path), task_id, skill_mode, run_id, status, files, size, "skipped", "nonterminal_run"))
            continue

        action = "eligible"
        reason = "terminal_run" if terminal else "include_incomplete_requested"
        if args.execute:
            remove_with_retry(datasets_path)
            action = "deleted"
        rows.append(Candidate(str(run_root), str(datasets_path), task_id, skill_mode, run_id, status, files, size, action, reason))

    eligible = [row for row in rows if row.action in {"eligible", "deleted"}]
    deleted = [row for row in rows if row.action == "deleted"]
    skipped = [row for row in rows if row.action == "skipped"]
    summary = {
        "mode": "execute" if args.execute else "dry_run",
        "runs_root": str(runs_root),
        "eligible_directory_count": len(eligible),
        "eligible_file_count": sum(row.file_count for row in eligible),
        "eligible_bytes": sum(row.bytes for row in eligible),
        "eligible_gib": round(sum(row.bytes for row in eligible) / (1024**3), 3),
        "deleted_directory_count": len(deleted),
        "skipped_directory_count": len(skipped),
        "rows": [asdict(row) for row in rows],
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "rows"}, ensure_ascii=False, indent=2))
    if not args.execute and eligible:
        print("Dry-run only. Re-run with --execute to delete eligible workspace datasets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
