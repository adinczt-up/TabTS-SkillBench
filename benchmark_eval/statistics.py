from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from benchmark_eval.utils import mean_or_none


def exact_mcnemar_p(fixed: int, regressed: int) -> float:
    discordant = fixed + regressed
    if not discordant:
        return 1.0
    lower = min(fixed, regressed)
    probability = sum(
        math.comb(discordant, value)
        for value in range(lower + 1)
    ) / (2**discordant)
    return min(1.0, 2 * probability)


def paired_bootstrap_ci(
    differences: list[float],
    *,
    samples: int = 10000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float | None, float | None]:
    if not differences:
        return None, None
    rng = random.Random(seed)
    values = []
    for _ in range(samples):
        values.append(
            sum(rng.choice(differences) for _ in differences) / len(differences)
        )
    values.sort()
    alpha = (1 - confidence) / 2
    lower = values[max(0, int(alpha * samples))]
    upper = values[min(samples - 1, int((1 - alpha) * samples) - 1)]
    return lower, upper


def paired_sign_flip_p(
    differences: list[float],
    *,
    samples: int = 20000,
    seed: int = 42,
) -> float | None:
    values = [value for value in differences if value != 0]
    if not values:
        return 1.0 if differences else None
    observed = abs(sum(values) / len(values))
    rng = random.Random(seed)
    extreme = 1
    for _ in range(samples):
        statistic = abs(
            sum(value if rng.random() < 0.5 else -value for value in values)
            / len(values)
        )
        extreme += statistic >= observed
    return extreme / (samples + 1)


def pair_conditions(
    rows: list[dict[str, Any]],
    *,
    baseline_condition: str = "baseline",
    target_condition: str,
    bootstrap_samples: int = 10000,
    confidence: float = 0.95,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str, int, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        key = (
            str(row["framework"]),
            str(row["model"]),
            int(row.get("repeat", 1)),
            str(row["task_id"]),
        )
        grouped[key][str(row["condition"])] = row
    paired = []
    for key, conditions in grouped.items():
        if baseline_condition not in conditions or target_condition not in conditions:
            continue
        before = conditions[baseline_condition]
        after = conditions[target_condition]
        if before.get("passed") is None or after.get("passed") is None:
            continue
        before_pass = bool(before.get("passed"))
        after_pass = bool(after.get("passed"))
        if not before_pass and after_pass:
            transition = "fixed"
        elif before_pass and not after_pass:
            transition = "regressed"
        elif after_pass:
            transition = "unchanged_correct"
        else:
            transition = "unchanged_incorrect"
        paired.append(
            {
                "framework": key[0],
                "model": key[1],
                "repeat": key[2],
                "task_id": key[3],
                "target_condition": target_condition,
                "transition": transition,
                "baseline_passed": before_pass,
                "target_passed": after_pass,
                "baseline_pcs": before.get("partial_credit_score"),
                "target_pcs": after.get("partial_credit_score"),
            }
        )

    fixed = sum(row["transition"] == "fixed" for row in paired)
    regressed = sum(row["transition"] == "regressed" for row in paired)
    baseline_correct = sum(row["baseline_passed"] for row in paired)
    target_correct = sum(row["target_passed"] for row in paired)
    run_differences = [
        float(row["target_passed"]) - float(row["baseline_passed"])
        for row in paired
    ]
    by_task: dict[str, list[float]] = defaultdict(list)
    for row, difference in zip(paired, run_differences):
        by_task[str(row["task_id"])].append(difference)
    differences = [sum(values) / len(values) for values in by_task.values()]
    lower, upper = paired_bootstrap_ci(
        differences,
        samples=bootstrap_samples,
        confidence=confidence,
    )
    baseline_errors = len(paired) - baseline_correct
    return {
        "baseline_condition": baseline_condition,
        "target_condition": target_condition,
        "paired_count": len(paired),
        "paired_task_count": len(by_task),
        "baseline_passed": baseline_correct,
        "target_passed": target_correct,
        "absolute_success_gain": mean_or_none(differences),
        "relative_error_reduction": (
            (target_correct - baseline_correct) / baseline_errors
            if baseline_errors
            else None
        ),
        "fixed_count": fixed,
        "regressed_count": regressed,
        "positive_conversion_rate": fixed / baseline_errors if baseline_errors else None,
        "negative_transfer_rate": (
            regressed / baseline_correct if baseline_correct else None
        ),
        "mcnemar_exact_p": exact_mcnemar_p(fixed, regressed),
        "bootstrap_confidence": confidence,
        "bootstrap_ci": [lower, upper],
        "bootstrap_unit": "task_id",
        "clustered_sign_flip_p": paired_sign_flip_p(differences),
        "mean_baseline_pcs": mean_or_none(row["baseline_pcs"] for row in paired),
        "mean_target_pcs": mean_or_none(row["target_pcs"] for row in paired),
        "tasks": paired,
    }
