from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from benchmark_eval.metric_audit import empirical_metric_health
from benchmark_eval.statistics import pair_conditions
from benchmark_eval.utils import mean_or_none, write_csv, write_json

METRICS = [
    "strict_success",
    "raw_strict_success",
    "after_repair_strict_success",
    "repair_attempted",
    "repair_succeeded",
    "whole_task_attempt_count",
    "infrastructure_retry_count",
    "partial_credit_score",
    "partial_credit_f1",
    "row_f1",
    "field_f1",
    "valid_completion",
    "table_retrieval_f1",
    "relational_execution_accuracy",
    "relational_join_coverage",
    "relational_join_key_f1",
    "distractor_avoidance_rate",
    "temporal_grounding_f1",
    "temporal_execution_accuracy",
    "temporal_evidence_coverage",
    "temporal_scope_f1",
    "temporal_boundary_coverage",
    "temporal_granularity_alignment",
    "temporal_operation_f1",
    "temporal_dependency_f1",
    "temporal_parameter_accuracy",
    "temporal_constraint_compliance",
    "temporal_strict_compliance",
    "leakage_free",
    "skill_retrieval_f1",
    "skill_execution_f1",
    "skill_validation_rate",
    "total_tokens",
    "tool_call_count",
]

PRIMARY_METRICS = [
    "avg_at_k",
    "partial_credit_score",
    "valid_completion",
    "table_retrieval_f1",
    "relational_execution_accuracy",
    "temporal_grounding_f1",
    "temporal_execution_accuracy",
    "temporal_dependency_f1",
    "temporal_constraint_compliance",
    "skill_retrieval_f1",
    "skill_execution_f1",
    "skill_validation_rate",
    "skill_induced_success_gain",
    "tool_call_count",
    "tokens_per_success",
]

METRIC_DEFINITIONS = {
    "avg_at_k": "Macro-average over tasks of the mean strict success across k independent repeats.",
    "raw_strict_success": "Strict success before any format-only repair turn.",
    "after_repair_strict_success": "Strict success after the declared format-only repair policy.",
    "repair_attempted": "Fraction of runs that used a format-only repair turn.",
    "repair_succeeded": "Success rate among runs that attempted format-only repair.",
    "whole_task_attempt_count": "Mean whole-task attempts, including the initial attempt.",
    "infrastructure_retry_count": "Mean whole-task retries caused by classified infrastructure failures.",
    "partial_credit_score": "Mean gold output-field coverage after key-based row matching.",
    "partial_credit_f1": "Field-level F1 after key-based row matching; extra rows and fields reduce precision.",
    "row_f1": "F1 between expected and submitted rows after key-based matching.",
    "field_f1": "F1 between expected and correct submitted fields, including penalties for extra fields.",
    "valid_completion": "Fraction of runs completed with a parseable contract-shaped answer.",
    "table_retrieval_f1": "F1 between required and trace-observed table sets.",
    "relational_execution_accuracy": "Mean applicable correctness of table coverage, join execution, and required join keys.",
    "relational_join_coverage": "Fraction of the minimum required join chain observed in executable commands.",
    "relational_join_key_f1": "F1 between required and trace-observed relational join keys.",
    "distractor_avoidance_rate": "Fraction of visible distractor tables not used in the executed analysis.",
    "temporal_grounding_f1": "F1 between required and trace-observed temporal anchors and scope literals.",
    "temporal_execution_accuracy": "Mean applicable GrA, Op-F1, Dep-F1, and ParamAcc.",
    "temporal_evidence_coverage": "Fraction of applicable temporal contract components with observable execution evidence.",
    "temporal_dependency_f1": "F1 of required pairwise temporal-operation dependencies observed in execution order.",
    "leakage_free": "Conditional safety diagnostic on leakage-sensitive tasks: fraction without command-observed future or out-of-bound access violations.",
    "temporal_constraint_compliance": "Mean compliance across applicable grounding, granularity, operation, dependency, parameter, and leakage constraints.",
    "temporal_strict_compliance": "Appendix indicator equal to one only when every applicable temporal constraint is fully satisfied.",
    "skill_retrieval_f1": "F1 between gold and agent-selected skill sets; Oracle uses its explicitly loaded set.",
    "skill_execution_f1": "F1 between required and script/structured-evidence executed skill sets.",
    "skill_validation_rate": "Fraction of executed skills with successful validator evidence.",
    "skill_induced_success_gain": "Paired Avg@k difference between a skill condition and baseline.",
    "tool_call_count": "Mean number of trace-observed tool calls per run.",
    "tokens_per_success": "Total input plus output tokens divided by strict successes.",
}


def average_at_k(
    rows: list[dict[str, Any]],
) -> tuple[float | None, int | None, int, int]:
    """Macro-average per-task success over independent repeats."""
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_task[str(row.get("task_id"))].append(row)
    expected_repeats = sorted({int(row.get("repeat", 1)) for row in rows})
    k = len(expected_repeats) or None
    task_values = []
    for task_rows in by_task.values():
        valid_by_repeat = {
            int(item.get("repeat", 1)): item.get("strict_success")
            for item in task_rows
            if item.get("strict_success") is not None
        }
        if expected_repeats and all(rep in valid_by_repeat for rep in expected_repeats):
            task_values.append(mean_or_none(valid_by_repeat.values()))
    return mean_or_none(task_values), k, len(task_values), len(by_task)


def aggregate_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {"task_count": len(rows)}
    avg_at_k, k, covered_tasks, total_tasks = average_at_k(rows)
    summary["avg_at_k"] = avg_at_k
    summary["avg_at_k_k"] = k
    summary["avg_at_k_covered_tasks"] = covered_tasks
    summary["avg_at_k_task_coverage"] = (
        covered_tasks / total_tasks if total_tasks else None
    )
    for metric in METRICS:
        summary[metric] = mean_or_none(row.get(metric) for row in rows)
        summary[f"{metric}_n"] = sum(row.get(metric) is not None for row in rows)
    successes = sum(bool(row.get("passed")) for row in rows)
    tokens = sum(int(row.get("total_tokens") or 0) for row in rows)
    durations = sum(float(row.get("duration_seconds") or 0) for row in rows)
    summary["passed"] = successes
    summary["tokens_per_success"] = tokens / successes if successes and tokens else None
    summary["time_per_success"] = durations / successes if successes and durations else None
    summary["infrastructure_error_rate"] = (
        sum(
            row.get("status") in {"missing_run", "infrastructure_error"}
            for row in rows
        )
        / len(rows)
        if rows
        else None
    )
    return summary


def aggregate(
    rows: list[dict[str, Any]],
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(key) for key in keys)].append(row)
    output = []
    for values, group_rows in sorted(groups.items(), key=lambda item: str(item[0])):
        output.append(
            {
                **dict(zip(keys, values)),
                **aggregate_group(group_rows),
            }
        )
    return output


def macro_score(
    rows: list[dict[str, Any]],
    *,
    group_key: str,
    metric: str,
) -> float | None:
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row.get(group_key)].append(row)
    return mean_or_none(
        mean_or_none(row.get(metric) for row in group_rows)
        for group_rows in groups.values()
    )


def latex_escape(value: Any) -> str:
    text = str(value)
    for source, target in (
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("_", r"\_"),
        ("#", r"\#"),
    ):
        text = text.replace(source, target)
    return text


def percent(value: Any) -> str:
    return "--" if value is None else f"{100 * float(value):.1f}"


def number(value: Any) -> str:
    return "--" if value is None else f"{float(value):.1f}"


def write_main_latex(path: Path, overall: list[dict[str, Any]]) -> None:
    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Overall performance on the multi-table time-series benchmark.}",
        r"\label{tab:overall}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{lll|rrr|rr|rrrr|rrrr|rr}",
        r"\toprule",
        r"\multirow{2}{*}{Framework} & \multirow{2}{*}{Model} & \multirow{2}{*}{Setting} &",
        r"\multicolumn{3}{c|}{Outcome Quality} & \multicolumn{2}{c|}{Multi-Table Execution} &",
        r"\multicolumn{4}{c|}{Temporal Processing} & \multicolumn{4}{c|}{Skill-Oriented Evaluation} & \multicolumn{2}{c}{Efficiency}\\",
        r"\cmidrule(lr){4-6}\cmidrule(lr){7-8}\cmidrule(lr){9-12}\cmidrule(lr){13-16}\cmidrule(lr){17-18}",
        r"& & & Avg@$k\uparrow$ & PCS$\uparrow$ & VCR$\uparrow$ & TR-F1$\uparrow$ & REA$\uparrow$ & TG-F1$\uparrow$ & TEA$\uparrow$ & Dep-F1$\uparrow$ & TCC$\uparrow$ & SkR-F1$\uparrow$ & SkE-F1$\uparrow$ & SVR$\uparrow$ & $\Delta$SR$\uparrow$ & Calls$\downarrow$ & Tok./Succ.$\downarrow$\\",
        r"\midrule",
    ]
    previous_framework = None
    for row in overall:
        framework = latex_escape(row.get("framework", ""))
        model = latex_escape(row.get("model", ""))
        setting = latex_escape(row.get("condition", ""))
        if previous_framework is not None and framework != previous_framework:
            lines.append(r"\midrule")
        values = [
            percent(row.get("avg_at_k")),
            percent(row.get("partial_credit_score")),
            percent(row.get("valid_completion")),
            percent(row.get("table_retrieval_f1")),
            percent(row.get("relational_execution_accuracy")),
            percent(row.get("temporal_grounding_f1")),
            percent(row.get("temporal_execution_accuracy")),
            percent(row.get("temporal_dependency_f1")),
            percent(row.get("temporal_constraint_compliance")),
            percent(row.get("skill_retrieval_f1")),
            percent(row.get("skill_execution_f1")),
            percent(row.get("skill_validation_rate")),
            percent(row.get("skill_induced_success_gain")),
            number(row.get("tool_call_count")),
            number(row.get("tokens_per_success")),
        ]
        lines.append(
            f"{framework} & {model} & {setting} & "
            + " & ".join(values)
            + r"\\"
        )
        previous_framework = framework
    lines.extend([r"\bottomrule", r"\end{tabular}}", r"\end{table*}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_temporal_latex(path: Path, overall: list[dict[str, Any]]) -> None:
    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Temporal reasoning performance.}",
        r"\label{tab:temporal}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{lll|rrrrrrrr}",
        r"\toprule",
        r"Framework & Model & Setting & TG-F1$\uparrow$ & GrA$\uparrow$ & Op-F1$\uparrow$ & Dep-F1$\uparrow$ & ParamAcc$\uparrow$ & TEA$\uparrow$ & LFR$\uparrow$ & TCC$\uparrow$\\",
        r"\midrule",
    ]
    for row in overall:
        values = [
            percent(row.get("temporal_grounding_f1")),
            percent(row.get("temporal_granularity_alignment")),
            percent(row.get("temporal_operation_f1")),
            percent(row.get("temporal_dependency_f1")),
            percent(row.get("temporal_parameter_accuracy")),
            percent(row.get("temporal_execution_accuracy")),
            percent(row.get("leakage_free")),
            percent(row.get("temporal_constraint_compliance")),
        ]
        lines.append(
            f"{latex_escape(row.get('framework', ''))} & "
            f"{latex_escape(row.get('model', ''))} & "
            f"{latex_escape(row.get('condition', ''))} & "
            + " & ".join(values)
            + r"\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}}", r"\end{table*}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def generate_reports(
    rows: list[dict[str, Any]],
    output_dir: Path,
    *,
    bootstrap_samples: int = 10000,
    confidence: float = 0.95,
    comparison_baselines: dict[str, str] | None = None,
) -> dict[str, Any]:
    comparison_baselines = comparison_baselines or {}
    overall = aggregate(rows, ("framework", "model", "condition"))
    by_dataset = aggregate(rows, ("framework", "model", "condition", "dataset"))
    by_family = aggregate(rows, ("framework", "model", "condition", "task_family"))
    by_temporal_operation_rows = []
    by_skill_rows = []
    skills = sorted(
        {
            skill
            for row in rows
            for skill in row.get("required_skills") or []
        }
    )
    for framework in sorted({row["framework"] for row in rows}):
        for model in sorted({row["model"] for row in rows if row["framework"] == framework}):
            for condition in sorted(
                {
                    row["condition"]
                    for row in rows
                    if row["framework"] == framework and row["model"] == model
                }
            ):
                scoped = [
                    row
                    for row in rows
                    if row["framework"] == framework
                    and row["model"] == model
                    and row["condition"] == condition
                ]
                for skill in skills:
                    skill_rows = [
                        row for row in scoped if skill in (row.get("required_skills") or [])
                    ]
                    if skill_rows:
                        by_skill_rows.append(
                            {
                                "framework": framework,
                                "model": model,
                                "condition": condition,
                                "skill": skill,
                                **aggregate_group(skill_rows),
                            }
                        )

    temporal_operations = sorted(
        {
            operation
            for row in rows
            for operation in row.get("required_temporal_operations") or []
        }
    )
    for framework, model, condition in sorted(
        {
            (row["framework"], row["model"], row["condition"])
            for row in rows
        }
    ):
        scoped = [
            row
            for row in rows
            if row["framework"] == framework
            and row["model"] == model
            and row["condition"] == condition
        ]
        for operation in temporal_operations:
            operation_rows = [
                row
                for row in scoped
                if operation in (row.get("required_temporal_operations") or [])
            ]
            if operation_rows:
                by_temporal_operation_rows.append(
                    {
                        "framework": framework,
                        "model": model,
                        "condition": condition,
                        "temporal_operation": operation,
                        **aggregate_group(operation_rows),
                    }
                )

    comparisons = []
    baseline_gain_lookup: dict[tuple[str, str, str], float | None] = {}
    pairs = sorted({(row["framework"], row["model"]) for row in rows})
    for framework, model in pairs:
        scoped = [
            row
            for row in rows
            if row["framework"] == framework and row["model"] == model
        ]
        conditions = {row["condition"] for row in scoped}
        if "baseline" in conditions:
            for target in sorted(conditions - {"baseline"}):
                baseline_comparison = pair_conditions(
                    scoped,
                    baseline_condition="baseline",
                    target_condition=target,
                    bootstrap_samples=bootstrap_samples,
                    confidence=confidence,
                )
                baseline_gain_lookup[(framework, model, target)] = (
                    baseline_comparison.get("absolute_success_gain")
                )
        for target in sorted(conditions):
            reference = comparison_baselines.get(target, "baseline")
            if target == reference or reference not in conditions:
                continue
            comparison = pair_conditions(
                scoped,
                baseline_condition=reference,
                target_condition=target,
                bootstrap_samples=bootstrap_samples,
                confidence=confidence,
            )
            comparison["framework"] = framework
            comparison["model"] = model
            comparisons.append(comparison)

    for row in overall:
        scoped = [
            item
            for item in rows
            if item["framework"] == row["framework"]
            and item["model"] == row["model"]
            and item["condition"] == row["condition"]
        ]
        row["macro_dataset_sr"] = macro_score(
            scoped,
            group_key="dataset",
            metric="strict_success",
        )
        row["macro_family_sr"] = macro_score(
            scoped,
            group_key="task_family",
            metric="strict_success",
        )

    for row in overall:
        if row.get("condition") == "baseline":
            row["skill_induced_success_gain"] = None
        else:
            row["skill_induced_success_gain"] = baseline_gain_lookup.get(
                (row["framework"], row["model"], row["condition"])
            )

    comparison_lookup = {
        (item["framework"], item["model"], item["target_condition"]): item
        for item in comparisons
    }
    for row in overall:
        comparison = comparison_lookup.get(
            (row["framework"], row["model"], row["condition"])
        )
        row["comparison_reference"] = (
            comparison.get("baseline_condition") if comparison else None
        )
        row["success_delta_vs_reference"] = (
            comparison.get("absolute_success_gain") if comparison else None
        )

    coverage_rows = []
    for row in overall:
        for metric in PRIMARY_METRICS:
            if metric == "avg_at_k":
                value_count = row.get("strict_success_n", 0)
            elif metric == "tokens_per_success":
                value_count = row.get("total_tokens_n", 0)
            elif metric == "skill_induced_success_gain":
                value_count = row.get("task_count") if row.get(metric) is not None else 0
            else:
                value_count = row.get(f"{metric}_n", 0)
            coverage_rows.append(
                {
                    "framework": row["framework"],
                    "model": row["model"],
                    "condition": row["condition"],
                    "metric": metric,
                    "value_count": value_count,
                    "task_count": row.get("task_count"),
                    "coverage": (
                        value_count / row["task_count"] if row.get("task_count") else None
                    ),
                }
            )

    write_json(output_dir / "summary.json", {"overall": overall, "comparisons": comparisons})
    write_json(
        output_dir / "metric_definitions.json",
        {"primary_metrics": PRIMARY_METRICS, "definitions": METRIC_DEFINITIONS},
    )
    write_csv(output_dir / "overall.csv", overall)
    write_csv(output_dir / "by_dataset.csv", by_dataset)
    write_csv(output_dir / "by_task_family.csv", by_family)
    write_csv(output_dir / "by_skill.csv", by_skill_rows)
    write_csv(output_dir / "by_temporal_operation.csv", by_temporal_operation_rows)
    write_csv(output_dir / "metric_coverage.csv", coverage_rows)
    metric_health = empirical_metric_health(rows, METRICS)
    write_json(output_dir / "metric_health.json", {"metrics": metric_health})
    write_csv(output_dir / "metric_health.csv", metric_health)
    write_json(
        output_dir / "paired_comparisons.json",
        {"comparisons": comparisons},
    )
    write_csv(
        output_dir / "paired_comparisons.csv",
        [
            {key: value for key, value in comparison.items() if key != "tasks"}
            for comparison in comparisons
        ],
    )
    write_csv(
        output_dir / "paired_transitions.csv",
        [
            {
                "framework": comparison.get("framework"),
                "model": comparison.get("model"),
                "baseline_condition": comparison.get("baseline_condition"),
                **task,
            }
            for comparison in comparisons
            for task in comparison.get("tasks", [])
        ],
    )
    write_main_latex(output_dir / "table_main.tex", overall)
    write_temporal_latex(output_dir / "table_temporal.tex", overall)
    return {
        "overall": overall,
        "by_dataset": by_dataset,
        "by_task_family": by_family,
        "by_skill": by_skill_rows,
        "by_temporal_operation": by_temporal_operation_rows,
        "comparisons": comparisons,
        "metric_health": metric_health,
    }
