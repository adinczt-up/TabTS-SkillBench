#!/usr/bin/env python3
"""Recompute compact two-level change-point evidence from its source."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    observed = json.loads(args.input.read_text(encoding="utf-8-sig"))
    parameters = observed.get("parameters") or {}
    required = {"group", "time", "value", "frequency", "group_output_field", "time_output_field", "min_side", "top_k"}
    errors: list[str] = []
    if observed.get("status") != "ok" or not required <= parameters.keys() or not observed.get("input"):
        errors.append("invalid_evidence_contract")
    else:
        descriptor, temporary_name = tempfile.mkstemp(suffix=".json")
        os.close(descriptor)
        recomputed_path = Path(temporary_name)
        recomputed_path.unlink(missing_ok=True)
        try:
            command = [
                sys.executable, str(Path(__file__).with_name("execute_analysis.py")),
                "--file", observed["input"], "--group", parameters["group"],
                "--time", parameters["time"], "--value", parameters["value"],
                "--frequency", parameters["frequency"],
                "--group-output-field", parameters["group_output_field"],
                "--time-output-field", parameters["time_output_field"],
                "--min-side", str(parameters["min_side"]), "--top-k", str(parameters["top_k"]),
                "--output", str(recomputed_path),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                errors.append("source_recomputation_failed")
            else:
                recomputed = json.loads(recomputed_path.read_text(encoding="utf-8"))
                if recomputed.get("selected_rows") != observed.get("selected_rows"):
                    errors.append("selected_rows_recomputation_mismatch")
        finally:
            recomputed_path.unlink(missing_ok=True)
    report = {"status": "ok" if not errors else "failed", "valid": not errors, "errors": errors, "recomputed_from_source": not errors}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
