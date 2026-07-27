from __future__ import annotations

import json
import re
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from jsonschema import Draft202012Validator

from benchmark_eval.metrics import score_trace
from benchmark_eval.schema import RunLocator, TraceRecord
from benchmark_eval.utils import read_jsonl

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = ROOT / "docs/normalized-traces/v1"


def nested_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [item for key, child in value.items() for item in [str(key), *nested_strings(child)]]
    if isinstance(value, list):
        return [item for child in value for item in nested_strings(child)]
    return [value] if isinstance(value, str) else []


def nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {
            str(key).casefold()
            for key, child in value.items()
        } | {key for child in value.values() for key in nested_keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in nested_keys(child)}
    return set()


class NormalizedTraceExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(
            (EXAMPLE_ROOT / "normalized-trace.schema.json").read_text(encoding="utf-8")
        )
        cls.traces = read_jsonl(EXAMPLE_ROOT / "synthetic-normalized-traces.jsonl")
        cls.manifest = json.loads(
            (EXAMPLE_ROOT / "fixture-manifest.json").read_text(encoding="utf-8")
        )

    def test_schema_matches_trace_record_fields(self) -> None:
        record = TraceRecord(
            locator=RunLocator("t", "f", "m", "c", 1, "r", ""),
            status="completed",
            failure_reason="",
            final_answer="[]",
            answer_source="test",
        )
        expected_fields = set(record.to_dict())

        self.assertEqual(set(self.schema["properties"]), expected_fields)
        self.assertEqual(set(self.schema["required"]), expected_fields)
        self.assertFalse(self.schema["additionalProperties"])
        Draft202012Validator.check_schema(self.schema)

    def test_exactly_three_explicitly_synthetic_cases(self) -> None:
        self.assertTrue(self.manifest["synthetic"])
        self.assertEqual(len(self.traces), 3)
        self.assertEqual(len(self.manifest["cases"]), 3)
        self.assertEqual(
            {row["framework"] for row in self.traces},
            {"Nanobot", "Codex", "Claude Code"},
        )
        self.assertEqual(
            {case["outcome_class"] for case in self.manifest["cases"]},
            {"success", "process_operation_error", "answer_error"},
        )
        self.assertTrue(all(case["synthetic"] for case in self.manifest["cases"]))
        self.assertTrue(all(row["run_id"].startswith("synthetic-") for row in self.traces))
        self.assertTrue(all(row["model"] == "synthetic-contract-model" for row in self.traces))

    def test_examples_validate_round_trip_and_score(self) -> None:
        validator = Draft202012Validator(self.schema)
        cases = {case["task_id"]: case for case in self.manifest["cases"]}
        contract = self.manifest["scoring_contract"]

        for row in self.traces:
            with self.subTest(task_id=row["task_id"]):
                validator.validate(row)
                trace = TraceRecord.from_dict(row)
                self.assertEqual(trace.to_dict(), row)
                metrics = score_trace(trace, {"task_id": row["task_id"]}, contract)
                for name, expected in cases[row["task_id"]]["expected_metrics"].items():
                    self.assertEqual(metrics[name], expected, name)

    def test_examples_keep_public_privacy_boundary(self) -> None:
        self.assertTrue(all(not row["commands"] for row in self.traces))
        self.assertTrue(all(not row["run_root"] for row in self.traces))
        self.assertTrue(all(not row["raw_result_path"] for row in self.traces))
        self.assertTrue(
            all(
                row[field] is None
                for row in self.traces
                for field in (
                    "prompt_tokens",
                    "completion_tokens",
                    "cached_tokens",
                    "duration_seconds",
                )
            )
        )
        strings = nested_strings({"traces": self.traces, "manifest": self.manifest})
        self.assertTrue(
            all(
                not PurePosixPath(value).is_absolute() and not PureWindowsPath(value).is_absolute()
                for value in strings
            )
        )
        self.assertTrue(
            all(not value.casefold().startswith(("http://", "https://")) for value in strings)
        )
        forbidden_keys = {
            "api_key",
            "credential",
            "dataset_rows",
            "endpoint",
            "password",
            "prompt",
            "raw_response",
            "reasoning",
            "request_id",
            "system_prompt",
        }
        self.assertFalse(
            forbidden_keys.intersection(
                nested_keys({"traces": self.traces, "manifest": self.manifest})
            )
        )
        sensitive_patterns = (
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
            r"\bsk-[A-Za-z0-9_-]{16,}\b",
            r"\bAKIA[0-9A-Z]{16}\b",
            r"\bgh[oprsu]_[A-Za-z0-9]{20,}\b",
        )
        self.assertTrue(
            all(not re.search(pattern, value) for pattern in sensitive_patterns for value in strings)
        )
        self.assertTrue(
            all(not call.get("id") for row in self.traces for call in row["tool_calls"])
        )


if __name__ == "__main__":
    unittest.main()
