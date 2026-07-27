from __future__ import annotations

import csv
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_reproduce_all_outputs(tmp_path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "scripts/paper/reproduce_all.py",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=True,
    )
    with (tmp_path / "table2.csv").open(encoding="utf-8", newline="") as stream:
        table2 = list(csv.DictReader(stream))
    assert len(table2) == 10
    assert table2[-1]["Avg@3"] == "38.4/57.1/56.5"
    assert table2[-1]["Δ"] == "—/+18.6/+18.1"
    assert table2[-1]["Calls"] == "8.81/20.25/22.43"

    with (tmp_path / "table3.csv").open(encoding="utf-8", newline="") as stream:
        table3 = list(csv.DictReader(stream))
    assert len(table3) == 6
    assert table3[0]["Ablation"] == "No Temporal Skills"
    assert table3[0]["SR drop"] == "15.9"
    assert table3[0]["95% CI"] == "[9.6, 22.3]"

    for number in (4, 5, 7, 8):
        ET.parse(tmp_path / f"figure{number}.svg")

    summary = json.loads((tmp_path / "paper_summary.json").read_text())
    assert summary["task_count"] == 251
    assert summary["execution_count"] == 20331


def test_paper_result_verifier() -> None:
    result = subprocess.run(
        [sys.executable, "tools/verify_paper_results.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "PASS paper result reproduction" in result.stdout
