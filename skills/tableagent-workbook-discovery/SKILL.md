---
name: "tableagent-workbook-discovery"
description: "Use for local spreadsheet QA when multiple accessible workbooks or sheets exist and the relevant table is not explicitly known. Build a compact file, sheet, and header inventory and rank candidates by question terms. Do not use when the exact data asset is supplied, for remote search, or as a substitute for analysis."
---

# TableAgent Workbook Discovery

## Trigger Conditions

Use this skill when the task provides many local Excel/CSV files and the relevant file, sheet, or table must be discovered from the question.

## Disable Conditions

Do not use this skill when the prompt gives one explicit file and sheet, or when the answer does not require reading local tables.

## Steps

1. List available files under `workspace/datasets` recursively.
2. For each candidate spreadsheet, record only lightweight metadata first: relative path, file name, sheet names, used range size, and the first non-empty header/label rows.
3. Normalize text only for matching: lowercase ASCII, full-width to half-width, remove spaces, and keep original names for reporting.
4. Score candidate tables by overlap with the question's time terms, entity terms, metric terms, and operation terms.
5. Inspect only the top candidates deeply; if the first candidate has wrong headers or wrong time/entity coverage, move to the next candidate.
6. Keep a candidate log with `file`, `sheet`, `why_selected`, `why_rejected`, and `remaining_gap`.

## Output Format

When this skill affects the answer, keep an internal candidate list shaped as:

```json
[
  {"file": "...", "sheet": "...", "score_reason": "...", "status": "selected|rejected"}
]
```

Do not answer from file names alone. Use workbook contents as evidence.
