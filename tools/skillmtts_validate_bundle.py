"""Validate task, data, Oracle, and skill contracts for a SkillMTTS bundle."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


def as_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    raise TypeError("gold_rows must be an object or array of objects")


def scalar_equal(left: Any, right: Any, tolerance: float) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)
    return str(left).strip().casefold() == str(right).strip().casefold()


def rows_equal(actual: list[dict[str, Any]], expected: list[dict[str, Any]], keys: list[str], tolerance: float) -> bool:
    def key(row: dict[str, Any]):
        return tuple(str(row.get(field, "")).strip().casefold() for field in keys)
    actual_map = {key(row): row for row in actual}
    expected_map = {key(row): row for row in expected}
    if set(actual_map) != set(expected_map):
        return False
    for row_key, expected_row in expected_map.items():
        actual_row = actual_map[row_key]
        if set(actual_row) != set(expected_row):
            return False
        if any(not scalar_equal(actual_row[field], expected_row[field], tolerance) for field in expected_row):
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-json", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--skills-root", required=True, type=Path)
    parser.add_argument("--duckdb", type=Path)
    parser.add_argument("--min-required-tables", type=int, default=3)
    parser.add_argument("--numeric-tolerance", type=float, default=5e-4)
    parser.add_argument("--max-core-skills", type=int, default=4)
    parser.add_argument("--require-semantic-contract", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    tasks = json.loads(args.task_json.read_text(encoding="utf-8-sig"))
    if not isinstance(tasks, list):
        raise TypeError("task JSON must contain an array")
    connection = None
    if args.duckdb:
        import duckdb
        connection = duckdb.connect(str(args.duckdb), read_only=True)

    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    reports = []
    for task in tasks:
        errors = []
        warnings = []
        task_id = str(task.get("task_id", ""))
        question = "\n".join(str(turn.get("question", "")) for turn in task.get("turns", []))
        metadata = task.get("metadata", {})
        if not task_id or task_id in seen_ids:
            errors.append("missing or duplicate task_id")
        if not question.strip() or question in seen_questions:
            errors.append("missing or duplicate question")
        seen_ids.add(task_id)
        seen_questions.add(question)

        assets = task.get("data_assets", [])
        missing_assets = [str(asset.get("path")) for asset in assets if not (args.data_root / str(asset.get("path", ""))).is_file()]
        if missing_assets:
            errors.append(f"missing data assets: {missing_assets}")
        required_tables = list(metadata.get("required_tables", []))
        if len(required_tables) < args.min_required_tables:
            errors.append(f"too few required tables: {len(required_tables)}")

        try:
            gold_rows = as_rows(metadata.get("gold_rows"))
        except Exception as exc:
            gold_rows = []
            errors.append(str(exc))
        key_fields = list(metadata.get("key_fields", []))
        if not key_fields or any(field not in row for row in gold_rows for field in key_fields):
            errors.append("invalid key_fields")
        oracle = str(metadata.get("oracle_sql", "")).strip()
        if not oracle:
            errors.append("missing oracle_sql")
        if re.search(r"\b(random|current_date|current_timestamp|now)\s*\(", oracle, re.I):
            errors.append("nondeterministic Oracle function")
        missing_sql_tables = [table for table in required_tables if table.casefold() not in oracle.casefold()]
        if missing_sql_tables:
            warnings.append(f"required tables not found literally in SQL: {missing_sql_tables}")

        skills = list(task.get("skills", []))
        supporting_skills = list(task.get("supporting_skills", []))
        if len(skills) > args.max_core_skills:
            errors.append(f"too many core skills: {len(skills)} > {args.max_core_skills}")
        overlap = sorted(set(skills) & set(supporting_skills))
        if overlap:
            errors.append(f"core/supporting skill overlap: {overlap}")
        missing_skills = [
            name for name in skills + supporting_skills
            if not (args.skills_root / name / "SKILL.md").is_file()
        ]
        if missing_skills:
            errors.append(f"missing skills: {missing_skills}")
        semantic_contract = metadata.get("semantic_contract")
        if args.require_semantic_contract and not isinstance(semantic_contract, dict):
            errors.append("missing semantic_contract")
        elif isinstance(semantic_contract, dict):
            if not semantic_contract:
                errors.append("empty semantic_contract")
            if any(value in (None, "") for value in semantic_contract.values()):
                errors.append("semantic_contract contains empty values")
        entity_contract = str(metadata.get("entity_label_contract", "")).strip()
        if "entity" in key_fields:
            if not entity_contract or entity_contract == "not_applicable":
                errors.append("entity key requires an explicit source-label contract")
            elif entity_contract.casefold() not in question.casefold():
                errors.append("entity-label contract is not stated in the question")
        key_string_values = {
            str(row[field]).strip().casefold()
            for row in gold_rows for field in key_fields
            if field not in {"peak_month", "period", "month", "date"}
            and isinstance(row.get(field), str)
            and len(str(row[field]).strip()) >= 6
            and str(row[field]).strip().casefold() not in {"mean", "unknown", "untagged"}
        }
        leaks = sorted(value for value in key_string_values if value in question.casefold())
        if leaks:
            warnings.append(f"possible key-entity leakage: {leaks}")

        oracle_match = None
        if connection is not None and oracle:
            try:
                cursor = connection.execute(oracle)
                columns = [item[0] for item in cursor.description]
                actual = [dict(zip(columns, row)) for row in cursor.fetchall()]
                oracle_match = rows_equal(actual, gold_rows, key_fields, args.numeric_tolerance)
                if not oracle_match:
                    errors.append("stored Gold does not match Oracle execution")
            except Exception as exc:
                errors.append(f"Oracle execution failed: {exc}")
        reports.append({
            "task_id": task_id,
            "valid": not errors,
            "required_table_count": len(required_tables),
            "skill_count": len(skills),
            "supporting_skill_count": len(supporting_skills),
            "gold_row_count": len(gold_rows),
            "oracle_match": oracle_match,
            "errors": errors,
            "warnings": warnings,
        })

    if connection is not None:
        connection.close()
    summary = {
        "valid": all(row["valid"] for row in reports),
        "task_count": len(reports),
        "valid_count": sum(row["valid"] for row in reports),
        "tasks": reports,
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
