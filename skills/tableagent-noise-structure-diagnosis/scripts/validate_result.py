#!/usr/bin/env python3
"""Validate noise evidence and decision without a gold label."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    errors: list[str] = []
    scale = float(data.get("scale_reference", 0))
    residual = float(data.get("residual_scale", 0))
    relative = residual / scale if scale > 0 else math.inf
    if not math.isclose(relative, float(data.get("relative_residual_scale", math.nan)), rel_tol=1e-8, abs_tol=1e-8):
        errors.append("relative residual scale cannot be recomputed")
    expected_presence = "none" if relative <= float(data.get("relative_noise_threshold", 0.02)) else "meaningful"
    if data.get("noise_presence") != expected_presence:
        errors.append("noise presence contradicts residual scale")
    target = data.get("target")
    expected = {
        "raw_white_noise": "yes" if data.get("dependence") == "white" else "no",
        "presence": data.get("noise_presence"),
        "dependence": data.get("dependence"),
        "noise_type": data.get("noise_type"),
        "variance_form": data.get("variance_form"),
    }.get(target)
    if target == "raw_white_noise":
        if data.get("analysis_series") != "raw_centered" or data.get("signal_model") != "raw":
            errors.append("raw white-noise target must analyze the centered raw series")
    if not data.get("failure_state") and data.get("decision") != expected:
        errors.append("decision does not follow requested target")
    if data.get("failure_state") and data.get("final_claim"):
        errors.append("final claim prohibited under failure state")
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
