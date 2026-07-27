from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from benchmark_eval.utils import write_json

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "data_sources.yaml"
DEFAULT_SOURCE_ROOT = Path("data") / "sources"
DEFAULT_OUTPUT_ROOT = Path("data") / "skillmtts" / "standardized"
DEFAULT_ASSET_MANIFEST = REPO_ROOT / "benchmark" / "manifests" / "assets_sha256.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def load_registry(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    datasets = payload.get("datasets")
    if not isinstance(datasets, dict) or not datasets:
        raise ValueError(f"Data source registry has no datasets: {path}")
    return payload


def selected_datasets(
    registry: dict[str, Any],
    requested: list[str] | None,
) -> list[str]:
    available = list((registry.get("datasets") or {}).keys())
    if not requested or "all" in requested:
        return available
    missing = sorted(set(requested) - set(available))
    if missing:
        raise ValueError(f"Unknown datasets: {', '.join(missing)}")
    return list(dict.fromkeys(requested))


def inspect_source(
    dataset: str,
    record: dict[str, Any],
    source_root: Path,
) -> dict[str, Any]:
    layout = record.get("source_layout") or {}
    required_paths = [str(value) for value in layout.get("required_paths") or []]
    required_globs = [str(value) for value in layout.get("required_globs") or []]
    def evidence(paths: list[Path]) -> list[dict[str, Any]]:
        return [
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in paths
            if path.is_file()
        ]

    path_checks = []
    for value in required_paths:
        matches = [source_root / value] if (source_root / value).is_file() else []
        path_checks.append(
            {
                "pattern": value,
                "kind": "path",
                "matches": [str(path) for path in matches],
                "evidence": evidence(matches),
            }
        )
    glob_checks = []
    for value in required_globs:
        matches = [path for path in sorted(source_root.glob(value)) if path.is_file()]
        glob_checks.append(
            {
                "pattern": value,
                "kind": "glob",
                "matches": [str(path) for path in matches],
                "evidence": evidence(matches),
            }
        )
    checks = path_checks + glob_checks
    return {
        "dataset": dataset,
        "ready": bool(checks) and all(check["matches"] for check in checks),
        "checks": checks,
    }


def print_dataset_guide(dataset: str, record: dict[str, Any]) -> None:
    print(f"\n[{dataset}]")
    print(f"  license: {record.get('upstream_license', 'unknown')}")
    print(f"  acquisition: {record.get('acquisition_mode', 'unspecified')}")
    print(f"  redistribution: {record.get('redistribution_status', 'unspecified')}")
    if record.get("terms_url"):
        print(f"  terms: {record['terms_url']}")
    if record.get("upstream_url"):
        print(f"  upstream: {record['upstream_url']}")
    for index, instruction in enumerate(record.get("user_instructions") or [], start=1):
        print(f"  {index}. {instruction}")


def guide_command(args: argparse.Namespace) -> int:
    registry = load_registry(resolved(args.registry))
    names = selected_datasets(registry, args.datasets)
    records = registry["datasets"]
    print(
        "TabTS-SkillBench never accepts third-party terms on a user's behalf and "
        "never downloads sources marked user_download_required."
    )
    for name in names:
        print_dataset_guide(name, records[name])
    return 0


def _load_standardizer():
    candidates = [
        REPO_ROOT / "tools" / "standardize_skillmtts_datasets.py",
        Path(__file__).resolve().with_name("_standardize_skillmtts_datasets.py"),
    ]
    script = next((path for path in candidates if path.is_file()), None)
    if script is None:
        raise FileNotFoundError(
            "The data standardizer is not installed. Use a source checkout or reinstall "
            "tabts-skillbench with its packaged data standardizer."
        )
    spec = importlib.util.spec_from_file_location("tabts_skillbench_standardizer", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load data standardizer: {script}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:
        if exc.name in {"duckdb", "pyarrow"}:
            raise RuntimeError(
                'Data preparation dependencies are missing. Install with pip install -e ".[benchmark]".'
            ) from exc
        raise
    return module.Standardizer


def load_asset_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Asset manifest must be a JSON array: {path}")
    return payload


def verify_outputs(
    output_root: Path,
    asset_manifest: Path,
    datasets: list[str] | None = None,
) -> dict[str, Any]:
    selected = set(datasets or [])
    rows = []
    for item in load_asset_manifest(asset_manifest):
        logical_path = Path(str(item["path"]))
        parts = logical_path.parts
        try:
            marker = parts.index("standardized")
        except ValueError as exc:
            raise ValueError(f"Unexpected asset path: {logical_path}") from exc
        relative = Path(*parts[marker + 1 :])
        dataset = relative.parts[0]
        if selected and dataset not in selected:
            continue
        path = output_root / relative
        actual = sha256_file(path) if path.is_file() else None
        expected = str(item["sha256"])
        rows.append(
            {
                "dataset": dataset,
                "path": str(path),
                "expected_sha256": expected,
                "actual_sha256": actual,
                "passed": actual == expected,
            }
        )
    return {
        "checked": len(rows),
        "passed": sum(bool(row["passed"]) for row in rows),
        "failed": sum(not row["passed"] for row in rows),
        "assets": rows,
    }


def verify_command(args: argparse.Namespace) -> int:
    registry = load_registry(resolved(args.registry))
    names = selected_datasets(registry, args.datasets)
    report = verify_outputs(
        resolved(args.output_root),
        resolved(args.asset_manifest),
        names,
    )
    print(
        f"Verified assets={report['checked']} passed={report['passed']} "
        f"failed={report['failed']}"
    )
    for row in report["assets"]:
        if not row["passed"]:
            status = "missing" if row["actual_sha256"] is None else "hash mismatch"
            print(f"  [{status}] {row['path']}")
    return 1 if report["failed"] else 0


def prepare_command(args: argparse.Namespace) -> int:
    registry_path = resolved(args.registry)
    registry = load_registry(registry_path)
    names = selected_datasets(registry, args.datasets)
    records = registry["datasets"]
    source_root = resolved(args.source_root)
    output_root = resolved(args.output_root)
    inspections = [inspect_source(name, records[name], source_root) for name in names]
    missing = [item for item in inspections if not item["ready"]]
    if missing:
        print(
            "Required upstream inputs are missing. No download or terms acceptance "
            "was attempted."
        )
        for item in missing:
            print_dataset_guide(item["dataset"], records[item["dataset"]])
            for check in item["checks"]:
                if not check["matches"]:
                    print(f"  missing {check['kind']}: {check['pattern']}")
        return 2

    standardizer_class = _load_standardizer()
    standardizer = standardizer_class(source_root, output_root, args.force)
    try:
        standardizer.run(names)
    finally:
        standardizer.close()

    verification = verify_outputs(
        output_root,
        resolved(args.asset_manifest),
        names,
    )
    report = {
        "schema_version": 1,
        "prepared_at_utc": datetime.now(UTC).isoformat(),
        "registry": str(registry_path),
        "registry_sha256": sha256_file(registry_path),
        "source_root": str(source_root),
        "output_root": str(output_root),
        "datasets": names,
        "source_records": {name: records[name] for name in names},
        "source_preflight": inspections,
        "output_verification": verification,
    }
    report_path = output_root / "preparation_report.json"
    write_json(report_path, report)
    print(
        f"Prepared datasets={len(names)} assets={verification['checked']} "
        f"verified={verification['passed']} failed={verification['failed']}"
    )
    print(f"Preparation report: {report_path}")
    return 1 if verification["failed"] else 0


def add_data_parser(subparsers: Any) -> None:
    data = subparsers.add_parser(
        "data",
        help="Guide, prepare, and verify benchmark data without accepting source terms.",
    )
    actions = data.add_subparsers(dest="data_command", required=True)

    def add_registry_and_datasets(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
        parser.add_argument("--datasets", nargs="+", default=["all"])

    guide = actions.add_parser("guide", help="Show source-specific legal download guidance.")
    add_registry_and_datasets(guide)

    prepare = actions.add_parser(
        "prepare",
        help="Standardize user-provided upstream data and verify released hashes.",
    )
    add_registry_and_datasets(prepare)
    prepare.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    prepare.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    prepare.add_argument("--asset-manifest", type=Path, default=DEFAULT_ASSET_MANIFEST)
    prepare.add_argument("--force", action="store_true")

    verify = actions.add_parser("verify", help="Verify standardized files against SHA-256.")
    add_registry_and_datasets(verify)
    verify.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    verify.add_argument("--asset-manifest", type=Path, default=DEFAULT_ASSET_MANIFEST)


def data_command(args: argparse.Namespace) -> int:
    return {
        "guide": guide_command,
        "prepare": prepare_command,
        "verify": verify_command,
    }[args.data_command](args)
