from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER_SCRIPTS = ROOT / "scripts" / "paper"
sys.path.insert(0, str(PAPER_SCRIPTS))

from common import (  # noqa: E402
    CONDITIONS,
    DEFAULT_OUTPUT_ROOT,
    METRICS,
    compute_ablation_results,
    gain_correlations,
    load_ablation_manifest,
    load_main_manifest,
    load_main_results,
)

FORBIDDEN_TEXT = (
    "api_key",
    "password",
    "BEGIN PRIVATE KEY",
    "raw_result_path",
)
FORBIDDEN_PATTERNS = (
    re.compile(r"/Users/", re.IGNORECASE),
    re.compile(r"[A-Z]:\\Users\\", re.IGNORECASE),
    re.compile(r"\b(?:sk[-_]|gh[op]_)[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def close(actual: float, expected: float, tolerance: float = 1e-9) -> None:
    if not math.isclose(actual, expected, abs_tol=tolerance, rel_tol=0):
        raise AssertionError(f"{actual} != {expected}")


def rounded(actual: float, expected: float, digits: int = 1) -> None:
    if f"{actual:.{digits}f}" != f"{expected:.{digits}f}":
        raise AssertionError(f"rounded value {actual:.{digits}f} != {expected:.{digits}f}")


def verify_main() -> None:
    data = load_main_results()
    manifest = load_main_manifest()
    if data["benchmark"] != "TabTS-SkillBench":
        raise AssertionError("unexpected benchmark name")
    if len(data["rows"]) != manifest["configuration_count"]:
        raise AssertionError("configuration count mismatch")
    configuration_ids: set[str] = set()
    for result, configuration in zip(
        data["rows"],
        manifest["configurations"],
        strict=True,
    ):
        if result["configuration_id"] != configuration["id"]:
            raise AssertionError("configuration id or order mismatch")
        if result["harness"] != configuration["harness"]:
            raise AssertionError("configuration harness mismatch")
        if result["model"] != configuration["result_model"]:
            raise AssertionError("configuration model label mismatch")
        configuration_ids.add(result["configuration_id"])
    if len(configuration_ids) != manifest["configuration_count"]:
        raise AssertionError("duplicate configuration id")
    if tuple(data["condition_order"]) != CONDITIONS:
        raise AssertionError("condition order mismatch")
    expected_executions = (
        manifest["task_count"]
        * manifest["configuration_count"]
        * len(manifest["conditions"])
        * manifest["repeats"]
    )
    if expected_executions != manifest["execution_count"]:
        raise AssertionError("execution count mismatch")

    for row in data["rows"]:
        baseline = row["outcome"]["avg_at_3"]["baseline"]
        for condition in ("self_route", "annotated_preload"):
            close(
                row["outcome"]["delta_percentage_points"][condition],
                row["outcome"]["avg_at_3"][condition] - baseline,
            )
        for condition in CONDITIONS:
            close(
                row["cost"]["calls_per_success"][condition],
                row["cost"]["calls"][condition] / (row["outcome"]["avg_at_3"][condition] / 100),
            )

    macro = data["macro_average"]
    for group, metric, _ in METRICS:
        for condition in CONDITIONS:
            values = [
                row[group][metric][condition]
                for row in data["rows"]
                if row[group][metric][condition] is not None
            ]
            expected = macro[group][metric][condition]
            if not values:
                if expected is not None:
                    raise AssertionError(f"expected null macro for {metric}.{condition}")
            else:
                close(expected, statistics.mean(values))

    claims = manifest["paper_claims"]
    for condition, expected in claims["macro_avg_at_3"].items():
        rounded(macro["outcome"]["avg_at_3"][condition], expected)
    for condition, expected in claims["macro_calls"].items():
        rounded(macro["cost"]["calls"][condition], expected)
    best = max(
        row["outcome"]["avg_at_3"][condition] for row in data["rows"] for condition in CONDITIONS
    )
    rounded(best, claims["best_avg_at_3"])
    baselines = [row["outcome"]["avg_at_3"]["baseline"] for row in data["rows"]]
    self_route = [row["outcome"]["avg_at_3"]["self_route"] for row in data["rows"]]
    rounded(
        statistics.pstdev(baselines),
        claims["cross_configuration_std"]["baseline"],
    )
    rounded(
        statistics.pstdev(self_route),
        claims["cross_configuration_std"]["self_route"],
    )
    correlations = gain_correlations(data)
    for values in correlations.values():
        rounded(values["r"], claims["pearson_gain_vs_baseline"]["r"], 2)
        rounded(values["p"], claims["pearson_gain_vs_baseline"]["p"], 3)
    temporal = claims["temporal_macro"]
    rounded(
        macro["temporal_analysis"]["tea"]["baseline"],
        temporal["tea_baseline"],
    )
    rounded(
        macro["temporal_analysis"]["tea"]["annotated_preload"],
        temporal["tea_preload"],
    )
    rounded(
        macro["temporal_analysis"]["td_f1"]["baseline"],
        temporal["td_f1_baseline"],
    )
    rounded(
        macro["temporal_analysis"]["td_f1"]["annotated_preload"],
        temporal["td_f1_preload"],
    )
    rounded(
        macro["temporal_analysis"]["tcc"]["baseline"],
        temporal["tcc_baseline"],
    )
    rounded(
        macro["temporal_analysis"]["tcc"]["annotated_preload"],
        temporal["tcc_preload"],
    )


def verify_csv_json_equivalence() -> None:
    data = load_main_results()
    path = ROOT / "artifacts" / "paper" / "results" / "main_aggregate_results.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    if len(csv_rows) != len(data["rows"]) + 1:
        raise AssertionError("main aggregate CSV row count mismatch")

    def parse_values(value: str) -> list[float | None]:
        return [None if part == "—" else float(part) for part in value.split("/")]

    metric_columns = {
        metric: f"{label} (B/S/A)" for _, metric, label in METRICS
    }
    for json_row, csv_row in zip(data["rows"], csv_rows[:-1], strict=True):
        if (csv_row["Harness"], csv_row["Model"]) != (
            json_row["harness"],
            json_row["model"],
        ):
            raise AssertionError("main aggregate CSV labels or order mismatch")
        for group, metric, _ in METRICS:
            observed = parse_values(csv_row[metric_columns[metric]])
            expected = [json_row[group][metric][condition] for condition in CONDITIONS]
            if len(observed) != len(expected):
                raise AssertionError(f"CSV condition count mismatch for {metric}")
            for actual, target in zip(observed, expected, strict=True):
                if actual is None or target is None:
                    if actual is not target:
                        raise AssertionError(f"CSV null mismatch for {metric}")
                else:
                    close(actual, target)
        observed_delta = parse_values(csv_row["Δ (S/A)"])
        expected_delta = [
            json_row["outcome"]["delta_percentage_points"][condition]
            for condition in ("self_route", "annotated_preload")
        ]
        for actual, target in zip(observed_delta, expected_delta, strict=True):
            close(float(actual), target)

    macro_row = csv_rows[-1]
    if (macro_row["Harness"], macro_row["Model"]) != ("Macro Average", ""):
        raise AssertionError("main aggregate CSV macro row mismatch")
    macro = data["macro_average"]
    for group, metric, _ in METRICS:
        observed = parse_values(macro_row[metric_columns[metric]])
        expected = [macro[group][metric][condition] for condition in CONDITIONS]
        for actual, target in zip(observed, expected, strict=True):
            if actual is None or target is None:
                if actual is not target:
                    raise AssertionError(f"CSV macro null mismatch for {metric}")
            else:
                close(actual, target)


def verify_ablations() -> None:
    manifest = load_ablation_manifest()
    task_manifest = json.loads(
        (ROOT / "benchmark" / "manifests" / "task_set_251.json").read_text()
    )
    expected_task_ids = set(task_manifest["task_ids"])
    if len(expected_task_ids) != manifest["task_count"]:
        raise AssertionError("final task manifest count mismatch")
    result_path = ROOT / "artifacts" / "paper" / "results" / "ablation_paired_outcomes.csv"
    with result_path.open(encoding="utf-8", newline="") as stream:
        source_rows = list(csv.DictReader(stream))
    rows = compute_ablation_results()
    if len(rows) != len(manifest["ablations"]):
        raise AssertionError("ablation count mismatch")
    by_id = {row["ablation_id"]: row for row in rows}
    expected_ablation_ids = {ablation["id"] for ablation in manifest["ablations"]}
    if {row["ablation_id"] for row in source_rows} != expected_ablation_ids:
        raise AssertionError("unexpected ablation id")
    for order, ablation in enumerate(manifest["ablations"], start=1):
        inputs = [row for row in source_rows if row["ablation_id"] == ablation["id"]]
        task_ids = [row["task_id"] for row in inputs]
        if len(task_ids) != len(set(task_ids)):
            raise AssertionError(f"duplicate task id in {ablation['id']}")
        if set(task_ids) != expected_task_ids:
            raise AssertionError(f"task set mismatch in {ablation['id']}")
        for input_row in inputs:
            expected_metadata = {
                "ablation_label": ablation["label"],
                "table_order": str(order),
                "reference_condition": ablation["reference_condition"],
                "bootstrap_seed": str(ablation["bootstrap_seed"]),
            }
            for field, expected_value in expected_metadata.items():
                if input_row[field] != expected_value:
                    raise AssertionError(f"{field} mismatch in {ablation['id']}")
            for field in ("reference_strict_success", "ablated_strict_success"):
                if input_row[field] not in {"0", "1"}:
                    raise AssertionError(f"non-binary {field} in {ablation['id']}")
        row = by_id[ablation["id"]]
        if row["paired_tasks"] != manifest["task_count"]:
            raise AssertionError("paired task count mismatch")
        expected = ablation["paper"]
        rounded(row["reference_sr"], expected["reference_sr"])
        rounded(row["ablated_sr"], expected["ablated_sr"])
        rounded(row["sr_loss"], expected["loss"])
        rounded(row["ci_low"], expected["ci_low"])
        rounded(row["ci_high"], expected["ci_high"])


def verify_outputs() -> None:
    required = (
        "table2.csv",
        "table2.tex",
        "table3.csv",
        "table3.tex",
        "figure4.svg",
        "figure5.svg",
        "figure7.svg",
        "figure8.svg",
        "paper_summary.json",
    )
    for name in required:
        path = DEFAULT_OUTPUT_ROOT / name
        if not path.is_file() or path.stat().st_size == 0:
            raise AssertionError(f"missing reproduced output: {name}")
        if path.suffix == ".svg":
            ET.parse(path)
    summary = json.loads((DEFAULT_OUTPUT_ROOT / "paper_summary.json").read_text())
    if summary["execution_count"] != 20331:
        raise AssertionError("summary execution count mismatch")
    with (DEFAULT_OUTPUT_ROOT / "table2.csv").open(encoding="utf-8", newline="") as stream:
        table2 = list(csv.DictReader(stream))
    macro = table2[-1]
    expected_macro = {
        "Avg@3": "38.4/57.1/56.5",
        "Δ": "—/+18.6/+18.1",
        "DAR": "60.6/58.8/71.1",
        "Calls": "8.81/20.25/22.43",
        "C/S": "25.4/36.9/40.2",
    }
    for field, expected in expected_macro.items():
        if macro[field] != expected:
            raise AssertionError(f"Table 2 macro {field}: {macro[field]} != {expected}")


def verify_sanitization() -> None:
    roots = (
        ROOT / "artifacts" / "paper",
        ROOT / "scripts" / "paper",
    )
    suffixes = {".json", ".csv", ".md", ".py", ".tex", ".svg"}
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            text = path.read_text(encoding="utf-8-sig")
            for forbidden in FORBIDDEN_TEXT:
                if forbidden.casefold() in text.casefold():
                    raise AssertionError(
                        f"forbidden text {forbidden!r} in {path.relative_to(ROOT)}"
                    )
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.search(text):
                    raise AssertionError(
                        f"forbidden pattern {pattern.pattern!r} in {path.relative_to(ROOT)}"
                    )


def verify_checksums() -> None:
    paper_root = ROOT / "artifacts" / "paper"
    checksum_path = paper_root / "SHA256SUMS"
    lines = checksum_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise AssertionError("empty SHA256SUMS")
    expected_paths = {
        path.relative_to(paper_root).as_posix()
        for path in paper_root.rglob("*")
        if path.is_file() and path != checksum_path
    }
    observed_paths: set[str] = set()
    for line_value in lines:
        digest, relative = line_value.split("  ", 1)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise AssertionError(f"invalid checksum: {digest}")
        if relative in observed_paths:
            raise AssertionError(f"duplicate checksum entry: {relative}")
        observed_paths.add(relative)
        path = paper_root / relative
        if not path.is_file() or not path.resolve().is_relative_to(paper_root.resolve()):
            raise AssertionError(f"invalid checksum path: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise AssertionError(f"checksum mismatch: {relative}")
    if observed_paths != expected_paths:
        raise AssertionError("checksum inventory mismatch")


def main() -> None:
    checks = (
        ("main aggregate results", verify_main),
        ("CSV/JSON equivalence", verify_csv_json_equivalence),
        ("component ablations", verify_ablations),
        ("reproduced outputs", verify_outputs),
        ("sanitization", verify_sanitization),
        ("checksums", verify_checksums),
    )
    for label, check in checks:
        check()
        print(f"PASS {label}")
    print("PASS paper result reproduction")


if __name__ == "__main__":
    main()
