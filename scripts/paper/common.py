from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
PAPER_ROOT = ROOT / "artifacts" / "paper"
RESULTS_ROOT = PAPER_ROOT / "results"
MANIFEST_ROOT = PAPER_ROOT / "manifests"
DEFAULT_OUTPUT_ROOT = PAPER_ROOT / "reproduced"

CONDITIONS = ("baseline", "self_route", "annotated_preload")
CONDITION_LABELS = {
    "baseline": "Baseline",
    "self_route": "Self-Route",
    "annotated_preload": "Annotated-Skill Preload",
}
METRICS = (
    ("outcome", "avg_at_3", "Avg@3"),
    ("temporal_analysis", "tea", "TEA"),
    ("temporal_analysis", "td_f1", "TD-F1"),
    ("temporal_analysis", "tcc", "TCC"),
    ("multi_table", "rea", "REA"),
    ("multi_table", "dar", "DAR"),
    ("skill", "ske_f1", "SkE-F1"),
    ("skill", "svr", "SVR"),
    ("cost", "calls", "Calls"),
    ("cost", "calls_per_success", "C/S"),
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_main_results() -> dict[str, Any]:
    return load_json(RESULTS_ROOT / "main_aggregate_results.json")


def load_main_manifest() -> dict[str, Any]:
    return load_json(MANIFEST_ROOT / "main_results_manifest.json")


def load_ablation_manifest() -> dict[str, Any]:
    return load_json(MANIFEST_ROOT / "ablation_manifest.json")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_checksums() -> None:
    paths = sorted(
        path
        for path in PAPER_ROOT.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS" and "__pycache__" not in path.parts
    )
    lines = []
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(PAPER_ROOT)}")
    (PAPER_ROOT / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def value_at(row: dict[str, Any], group: str, metric: str, condition: str) -> float | None:
    return row[group][metric][condition]


def configuration_label(row: dict[str, Any]) -> str:
    return f"{row['harness']} {row['model']}"


def flatten_main_results(data: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for order, row in enumerate(data["rows"], start=1):
        for condition_order, condition in enumerate(CONDITIONS):
            flat: dict[str, Any] = {
                "configuration_order": order,
                "configuration": configuration_label(row),
                "harness": row["harness"],
                "model": row["model"],
                "condition_order": condition_order,
                "condition": condition,
            }
            for group, metric, _ in METRICS:
                flat[metric] = value_at(row, group, metric, condition)
            output.append(flat)
    return output


def mean_non_null(values: Iterable[float | None]) -> float | None:
    kept = [value for value in values if value is not None]
    return statistics.mean(kept) if kept else None


def pearson_r(x: list[float], y: list[float]) -> float:
    if len(x) != len(y) or len(x) < 3:
        raise ValueError("Pearson correlation requires equally sized samples")
    x_mean = statistics.mean(x)
    y_mean = statistics.mean(y)
    numerator = sum(
        (x_value - x_mean) * (y_value - y_mean) for x_value, y_value in zip(x, y, strict=True)
    )
    denominator = math.sqrt(
        sum((value - x_mean) ** 2 for value in x) * sum((value - y_mean) ** 2 for value in y)
    )
    if denominator == 0:
        raise ValueError("Pearson correlation is undefined")
    return numerator / denominator


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    max_iterations = 200
    epsilon = 3e-14
    floor = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < floor:
        d = floor
    d = 1.0 / d
    h = d
    for iteration in range(1, max_iterations + 1):
        m2 = 2 * iteration
        aa = iteration * (b - iteration) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < floor:
            d = floor
        c = 1.0 + aa / c
        if abs(c) < floor:
            c = floor
        d = 1.0 / d
        h *= d * c
        aa = -((a + iteration) * (qab + iteration) * x / ((a + m2) * (qap + m2)))
        d = 1.0 + aa * d
        if abs(d) < floor:
            d = floor
        c = 1.0 + aa / c
        if abs(c) < floor:
            c = floor
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < epsilon:
            return h
    raise ArithmeticError("incomplete beta did not converge")


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if not 0.0 <= x <= 1.0:
        raise ValueError("x must be in [0, 1]")
    if x in (0.0, 1.0):
        return x
    factor = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return factor * _beta_continued_fraction(a, b, x) / a
    return 1.0 - (factor * _beta_continued_fraction(b, a, 1.0 - x) / b)


def pearson_two_sided_p(r_value: float, sample_size: int) -> float:
    degrees = sample_size - 2
    if degrees <= 0:
        raise ValueError("sample size must be at least 3")
    if abs(r_value) >= 1:
        return 0.0
    t_squared = r_value * r_value * degrees / (1.0 - r_value * r_value)
    x_value = degrees / (degrees + t_squared)
    return regularized_incomplete_beta(degrees / 2.0, 0.5, x_value)


def gain_correlations(
    data: dict[str, Any],
) -> dict[str, dict[str, float]]:
    baselines = [round(row["outcome"]["avg_at_3"]["baseline"], 1) for row in data["rows"]]
    output: dict[str, dict[str, float]] = {}
    for condition in ("self_route", "annotated_preload"):
        gains = [
            round(row["outcome"]["delta_percentage_points"][condition], 1) for row in data["rows"]
        ]
        r_value = pearson_r(baselines, gains)
        output[condition] = {
            "r": r_value,
            "p": pearson_two_sided_p(r_value, len(baselines)),
        }
    return output


def exact_mcnemar_p(fixed: int, regressed: int) -> float:
    discordant = fixed + regressed
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, index) for index in range(min(fixed, regressed) + 1)) / (
        2**discordant
    )
    return min(1.0, 2.0 * tail)


def bootstrap_loss_ci(
    reference: list[int],
    ablated: list[int],
    seed: int,
    iterations: int,
) -> tuple[float, float]:
    differences = [target - source for source, target in zip(reference, ablated, strict=True)]
    rng = random.Random(seed)
    size = len(differences)
    draws = sorted(
        sum(differences[rng.randrange(size)] for _ in range(size)) / size for _ in range(iterations)
    )
    delta_low = draws[int(0.025 * iterations)]
    delta_high = draws[min(iterations - 1, int(0.975 * iterations))]
    return -delta_high, -delta_low


def compute_ablation_results() -> list[dict[str, Any]]:
    manifest = load_ablation_manifest()
    path = RESULTS_ROOT / "ablation_paired_outcomes.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        source_rows = list(csv.DictReader(stream))
    output: list[dict[str, Any]] = []
    for order, ablation in enumerate(manifest["ablations"], start=1):
        rows = [row for row in source_rows if row["ablation_id"] == ablation["id"]]
        reference = [int(row["reference_strict_success"]) for row in rows]
        target = [int(row["ablated_strict_success"]) for row in rows]
        if len(rows) != manifest["task_count"]:
            raise ValueError(
                f"{ablation['id']} has {len(rows)} paired tasks, expected {manifest['task_count']}"
            )
        reference_rate = statistics.mean(reference)
        target_rate = statistics.mean(target)
        loss = reference_rate - target_rate
        ci_low, ci_high = bootstrap_loss_ci(
            reference,
            target,
            seed=ablation["bootstrap_seed"],
            iterations=manifest["bootstrap_iterations"],
        )
        fixed = sum(
            source == 0 and result == 1 for source, result in zip(reference, target, strict=True)
        )
        regressed = sum(
            source == 1 and result == 0 for source, result in zip(reference, target, strict=True)
        )
        output.append(
            {
                "table_order": order,
                "ablation_id": ablation["id"],
                "ablation": ablation["label"],
                "reference_condition": ablation["reference_condition"],
                "paired_tasks": len(rows),
                "reference_sr": reference_rate * 100,
                "ablated_sr": target_rate * 100,
                "sr_loss": loss * 100,
                "ci_low": ci_low * 100,
                "ci_high": ci_high * 100,
                "fixed_count": fixed,
                "regressed_count": regressed,
                "unchanged_count": len(rows) - fixed - regressed,
                "mcnemar_exact_p": exact_mcnemar_p(fixed, regressed),
            }
        )
    return output


def latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(character, character) for character in value)
