from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark_eval.adapters.nanobot import NanobotAdapter
from benchmark_eval.cli import parser
from benchmark_eval.config import load_experiment, write_runner_tasks
from benchmark_eval.contracts import build_contract
from benchmark_eval.metric_audit import empirical_metric_health, static_metric_applicability
from benchmark_eval.metrics import (
    _relational_metrics,
    _temporal_metrics,
    prf,
    score_answer,
    score_trace,
)
from benchmark_eval.report import aggregate_group
from benchmark_eval.schema import RunLocator, TraceRecord
from benchmark_eval.statistics import exact_mcnemar_p, pair_conditions
from benchmark_eval.trace import (
    _temporal_granularities,
    _temporal_operation_sequence,
    _temporal_parameters,
)
from isolated_benchmark_runner.run_isolated_task import (
    build_config,
    build_final_answer_repair_prompt,
    detect_infrastructure_error,
    final_answer_issue,
    resolve_allowed_and_required_skills,
    stage_task_assets,
)
from tools.build_skill_ablation_views import build_views


class BenchmarkEvalTests(unittest.TestCase):
    def test_custom_condition_uses_declared_base_condition(self) -> None:
        self.assertEqual(
            NanobotAdapter._condition_flags(
                "oracle_no_validator",
                {"base_condition": "oracle_skill"},
            ),
            ("on", "required", "preload"),
        )

    def test_skill_exclusion_filters_visible_read_and_execution_sets(self) -> None:
        task = {
            "skills": ["table-plan", "temporal-analysis"],
            "required_execution_skills": ["temporal-analysis"],
        }
        allowed, declared, required = resolve_allowed_and_required_skills(
            task=task,
            skill_mode="on",
            skills_root=Path("."),
            skill_experiment_mode="required",
            excluded_skills=["table-plan"],
        )
        self.assertEqual(allowed, ["temporal-analysis"])
        self.assertEqual(declared, ["temporal-analysis"])
        self.assertEqual(required, ["temporal-analysis"])

    def test_skill_ablation_views_are_deterministic_and_component_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "skills" / "demo-skill"
            scripts = source / "scripts"
            scripts.mkdir(parents=True)
            (source / "SKILL.md").write_text(
                "---\n"
                "name: demo-skill\n"
                "description: Use for demos. Requires data. Do not use for lookups.\n"
                "---\n\n"
                "# Demo\n\n"
                "## Trigger Boundary\n"
                "- Trigger for demos.\n"
                "- Do not trigger for lookups.\n\n"
                "## Mechanical Procedure\n"
                "1. Compute a result.\n\n"
                "## Structured Execution\n"
                "```bash\n"
                "python skills/demo-skill/scripts/execute_analysis.py\n"
                "python skills/demo-skill/scripts/validate_result.py\n"
                "```\n",
                encoding="utf-8",
            )
            (scripts / "execute_analysis.py").write_text("print('ok')\n", encoding="utf-8")
            (scripts / "validate_result.py").write_text("print('ok')\n", encoding="utf-8")
            categories = root / "categories.yaml"
            categories.write_text(
                "categories:\n  temporal:\n    - demo-skill\n",
                encoding="utf-8",
            )
            output = root / "views"
            first = build_views(root / "skills", output, categories)
            first_manifest = (output / "manifest.json").read_text(encoding="utf-8")
            build_views(root / "skills", output, categories)
            second_manifest = (output / "manifest.json").read_text(encoding="utf-8")

            self.assertEqual(first["skill_count"], 1)
            self.assertEqual(first_manifest, second_manifest)
            self.assertFalse((output / "description_only" / "demo-skill" / "scripts").exists())
            self.assertFalse((output / "text_only" / "demo-skill" / "scripts").exists())
            self.assertTrue(
                output.joinpath(
                    "no_validator", "demo-skill", "scripts", "execute_analysis.py"
                ).is_file()
            )
            self.assertFalse(
                output.joinpath(
                    "no_validator", "demo-skill", "scripts", "validate_result.py"
                ).exists()
            )
            no_validator_md = output.joinpath(
                "no_validator", "demo-skill", "SKILL.md"
            ).read_text(encoding="utf-8")
            self.assertIn("execute_analysis.py", no_validator_md)
            self.assertNotIn("validate_result.py", no_validator_md)
            no_guard_md = output.joinpath(
                "no_route_guardrails", "demo-skill", "SKILL.md"
            ).read_text(encoding="utf-8")
            self.assertNotIn("Do not use", no_guard_md)
            self.assertNotIn("Do not trigger", no_guard_md)

    def test_pipeline_cli_exposes_concurrency_and_submission_delay(self) -> None:
        args = parser().parse_args(
            [
                "pipeline",
                "--experiment",
                "experiment.yaml",
                "--models-config",
                "models.yaml",
                "--concurrency",
                "12",
                "--submission-delay",
                "0.75",
            ]
        )
        self.assertEqual(args.concurrency, 12)
        self.assertEqual(args.submission_delay, 0.75)

    def test_nanobot_adapter_does_not_retry_output_contract_failure(self) -> None:
        payload = json.dumps(
            {
                "status": "failed",
                "failure_reason": (
                    "final_answer_contract_error:missing_or_invalid_json_array"
                ),
            }
        )
        locator = RunLocator("t", "nanobot", "m", "oracle_skill", 1, "r", "run")
        with patch("pathlib.Path.read_text", return_value=payload):
            retryable = NanobotAdapter._retryable_tasks({"t": locator}, ["t"])
        self.assertEqual(retryable, [])

    def test_nanobot_adapter_retries_infrastructure_failure(self) -> None:
        payload = json.dumps(
            {
                "status": "infrastructure_error",
                "failure_reason": "http_429",
            }
        )
        locator = RunLocator("t", "nanobot", "m", "baseline", 1, "r", "run")
        with patch("pathlib.Path.read_text", return_value=payload):
            retryable = NanobotAdapter._retryable_tasks({"t": locator}, ["t"])
        self.assertEqual(retryable, ["t"])

    def test_nanobot_adapter_records_whole_task_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            result_path = run_root / "task_result.json"
            result_path.write_text(
                json.dumps({"task_id": "t", "status": "completed"}),
                encoding="utf-8",
            )
            locator = RunLocator("t", "nanobot", "m", "baseline", 1, "r", str(run_root))
            NanobotAdapter._record_attempt_count(locator, 3)
            result = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(result["whole_task_attempt_count"], 3)
        self.assertEqual(result["infrastructure_retry_count"], 2)

    def test_runner_task_view_excludes_evaluator_only_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path = root / "tasks.json"
            task_path.write_text(
                json.dumps(
                    [
                        {
                            "task_id": "t",
                            "instruction": "answer",
                            "turns": [{"idx": 0, "question": "q"}],
                            "skills": ["s"],
                            "required_execution_skills": ["s"],
                            "metadata": {
                                "answer_contract": "json_array",
                                "output_fields": ["value"],
                                "gold_rows": [{"value": 1}],
                                "oracle_sql_template": "select 1",
                                "internal_note": "private",
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )
            experiment = root / "experiment.yaml"
            experiment.write_text(
                "experiment_id: test\n"
                "output_root: output\n"
                "task_json: tasks.json\n",
                encoding="utf-8",
            )
            _, paths = load_experiment(experiment, root)
            output = write_runner_tasks(paths)
            runner_task = json.loads(output.read_text(encoding="utf-8"))[0]

        self.assertEqual(runner_task["skills"], ["s"])
        self.assertEqual(
            runner_task["metadata"],
            {"answer_contract": "json_array", "output_fields": ["value"]},
        )
        self.assertNotIn("gold_rows", json.dumps(runner_task))
        self.assertNotIn("oracle_sql", json.dumps(runner_task))

    def test_formal_runner_config_enables_bwrap(self) -> None:
        config = build_config(
            base_config={},
            workspace=Path("/tmp/workspace"),
            allowed_skills=[],
            skills_root=Path("/tmp/skills"),
            skill_mode="off",
            timezone="UTC",
            max_tool_iterations=10,
            sandbox="bwrap",
        )
        self.assertTrue(config["tools"]["restrictToWorkspace"])
        self.assertEqual(config["tools"]["exec"]["sandbox"], "bwrap")

    def test_asset_copy_preserves_source_and_checks_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_root = root / "data"
            workspace = root / "workspace"
            source = data_root / "dataset/table.bin"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"immutable-input")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            task = {
                "data_assets": [
                    {
                        "path": "dataset/table.bin",
                        "env_path": "datasets/table.bin",
                        "sha256": digest,
                    }
                ]
            }
            staged = stage_task_assets(task, workspace, data_root, "copy")
            destination = workspace / "datasets/table.bin"
            destination.write_bytes(b"agent-write")

            self.assertEqual(source.read_bytes(), b"immutable-input")
            self.assertEqual(staged[0]["sha256"], digest)
            task["data_assets"][0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                stage_task_assets(task, root / "bad-workspace", data_root, "copy")

    def test_cli_skill_arguments_are_observable_temporal_evidence(self) -> None:
        commands = [
            "python skills/tableagent-grouped-anomaly-scoring/scripts/execute_analysis.py "
            "--method mad --frequency month --window 7"
        ]
        self.assertIn("month", _temporal_granularities(commands))
        self.assertIn("parameter:7:period", _temporal_parameters(commands))
        self.assertIn("robust_scale", _temporal_operation_sequence(commands))

    def test_metric_audit_flags_conditional_and_saturated_metrics(self) -> None:
        contracts = [
            {
                "required_tables": ["a", "b"],
                "candidate_tables": ["a", "b", "noise"],
                "relational_contract": {"required": True, "using_keys": ["id"]},
                "temporal_contract": {
                    "required": True,
                    "anchors": [{"role": "scope_start", "value": "2020-01-01"}],
                    "required_operations": ["filter"],
                    "required_dependencies": [],
                    "required_parameters": [],
                    "required_granularities": ["day"],
                    "leakage_policy": {"required": False},
                },
            }
        ]
        applicability = {
            row["metric"]: row
            for row in static_metric_applicability(
                contracts, ["table_retrieval_f1", "leakage_free"]
            )
        }
        self.assertEqual(
            applicability["table_retrieval_f1"]["contract_coverage"], 1.0
        )
        self.assertEqual(
            applicability["leakage_free"]["recommended_role"],
            "insufficient_coverage",
        )
        health = empirical_metric_health(
            [
                {"framework": "f", "model": "m", "condition": "baseline", "x": 1.0},
                {"framework": "f", "model": "m", "condition": "skill", "x": 1.0},
            ],
            ["x"],
        )[0]
        self.assertIn("near_ceiling", health["flags"])
        self.assertIn("low_condition_separation", health["flags"])

    def test_score_answer_exact_and_partial(self) -> None:
        gold = [{"entity": "A", "value": 1.25}, {"entity": "B", "value": 2.5}]
        exact = score_answer(list(gold), gold, ["entity"])
        self.assertIs(exact["passed"], True)
        self.assertEqual(exact["partial_credit_score"], 1.0)

        partial = score_answer(
            [{"entity": "A", "value": 1.25}, {"entity": "B", "value": 9.0}],
            gold,
            ["entity"],
        )
        self.assertIs(partial["passed"], False)
        self.assertEqual(partial["row_recall"], 1.0)
        self.assertEqual(partial["field_recall"], 0.75)

    def test_score_answer_f1_penalizes_extra_rows_and_fields(self) -> None:
        gold = [{"entity": "A", "value": 1.25}]
        actual = [
            {"entity": "A", "value": 1.25, "extra": "noise"},
            {"entity": "B", "value": 9.0},
        ]
        result = score_answer(actual, gold, ["entity"])

        self.assertEqual(result["partial_credit_score"], 1.0)
        self.assertLess(result["partial_credit_f1"], 1.0)
        self.assertEqual(result["row_precision"], 0.5)
        self.assertEqual(result["row_recall"], 1.0)
        self.assertEqual(result["extra_row_count"], 1)
        self.assertFalse(result["passed"])

    def test_score_trace_separates_raw_and_after_repair_success(self) -> None:
        trace = TraceRecord(
            locator=RunLocator("t", "nanobot", "m", "baseline", 1, "r", "."),
            status="completed",
            failure_reason="",
            final_answer='[{"entity":"A","value":1}]',
            pre_repair_final_answer="not-json",
            answer_source="successful_turn",
            final_answer_repair_attempt_count=1,
            final_answer_repair_success_count=1,
        )
        contract = {
            "answer_contract": {
                "gold_rows": [{"entity": "A", "value": 1}],
                "key_fields": ["entity"],
            }
        }
        result = score_trace(trace, {"task_id": "t"}, contract)

        self.assertEqual(result["raw_strict_success"], 0.0)
        self.assertEqual(result["after_repair_strict_success"], 1.0)
        self.assertEqual(result["repair_attempted"], 1.0)
        self.assertEqual(result["repair_succeeded"], 1.0)

    def test_prf_penalizes_extra_retrieval(self) -> None:
        precision, recall, f1 = prf({"a", "b"}, {"a", "b", "c"})
        self.assertEqual(precision, 2 / 3)
        self.assertEqual(recall, 1.0)
        self.assertGreater(f1, 0)
        self.assertLess(f1, 1)

    def test_paired_comparison_counts_skill_transitions(self) -> None:
        rows = []
        for task_id, baseline, skill in (
            ("a", False, True),
            ("b", True, False),
            ("c", True, True),
            ("d", False, True),
        ):
            common = {
                "task_id": task_id,
                "framework": "nanobot",
                "model": "m",
                "repeat": 1,
                "partial_credit_score": 1.0,
            }
            rows.append({**common, "condition": "baseline", "passed": baseline})
            rows.append({**common, "condition": "self_route", "passed": skill})
        result = pair_conditions(
            rows,
            target_condition="self_route",
            bootstrap_samples=100,
        )
        self.assertEqual(result["paired_count"], 4)
        self.assertEqual(result["fixed_count"], 2)
        self.assertEqual(result["regressed_count"], 1)
        self.assertEqual(result["absolute_success_gain"], 0.25)
        self.assertEqual(exact_mcnemar_p(2, 1), 1.0)

    def test_temporal_metrics_cover_scope_grain_and_operations(self) -> None:
        trace = TraceRecord(
            locator=RunLocator("t", "nanobot", "m", "baseline", 1, "r", "."),
            status="completed",
            failure_reason="",
            final_answer="[]",
            answer_source="final_output",
            timestamps_used=["2020-01-01", "2020-02-01"],
            temporal_operations=["filter", "period_aggregate"],
            temporal_operation_sequence=["filter", "period_aggregate"],
            temporal_granularities=["day"],
            temporal_parameters=["duration:7:day"],
            commands=["df[(df.date >= '2020-01-01') & (df.date < '2020-02-01')]"],
        )
        contract = {
            "temporal_contract": {
                "time_literals": ["2020-01-01", "2020-02-01"],
                "anchors": [
                    {"role": "scope_start", "value": "2020-01-01", "boundary": "inclusive"},
                    {"role": "scope_end", "value": "2020-02-01", "boundary": "exclusive"},
                ],
                "scope_boundaries": ["2020-01-01", "2020-02-01"],
                "scope_end_exclusive": "2020-02-01",
                "required_operations": ["period_compare", "period_aggregate"],
                "required_dependencies": [["period_compare", "period_aggregate"]],
                "required_granularities": ["day"],
                "required_parameters": ["duration:7:day"],
                "leakage_policy": {
                    "required": True,
                    "analysis_end_exclusive": "2020-02-01",
                },
            }
        }
        metrics = _temporal_metrics(trace, contract)
        self.assertEqual(metrics["temporal_scope_f1"], 1.0)
        self.assertEqual(metrics["temporal_boundary_coverage"], 1.0)
        self.assertEqual(metrics["temporal_operation_f1"], 1.0)
        self.assertEqual(metrics["temporal_granularity_alignment"], 1.0)
        self.assertEqual(metrics["temporal_dependency_f1"], 1.0)
        self.assertEqual(metrics["temporal_parameter_accuracy"], 1.0)
        self.assertEqual(metrics["temporal_grounding_f1"], 1.0)
        self.assertEqual(metrics["temporal_execution_accuracy"], 1.0)
        self.assertIs(metrics["leakage_free"], True)
        self.assertEqual(metrics["temporal_constraint_compliance"], 1.0)
        self.assertIs(metrics["temporal_strict_compliance"], True)

        trace.temporal_operations.append("forecast")
        metrics_with_extra = _temporal_metrics(trace, contract)
        self.assertLess(metrics_with_extra["temporal_operation_precision"], 1.0)
        self.assertLess(metrics_with_extra["temporal_operation_f1"], 1.0)

    def test_relational_metrics_penalize_distractor_tables_and_wrong_keys(self) -> None:
        trace = TraceRecord(
            locator=RunLocator("t", "nanobot", "m", "baseline", 1, "r", "."),
            status="completed",
            failure_reason="",
            final_answer="[]",
            answer_source="final_output",
            tables_read=["facts", "entities", "distractor"],
            join_operations=[
                {
                    "join_count": 1,
                    "using_keys": ["wrong_id"],
                    "merge_keys": [],
                    "on_edges": [],
                }
            ],
        )
        contract = {
            "required_tables": ["facts", "entities"],
            "candidate_tables": ["facts", "entities", "distractor"],
            "relational_contract": {
                "required": True,
                "required_join_count": 1,
                "using_keys": ["entity_id"],
                "on_edges": [],
            },
        }
        metrics = _relational_metrics(trace, contract)
        self.assertEqual(metrics["table_retrieval_recall"], 1.0)
        self.assertLess(metrics["table_retrieval_f1"], 1.0)
        self.assertLess(metrics["relational_execution_accuracy"], 1.0)

    def test_contract_ignores_hidden_generator_dates(self) -> None:
        task = {
            "task_id": "t",
            "turns": [{"question": "Use the half-open interval [2020-01-01, 2021-01-01)."}],
            "data_assets": [{"path": "facts.parquet"}],
            "skills": ["s"],
            "metadata": {
                "source": "demo",
                "task_family": "period_compare",
                "required_tables": ["facts"],
                "gold_rows": [{"value": 1}],
                "key_fields": ["value"],
                "task_parameters": {
                    "start": "2020-01-01",
                    "split": "2020-06-01",
                    "end": "2021-01-01",
                },
            },
        }
        contract = build_contract(task)
        self.assertEqual(
            contract["temporal_contract"]["time_literals"],
            ["2020-01-01", "2021-01-01"],
        )
        self.assertNotIn(
            "2020-06-01",
            str(contract["temporal_contract"]["anchors"]),
        )

    def test_tcc_is_graded_and_retains_strict_indicator(self) -> None:
        trace = TraceRecord(
            locator=RunLocator("t", "nanobot", "m", "baseline", 1, "r", "."),
            status="completed",
            failure_reason="",
            final_answer="[]",
            answer_source="final_output",
            timestamps_used=["2020-01-01", "2020-02-01"],
            temporal_operations=["filter"],
            temporal_operation_sequence=["filter"],
            temporal_granularities=["month"],
            commands=["df[(df.date >= '2020-01-01') & (df.date <= '2020-02-01')]"],
        )
        contract = {
            "temporal_contract": {
                "time_literals": ["2020-01-01", "2020-02-01"],
                "anchors": [
                    {"role": "scope_start", "value": "2020-01-01", "boundary": "inclusive"},
                    {"role": "scope_end", "value": "2020-02-01", "boundary": "exclusive"},
                ],
                "required_operations": ["period_compare"],
                "required_dependencies": [],
                "required_granularities": ["month"],
                "required_parameters": [],
                "leakage_policy": {"required": False},
            }
        }
        metrics = _temporal_metrics(trace, contract)
        self.assertGreater(metrics["temporal_constraint_compliance"], 0.0)
        self.assertLess(metrics["temporal_constraint_compliance"], 1.0)
        self.assertIs(metrics["temporal_strict_compliance"], False)

    def test_avg_at_k_is_macro_averaged_per_task(self) -> None:
        rows = [
            {"task_id": "a", "repeat": 1, "strict_success": 1.0, "passed": True},
            {"task_id": "a", "repeat": 2, "strict_success": 0.0, "passed": False},
            {"task_id": "b", "repeat": 1, "strict_success": 1.0, "passed": True},
            {"task_id": "b", "repeat": 2, "strict_success": 1.0, "passed": True},
        ]
        summary = aggregate_group(rows)
        self.assertEqual(summary["avg_at_k"], 0.75)
        self.assertEqual(summary["avg_at_k_k"], 2)

    def test_avg_at_k_excludes_incomplete_infrastructure_repeats(self) -> None:
        rows = [
            {"task_id": "a", "repeat": 1, "strict_success": 1.0, "passed": True},
            {"task_id": "a", "repeat": 2, "strict_success": None, "passed": None},
            {"task_id": "b", "repeat": 1, "strict_success": 0.0, "passed": False},
            {"task_id": "b", "repeat": 2, "strict_success": 1.0, "passed": True},
        ]
        summary = aggregate_group(rows)
        self.assertEqual(summary["avg_at_k"], 0.5)
        self.assertEqual(summary["avg_at_k_covered_tasks"], 1)
        self.assertEqual(summary["avg_at_k_task_coverage"], 0.5)

    def test_contract_separates_selected_and_executed_skills(self) -> None:
        task = {
            "task_id": "t",
            "turns": [{"question": "Compare 2020 with 2021."}],
            "data_assets": [{"path": "facts.parquet"}],
            "skills": ["table-selection", "analysis"],
            "required_execution_skills": ["analysis"],
            "metadata": {
                "source": "demo",
                "task_family": "period_compare",
                "required_tables": ["facts"],
                "gold_rows": [{"value": 1}],
                "key_fields": ["value"],
            },
        }
        contract = build_contract(task)
        self.assertEqual(contract["required_skills"], ["table-selection", "analysis"])
        self.assertEqual(contract["required_execution_skills"], ["analysis"])

    def test_llm_timeout_is_infrastructure_error(self) -> None:
        self.assertEqual(
            detect_infrastructure_error("Error calling LLM: timed out after 300s"),
            "llm_timeout",
        )

    def test_dashscope_burst_limit_is_infrastructure_error(self) -> None:
        self.assertEqual(
            detect_infrastructure_error(
                "Error: {'type': 'limit_burst_rate', "
                "'message': 'Request rate increased too quickly.'}"
            ),
            "llm_rate_limit",
        )

    def test_dashscope_content_filter_is_infrastructure_error(self) -> None:
        self.assertEqual(
            detect_infrastructure_error("Error: {'code': 'data_inspection_failed'}"),
            "llm_content_filter",
        )

    def test_json_contract_repairs_markdown_table_output(self) -> None:
        task = {
            "metadata": {
                "answer_contract": "json_array",
                "output_fields": ["segment", "month", "value"],
            }
        }
        self.assertEqual(
            final_answer_issue("| segment | month | value |\n| A | 2020-01 | 1 |", task),
            "missing_or_invalid_json_array",
        )
        self.assertIsNone(final_answer_issue('[{"segment":"A","month":"2020-01","value":1}]', task))
        prompt = build_final_answer_repair_prompt(task, "missing_or_invalid_json_array")
        self.assertIn("valid JSON array", prompt)
        self.assertIn("segment, month, value", prompt)


if __name__ == "__main__":
    unittest.main()
