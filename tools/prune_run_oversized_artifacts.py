#!/usr/bin/env python3
"""Remove oversized generated workspace artifacts from terminal benchmark runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TERMINAL_STATUSES = {"completed", "failed"}
GENERATED_SUFFIXES = {".csv", ".json", ".jsonl", ".parquet", ".pq", ".xlsx"}


def load_status(run_root: Path) -> str:
    try:
        result = json.loads((run_root / "task_result.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return "incomplete"
    return str(result.get("status") or "incomplete")


def candidate(file: Path, workspace: Path, minimum_bytes: int) -> bool:
    try:
        relative = file.relative_to(workspace)
        size = file.stat().st_size
    except (OSError, ValueError):
        return False
    if size < minimum_bytes or file.suffix.lower() not in GENERATED_SUFFIXES:
        return False
    if relative.parts and relative.parts[0] in {"datasets", "sessions", "skills", ".nanobot"}:
        return False
    return relative.parts[:1] == ("skill_evidence",) or len(relative.parts) == 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path(__file__).resolve().parents[1] / "runs")
    parser.add_argument("--min-mib", type=float, default=100.0)
    parser.add_argument("--run-id", action="append", help="Only inspect these run IDs.")
    parser.add_argument("--skill-mode", choices=("on", "off"))
    parser.add_argument(
        "--include-incomplete",
        action="store_true",
        help="Also inspect runs without terminal task_result.json; use only after stopping all benchmark processes.",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    runs_root = args.runs_root.resolve()
    if not runs_root.is_dir() or runs_root.name != "runs":
        raise ValueError(f"invalid runs root: {runs_root}")
    minimum_bytes = int(args.min_mib * 1024 * 1024)
    rows = []
    run_roots = {path.parent for path in runs_root.glob("*/skill_*/*/task_result.json")}
    run_roots.update(path.parent for path in runs_root.glob("*/skill_*/*/workspace"))
    statuses: dict[str, int] = {}
    for run_root in sorted(run_roots):
        if args.run_id and run_root.name not in set(args.run_id):
            continue
        if args.skill_mode and run_root.parent.name != f"skill_{args.skill_mode}":
            continue
        status = load_status(run_root)
        statuses[status] = statuses.get(status, 0) + 1
        if status not in TERMINAL_STATUSES and not args.include_incomplete:
            continue
        workspace = run_root / "workspace"
        if not workspace.is_dir():
            continue
        for file in workspace.rglob("*"):
            if not file.is_file() or not candidate(file, workspace, minimum_bytes):
                continue
            size = file.stat().st_size
            rows.append({"path": str(file), "bytes": size})
            if args.execute:
                file.unlink(missing_ok=True)
    summary = {
        "mode": "execute" if args.execute else "dry_run",
        "file_count": len(rows),
        "bytes": sum(row["bytes"] for row in rows),
        "gib": round(sum(row["bytes"] for row in rows) / 1024**3, 3),
        "discovered_run_statuses": statuses,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.execute and rows:
        print("Dry-run only. Re-run with --execute to delete listed artifact classes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
