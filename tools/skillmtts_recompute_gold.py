#!/usr/bin/env python3
"""Recompute stored SkillMTTS Gold from each task's final deterministic Oracle SQL."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

import duckdb


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_write(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        return None if not math.isfinite(value) else round(value, 8)
    if hasattr(value, "item"):
        return normalize(value.item())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def execute(connection: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = connection.execute(sql)
    columns = [item[0] for item in cursor.description]
    return [{column: normalize(value) for column, value in zip(columns, row)} for row in cursor.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-json", required=True, type=Path)
    parser.add_argument("--gold-json", type=Path)
    parser.add_argument("--validation-report", type=Path, help="Only recompute invalid task ids from this report.")
    parser.add_argument("--all", action="store_true", help="Recompute every task instead of only invalid report rows.")
    parser.add_argument("--task-family", action="append", help="Recompute every task in these task families.")
    parser.add_argument("--stabilize-correlation-ranking", action="store_true")
    args = parser.parse_args()
    if not args.all and not args.validation_report and not args.task_family:
        parser.error("use --all, --validation-report, or --task-family")

    tasks = load(args.task_json)
    selected: set[str]
    if args.all:
        selected = {str(task["task_id"]) for task in tasks}
    elif args.task_family:
        wanted = set(args.task_family)
        selected = {str(task["task_id"]) for task in tasks if task.get("metadata", {}).get("task_family") in wanted}
    else:
        report = load(args.validation_report)
        selected = {str(row["task_id"]) for row in report["tasks"] if not row.get("valid")}
    if not selected:
        print("No invalid tasks require Gold recomputation.")
        return 0

    connection = duckdb.connect()
    connection.execute("SET threads=4")
    changed = []
    for task in tasks:
        task_id = str(task["task_id"])
        if task_id not in selected:
            continue
        metadata = task["metadata"]
        if args.stabilize_correlation_ranking and metadata.get("task_family") in {"lagged_cross_correlation", "autocorrelation_structure"}:
            metadata["oracle_sql"] = str(metadata["oracle_sql"]).replace(
                "CORR(response,predictor) correlation",
                "ROUND(CORR(response,predictor),6) correlation",
            )
            metadata["oracle_sql"] = str(metadata["oracle_sql"]).replace(
                "WHERE correlation IS NOT NULL QUALIFY",
                "WHERE correlation IS NOT NULL AND isfinite(correlation) QUALIFY",
            )
            contract = metadata.setdefault("semantic_contract", {})
            contract["selection"] = "largest finite absolute correlation after rounding to 6 decimals, per group then global top 3"
            contract["selection_precision"] = 6
            contract["nonfinite_policy"] = "exclude undefined correlations"
            question = task["turns"][-1]["question"]
            question = question.replace(
                "Within each group keep the lag with largest absolute correlation",
                "Round correlations to 6 decimals for selection; within each group keep the lag with largest absolute selected correlation",
            ).replace("round correlation to 4 decimals", "round reported correlation to 4 decimals")
            if "exclude undefined correlations" not in question:
                question = question.replace(
                    "from exactly that many calendar months earlier.",
                    "from exactly that many calendar months earlier and exclude undefined correlations.",
                )
            task["turns"][-1]["question"] = question
        rows = execute(connection, str(metadata["oracle_sql"]))
        if not rows:
            raise RuntimeError(f"final Oracle returned no rows: {task_id}")
        expected_fields = list(metadata["output_fields"])
        if any(list(row) != expected_fields for row in rows):
            raise RuntimeError(f"final Oracle schema mismatch: {task_id}")
        metadata["gold_rows"] = rows
        metadata["gold_provenance"] = "deterministic_duckdb_oracle_recomputed_from_final_sql"
        metadata["full_gold_verified"] = True
        changed.append(task_id)
    connection.close()
    missing = selected - set(changed)
    if missing:
        raise KeyError(f"validation report contains unknown task ids: {sorted(missing)}")

    gold_path = args.gold_json or args.task_json.with_name("gold.json")
    gold = [{
        "task_id": task["task_id"],
        "question": task["turns"][-1]["question"],
        "gold_rows": task["metadata"]["gold_rows"],
        "key_fields": task["metadata"]["key_fields"],
        "output_fields": task["metadata"]["output_fields"],
    } for task in tasks]
    atomic_write(args.task_json, tasks)
    atomic_write(gold_path, gold)
    print(json.dumps({"recomputed_count": len(changed), "task_ids": changed}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
