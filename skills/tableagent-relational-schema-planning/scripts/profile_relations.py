#!/usr/bin/env python3
"""Profile local tables and propose shared-column relation candidates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


def read_tables(path: Path, max_rows: int) -> list[tuple[str, pd.DataFrame]]:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        sep = "\t" if suffix == ".tsv" else ","
        return [(path.name, pd.read_csv(path, sep=sep, nrows=max_rows, low_memory=False))]
    if suffix in {".xlsx", ".xls"}:
        book = pd.ExcelFile(path)
        return [
            (f"{path.name}::{sheet}", pd.read_excel(path, sheet_name=sheet, nrows=max_rows))
            for sheet in book.sheet_names
        ]
    if suffix in {".parquet", ".pq"}:
        parquet = pq.ParquetFile(path)
        batch = next(parquet.iter_batches(batch_size=max_rows), None)
        frame = batch.to_pandas() if batch is not None else pd.DataFrame()
        return [(path.name, frame)]
    return []


def norm_values(series: pd.Series, limit: int = 5000) -> set[str]:
    values = series.dropna().astype(str).str.strip()
    return set(values.head(limit))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-rows", type=int, default=2000)
    args = parser.parse_args()

    tables: dict[str, pd.DataFrame] = {}
    for path in sorted(args.data_dir.rglob("*")):
        if path.is_file():
            for name, frame in read_tables(path, args.max_rows):
                tables[str(path.relative_to(args.data_dir)) + ("::" + name.split("::", 1)[1] if "::" in name else "")] = frame

    profiles = []
    for name, frame in tables.items():
        columns = []
        for column in frame.columns:
            series = frame[column]
            non_null = int(series.notna().sum())
            distinct = int(series.nunique(dropna=True))
            columns.append({
                "name": str(column),
                "dtype": str(series.dtype),
                "non_null": non_null,
                "distinct": distinct,
                "unique_non_null": bool(non_null > 0 and distinct == non_null),
            })
        profiles.append({"table": name, "sampled_rows": int(len(frame)), "columns": columns})

    edges = []
    names = sorted(tables)
    for index, left_name in enumerate(names):
        left = tables[left_name]
        for right_name in names[index + 1:]:
            right = tables[right_name]
            for column in sorted(set(map(str, left.columns)) & set(map(str, right.columns))):
                left_values = norm_values(left[column])
                right_values = norm_values(right[column])
                if not left_values or not right_values:
                    overlap = 0.0
                else:
                    overlap = len(left_values & right_values) / min(len(left_values), len(right_values))
                edges.append({
                    "left": left_name,
                    "right": right_name,
                    "shared_column": column,
                    "sample_overlap": round(overlap, 6),
                    "left_unique": bool(left[column].notna().sum() and left[column].nunique(dropna=True) == left[column].notna().sum()),
                    "right_unique": bool(right[column].notna().sum() and right[column].nunique(dropna=True) == right[column].notna().sum()),
                })

    result = {"data_dir": str(args.data_dir), "tables": profiles, "candidate_edges": edges}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
