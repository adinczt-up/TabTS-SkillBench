from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from benchmark_eval.cli import parser
from benchmark_eval.data_cli import (
    inspect_source,
    load_registry,
    selected_datasets,
    verify_outputs,
)


class DataCliTests(unittest.TestCase):
    def test_repository_registry_marks_kaggle_sources_manual(self) -> None:
        root = Path(__file__).resolve().parents[1]
        registry = load_registry(root / "data_sources.yaml")

        for name in ("rel-hm", "rel-event"):
            record = registry["datasets"][name]
            self.assertEqual(record["acquisition_mode"], "user_download_required")
            self.assertTrue(record["requires_user_acceptance"])
            self.assertFalse(record["automatic_download"])
            self.assertEqual(record["redistribution_status"], "user_download_required")
            self.assertIn("Kaggle", " ".join(record["user_instructions"]))

    def test_selected_datasets_rejects_unknown_name(self) -> None:
        registry = {"datasets": {"a": {}, "b": {}}}
        self.assertEqual(selected_datasets(registry, ["b"]), ["b"])
        with self.assertRaisesRegex(ValueError, "Unknown datasets"):
            selected_datasets(registry, ["missing"])

    def test_source_preflight_requires_every_declared_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "cache" / "rel-demo" / "db" / "a.parquet"
            first.parent.mkdir(parents=True)
            first.write_bytes(b"a")
            record = {
                "source_layout": {
                    "required_globs": [
                        "**/rel-demo/db/a.parquet",
                        "**/rel-demo/db/b.parquet",
                    ]
                }
            }
            incomplete = inspect_source("rel-demo", record, root)
            self.assertFalse(incomplete["ready"])

            (first.parent / "b.parquet").write_bytes(b"b")
            complete = inspect_source("rel-demo", record, root)
            self.assertTrue(complete["ready"])

    def test_verify_outputs_checks_released_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "standardized"
            table = output / "demo" / "tables" / "table.parquet"
            table.parent.mkdir(parents=True)
            table.write_bytes(b"released-data")
            digest = hashlib.sha256(b"released-data").hexdigest()
            manifest = root / "assets.json"
            manifest.write_text(
                json.dumps(
                    [
                        {
                            "path": "skillmtts/standardized/demo/tables/table.parquet",
                            "sha256": digest,
                        }
                    ]
                ),
                encoding="utf-8",
            )

            valid = verify_outputs(output, manifest, ["demo"])
            self.assertEqual(valid["checked"], 1)
            self.assertEqual(valid["failed"], 0)

            table.write_bytes(b"changed")
            invalid = verify_outputs(output, manifest, ["demo"])
            self.assertEqual(invalid["failed"], 1)

    def test_cli_parses_data_prepare(self) -> None:
        args = parser().parse_args(
            [
                "data",
                "prepare",
                "--datasets",
                "rel-f1",
                "bdg2",
                "--source-root",
                "sources",
                "--output-root",
                "output",
            ]
        )
        self.assertEqual(args.command, "data")
        self.assertEqual(args.data_command, "prepare")
        self.assertEqual(args.datasets, ["rel-f1", "bdg2"])
        self.assertEqual(args.source_root, Path("sources"))

    def test_installed_cli_data_paths_are_relative_to_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                args = parser().parse_args(["data", "prepare"])
                expected_root = Path(directory).resolve()
                self.assertEqual(args.source_root.resolve(), expected_root / "data/sources")
                self.assertEqual(
                    args.output_root.resolve(),
                    expected_root / "data/skillmtts/standardized",
                )
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
