#!/usr/bin/env python3
"""Validate waveform amplitude evidence and direction."""

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
    segments = data.get("segments", [])
    if len(segments) != 2:
        errors.append("exactly two segments are required")
    else:
        amplitudes = []
        for index, segment in enumerate(segments):
            amplitude = (float(segment["high"]) - float(segment["low"])) / 2.0
            amplitudes.append(amplitude)
            if not math.isclose(amplitude, float(segment["semi_amplitude"]), rel_tol=1e-8, abs_tol=1e-8):
                errors.append(f"segment {index} amplitude cannot be recomputed")
        if not errors and min(amplitudes) > 0:
            relative = (amplitudes[1] - amplitudes[0]) / max(amplitudes)
            tolerance = float(data.get("tolerance", 0.15))
            expected = "same" if abs(relative) <= tolerance else ("increase" if relative > 0 else "decrease")
            if data.get("decision") != expected:
                errors.append("decision contradicts amplitudes and tolerance")
    if data.get("failure_state") and data.get("final_claim"):
        errors.append("final claim prohibited under failure state")
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
