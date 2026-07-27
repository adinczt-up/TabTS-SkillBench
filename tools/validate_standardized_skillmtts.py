from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq


def sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("\\", "/").replace("'", "''") + "'"


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def resolve_glob(dataset_root: Path, table: dict[str, Any]) -> str:
    logical = table["path"]
    return str(dataset_root / logical)


def table_expression(dataset_root: Path, table: dict[str, Any]) -> str:
    return f"read_parquet({sql_string(resolve_glob(dataset_root, table))}, hive_partitioning=true)"


def validate(root: Path) -> dict[str, Any]:
    root = root.resolve()
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    con = duckdb.connect()
    con.execute("SET threads = 4")
    con.execute("SET memory_limit = '8GB'")
    report: dict[str, Any] = {"root": str(root), "datasets": [], "passed": True, "warnings": []}
    try:
        manifests: dict[str, dict[str, Any]] = {}
        roots: dict[str, Path] = {}
        for item in catalog["datasets"]:
            dataset_id = item["dataset_id"]
            dataset_root = root / dataset_id
            manifests[dataset_id] = json.loads((dataset_root / "manifest.json").read_text(encoding="utf-8"))
            roots[dataset_id] = dataset_root

        for dataset_id, manifest in manifests.items():
            dataset_root = roots[dataset_id]
            dataset_report: dict[str, Any] = {
                "dataset_id": dataset_id,
                "passed": bool(manifest["validation"]["passed"]),
                "tables": [],
                "foreign_keys": [],
            }
            for table_name, table in manifest["tables"].items():
                expr = table_expression(dataset_root, table)
                files = list(dataset_root.glob(table["path"]))
                if not files and "*" in table["path"]:
                    files = list(dataset_root.glob(table["path"]))
                actual_rows = sum(pq.ParquetFile(file).metadata.num_rows for file in files)
                actual_columns = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {expr}").fetchall()]
                table_report: dict[str, Any] = {
                    "table": table_name,
                    "files": len(files),
                    "rows": actual_rows,
                    "row_count_matches_manifest": actual_rows == table["rows"],
                    "columns_match_manifest": actual_columns == table["columns"],
                    "primary_key": table.get("primary_key", []),
                }
                if table.get("time_column"):
                    time_column = table["time_column"]
                    dtype = next(row[1] for row in con.execute(f"DESCRIBE SELECT {quote_ident(time_column)} FROM {expr}").fetchall())
                    table_report["time_type"] = dtype
                    table_report["time_type_valid"] = "TIMESTAMP" in dtype.upper() or "DATE" in dtype.upper()
                primary_key = table.get("primary_key", [])
                if primary_key:
                    null_condition = " OR ".join(f"{quote_ident(column)} IS NULL" for column in primary_key)
                    key_expr = ", ".join(quote_ident(column) for column in primary_key)
                    total, nulls, distinct_keys = con.execute(
                        f"SELECT COUNT(*), COUNT(*) FILTER (WHERE {null_condition}), "
                        f"COUNT(DISTINCT ({key_expr})) FROM {expr}"
                    ).fetchone()
                    table_report["primary_key_nulls"] = nulls
                    table_report["primary_key_duplicates"] = total - distinct_keys
                    table_report["primary_key_valid"] = nulls == 0 and total == distinct_keys
                required_checks = [
                    table_report["row_count_matches_manifest"],
                    table_report["columns_match_manifest"],
                    table_report.get("time_type_valid", True),
                    table_report.get("primary_key_valid", True),
                ]
                table_report["passed"] = all(required_checks)
                dataset_report["passed"] = dataset_report["passed"] and table_report["passed"]
                dataset_report["tables"].append(table_report)

            for source_table, table in manifest["tables"].items():
                source_expr = table_expression(dataset_root, table)
                for source_column, targets_spec in table.get("foreign_keys", {}).items():
                    targets = targets_spec.split("|")
                    target_queries = []
                    for target in targets:
                        target_table, target_column = target.split(".", 1)
                        target_meta = manifest["tables"][target_table]
                        target_expr = table_expression(dataset_root, target_meta)
                        target_queries.append(
                            f"SELECT DISTINCT CAST({quote_ident(target_column)} AS VARCHAR) AS key FROM {target_expr} WHERE {quote_ident(target_column)} IS NOT NULL"
                        )
                    target_union = " UNION ".join(target_queries)
                    source_key = quote_ident(source_column)
                    distinct_source, unmatched = con.execute(
                        f"WITH s AS (SELECT DISTINCT CAST({source_key} AS VARCHAR) AS key FROM {source_expr} WHERE {source_key} IS NOT NULL), "
                        f"t AS ({target_union}) SELECT COUNT(*), COUNT(*) FILTER (WHERE t.key IS NULL) FROM s LEFT JOIN t USING (key)"
                    ).fetchone()
                    coverage = 1.0 if distinct_source == 0 else (distinct_source - unmatched) / distinct_source
                    relation = {
                        "source": f"{source_table}.{source_column}",
                        "target": targets_spec,
                        "distinct_source_keys": distinct_source,
                        "unmatched_keys": unmatched,
                        "coverage": round(coverage, 8),
                    }
                    dataset_report["foreign_keys"].append(relation)
                    if unmatched:
                        report["warnings"].append({"dataset_id": dataset_id, **relation})
            report["datasets"].append(dataset_report)
            report["passed"] = report["passed"] and dataset_report["passed"]
    finally:
        con.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Independently validate standardized SkillMTTS tables.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = validate(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"passed={report['passed']} datasets={len(report['datasets'])} warnings={len(report['warnings'])}")
    for dataset in report["datasets"]:
        print(f"{dataset['dataset_id']}: passed={dataset['passed']} tables={len(dataset['tables'])} foreign_keys={len(dataset['foreign_keys'])}")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
