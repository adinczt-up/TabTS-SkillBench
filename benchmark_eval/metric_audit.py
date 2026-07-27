from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any


def _eligible(contract: dict[str, Any], metric: str) -> bool:
    relation = contract.get("relational_contract") or {}
    temporal = contract.get("temporal_contract") or {}
    if metric in {"table_retrieval_f1", "relational_execution_accuracy"}:
        return bool(contract.get("required_tables"))
    if metric == "relational_join_coverage":
        return bool(relation.get("required"))
    if metric == "relational_join_key_f1":
        return bool(relation.get("using_keys") or relation.get("on_edges"))
    if metric == "distractor_avoidance_rate":
        return bool(set(contract.get("candidate_tables") or []) - set(contract.get("required_tables") or []))
    if metric in {"temporal_grounding_f1", "temporal_scope_f1"}:
        return bool(temporal.get("anchors") or temporal.get("time_literals"))
    if metric == "temporal_granularity_alignment":
        return bool(temporal.get("required_granularities"))
    if metric == "temporal_operation_f1":
        return bool(temporal.get("required_operations"))
    if metric == "temporal_dependency_f1":
        return bool(temporal.get("required_dependencies"))
    if metric == "temporal_parameter_accuracy":
        return bool(temporal.get("required_parameters"))
    if metric == "temporal_boundary_coverage":
        return any(
            anchor.get("boundary") in {"inclusive", "exclusive"}
            for anchor in temporal.get("anchors") or []
        )
    if metric == "leakage_free":
        return bool((temporal.get("leakage_policy") or {}).get("required"))
    if metric in {
        "temporal_execution_accuracy",
        "temporal_evidence_coverage",
        "temporal_constraint_compliance",
        "temporal_strict_compliance",
    }:
        return bool(temporal.get("required"))
    return True


def static_metric_applicability(
    contracts: list[dict[str, Any]],
    metrics: list[str],
) -> list[dict[str, Any]]:
    total = len(contracts)
    rows = []
    for metric in metrics:
        count = sum(_eligible(contract, metric) for contract in contracts)
        coverage = count / total if total else 0.0
        if coverage >= 0.75:
            role = "main_candidate"
        elif coverage >= 0.25:
            role = "conditional_or_appendix"
        else:
            role = "insufficient_coverage"
        rows.append(
            {
                "metric": metric,
                "eligible_tasks": count,
                "task_count": total,
                "contract_coverage": coverage,
                "recommended_role": role,
            }
        )
    return rows


def empirical_metric_health(
    rows: list[dict[str, Any]],
    metrics: list[str],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("framework")), str(row.get("model")))].append(row)
    output = []
    for (framework, model), scoped in sorted(grouped.items()):
        conditions = sorted({str(row.get("condition")) for row in scoped})
        for metric in metrics:
            condition_stats: dict[str, dict[str, Any]] = {}
            all_values: list[float] = []
            for condition in conditions:
                values = [
                    float(row[metric])
                    for row in scoped
                    if str(row.get("condition")) == condition
                    and row.get(metric) is not None
                    and isinstance(row.get(metric), (int, float, bool))
                    and math.isfinite(float(row[metric]))
                ]
                all_values.extend(values)
                if values:
                    condition_stats[condition] = {
                        "n": len(values),
                        "mean": sum(values) / len(values),
                        "std": statistics.pstdev(values),
                        "floor_rate": sum(value <= 0.05 for value in values) / len(values),
                        "ceiling_rate": sum(value >= 0.95 for value in values) / len(values),
                        "unique_3dp": len({round(value, 3) for value in values}),
                    }
            means = [value["mean"] for value in condition_stats.values()]
            condition_gap = max(means) - min(means) if means else None
            flags: list[str] = []
            if not all_values:
                flags.append("no_observations")
            else:
                coverage = len(all_values) / len(scoped) if scoped else 0.0
                if coverage < 0.25:
                    flags.append("low_empirical_coverage")
                if all(value["ceiling_rate"] >= 0.8 for value in condition_stats.values()):
                    flags.append("near_ceiling")
                if all(value["floor_rate"] >= 0.8 for value in condition_stats.values()):
                    flags.append("near_floor")
                if all(value["std"] < 0.05 for value in condition_stats.values()):
                    flags.append("low_variance")
                if len(condition_stats) > 1 and condition_gap is not None and condition_gap < 0.02:
                    flags.append("low_condition_separation")
            baseline_mean = (condition_stats.get("baseline") or {}).get("mean")
            skill_means = [
                stats["mean"]
                for condition, stats in condition_stats.items()
                if condition != "baseline"
            ]
            skill_gain = (
                max(skill_means) - baseline_mean
                if baseline_mean is not None and skill_means
                else None
            )
            severe_flags = {
                "no_observations",
                "low_empirical_coverage",
                "near_ceiling",
                "near_floor",
                "low_variance",
            }
            if any(flag in severe_flags for flag in flags):
                recommended_role = "conditional_or_diagnostic"
            elif "low_condition_separation" in flags:
                recommended_role = "benchmark_characterization_or_appendix"
            else:
                recommended_role = "main_candidate"
            output.append(
                {
                    "framework": framework,
                    "model": model,
                    "metric": metric,
                    "observation_count": len(all_values),
                    "run_count": len(scoped),
                    "empirical_coverage": len(all_values) / len(scoped) if scoped else None,
                    "condition_mean_range": condition_gap,
                    "best_skill_gain_over_baseline": skill_gain,
                    "recommended_role": recommended_role,
                    "flags": flags,
                    "condition_stats": condition_stats,
                }
            )
    return output
