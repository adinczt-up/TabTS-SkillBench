#!/usr/bin/env python3
"""Validate the declared answer contract without consulting Gold values."""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

MARKER = re.compile(r"(?im)^\s*(?:\*\*)?(?:final\s+answer|answer|total|\u6700\u7ec8\u7b54\u6848|\u7b54\u6848)(?:\*\*)?\s*[:\uff1a]\s*(.+?)\s*$")


def marker_payload(text: str) -> str:
    found = MARKER.findall(text)
    return found[-1].strip() if found else ""


def extract_json(text: str):
    decoder = json.JSONDecoder()
    candidates = []
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, end = decoder.raw_decode(text[index:])
            candidates.append((index + end, value))
        except json.JSONDecodeError:
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def normalize_label(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


def mapped_fields(items: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError("evidence field maps must use output_field=evidence_field")
        output_field, evidence_field = item.split("=", 1)
        result[output_field.strip()] = evidence_field.strip()
    return result


def evidence_equal(actual: Any, expected: Any, round_digits: int | None) -> bool:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if round_digits is not None:
            return round(float(actual), round_digits) == round(float(expected), round_digits)
        return float(actual) == float(expected)
    return normalize_label(actual) == normalize_label(expected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--answer", required=True, type=Path)
    parser.add_argument("--mode", choices=["free_form", "numeric", "multiple_choice", "yes_no", "json_array", "json_object"], default="free_form")
    parser.add_argument("--options", nargs="*", default=[])
    parser.add_argument("--required-fields", nargs="*", default=[])
    parser.add_argument("--key-fields", nargs="*", default=[])
    parser.add_argument("--allow-extra-fields", action="store_true")
    parser.add_argument(
        "--canonical-values",
        type=Path,
        help="JSON object mapping output fields to canonical labels extracted from source dimension tables.",
    )
    parser.add_argument("--canonical-fields", nargs="*", default=[])
    parser.add_argument("--require-final-marker", action="store_true")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--evidence-rows-key", default="selected_rows")
    parser.add_argument("--evidence-field-map", nargs="*", default=[])
    parser.add_argument("--round-digits", type=int)
    args = parser.parse_args()

    text = args.answer.read_text(encoding="utf-8-sig").strip()
    final = marker_payload(text)
    result = {"valid": True, "failure_state": "", "final_segment": final or None, "extracted": None, "errors": []}

    if args.mode in {"json_array", "json_object"}:
        value = extract_json(text)
        expected_type = list if args.mode == "json_array" else dict
        if not isinstance(value, expected_type):
            result.update(valid=False, failure_state="invalid_json_contract")
        else:
            rows = value if isinstance(value, list) else [value]
            if any(not isinstance(row, dict) for row in rows):
                result.update(valid=False, failure_state="invalid_json_contract")
            else:
                required = set(args.required_fields)
                for index, row in enumerate(rows):
                    fields = set(row)
                    missing = sorted(required - fields)
                    extra = sorted(fields - required) if required and not args.allow_extra_fields else []
                    if missing or extra:
                        result["errors"].append({"row": index, "missing": missing, "extra": extra})
                if args.key_fields:
                    keys = [tuple(str(row.get(field, "")).strip().casefold() for field in args.key_fields) for row in rows]
                    if len(set(keys)) != len(keys):
                        result["errors"].append("duplicate key rows")
                if args.canonical_fields:
                    if args.canonical_values is None:
                        result["errors"].append("canonical fields require --canonical-values")
                    else:
                        canonical_payload = json.loads(args.canonical_values.read_text(encoding="utf-8-sig"))
                        if not isinstance(canonical_payload, dict):
                            raise TypeError("canonical-values must contain a JSON object")
                        for field in args.canonical_fields:
                            values = canonical_payload.get(field)
                            if not isinstance(values, list) or not values:
                                result["errors"].append({"field": field, "error": "missing canonical reference values"})
                                continue
                            normalized = {normalize_label(item) for item in values}
                            for index, row in enumerate(rows):
                                if field not in row:
                                    continue
                                if normalize_label(row[field]) not in normalized:
                                    result["errors"].append(
                                        {"row": index, "field": field, "error": "noncanonical entity label", "actual": row[field]}
                                    )
                if args.evidence:
                    evidence_payload = json.loads(args.evidence.read_text(encoding="utf-8-sig"))
                    evidence_rows = evidence_payload.get(args.evidence_rows_key) if isinstance(evidence_payload, dict) else None
                    if not isinstance(evidence_rows, list) or any(not isinstance(row, dict) for row in evidence_rows):
                        result["errors"].append("invalid structured evidence rows")
                    else:
                        field_map = mapped_fields(args.evidence_field_map)
                        if len(rows) != len(evidence_rows):
                            result["errors"].append({"error": "result_set_incomplete", "answer_rows": len(rows), "evidence_rows": len(evidence_rows)})
                        for index, (row, evidence_row) in enumerate(zip(rows, evidence_rows)):
                            for field in required:
                                evidence_field = field_map.get(field, field)
                                if field not in row or evidence_field not in evidence_row:
                                    result["errors"].append({"row": index, "field": field, "error": "missing_evidence_field"})
                                elif not evidence_equal(row[field], evidence_row[evidence_field], args.round_digits):
                                    result["errors"].append({"row": index, "field": field, "error": "evidence_mismatch", "actual": row[field], "expected": evidence_row[evidence_field]})
                if result["errors"]:
                    label_error = any(
                        isinstance(error, dict) and error.get("error") == "noncanonical entity label"
                        for error in result["errors"]
                    )
                    evidence_error = any(
                        isinstance(error, dict) and error.get("error") in {"evidence_mismatch", "result_set_incomplete", "missing_evidence_field"}
                        for error in result["errors"]
                    )
                    result.update(
                        valid=False,
                        failure_state="noncanonical_entity_label" if label_error else "evidence_mismatch" if evidence_error else "missing_or_extra_fields",
                    )
                result["extracted"] = value
    elif args.require_final_marker and not final:
        result.update(valid=False, failure_state="missing_final_marker")
    elif args.mode == "multiple_choice":
        segment = final or next((line.strip() for line in reversed(text.splitlines()) if line.strip()), "")
        labels = args.options or list("ABCDE")
        found = [label for label in labels if re.search(rf"(?i)(?:^|\s|\*){re.escape(label)}\s*[.):\u3001\uff1a]", segment)]
        if len(found) != 1:
            result.update(valid=False, failure_state="missing_or_multiple_option_labels", extracted=found)
        else:
            result["extracted"] = found[0]
    elif args.mode == "numeric":
        segment = final if final else text if len(text) <= 300 else ""
        numbers = re.findall(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?", segment)
        if not numbers:
            result.update(valid=False, failure_state="missing_final_numeric_value")
        else:
            result["extracted"] = numbers[-1]
    elif args.mode == "yes_no":
        segment = final or next((line.strip() for line in reversed(text.splitlines()) if line.strip()), "")
        found = re.match(r"(?i)\s*(yes|no)\b", segment)
        if not found:
            result.update(valid=False, failure_state="missing_final_yes_no")
        else:
            result["extracted"] = found.group(1).lower()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
