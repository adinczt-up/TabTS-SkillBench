---
name: tableagent-answer-validation
description: Use immediately before finalizing a spreadsheet or tabular time-series answer after structured evidence exists. Validate the requested answer contract, fields, canonical source entity labels, entity-row completeness, units, and recomputability. Supports free text, numeric, choice, yes/no, JSON object, and JSON array outputs. Do not use as the primary analysis method or with expected Gold values.
---

# Answer Validation

## Mechanical Procedure

1. Perform one bounded validation pass after the analysis artifact is complete.
2. Read the answer contract from the question: scalar, free text, choice, yes/no, JSON object, or JSON array.
3. Verify entities, metric roles, time window, selected rows, and units against retained evidence. Build canonical entity references directly from source dimension tables; never use Gold or a hand-written winner list.
4. Recompute final values from evidence. For extrema, assert selection used raw values and includes all and only required ties. When the analysis Skill emitted `selected_rows`, compare the proposed answer mechanically with those rows instead of transcribing values by hand.
5. For JSON output, emit exactly the requested fields, preserve numeric types, enforce unique key fields, and do not add explanatory rows. Entity fields must exactly match a canonical source label after Unicode and whitespace normalization; surnames, abbreviations, translations, and aliases are invalid unless the source label itself uses them.
6. For scalar output, build one terminal `Final Answer:` line. For JSON output, a plain or fenced JSON value is valid without that marker.
7. Run `scripts/validate_final_answer.py` with the matching mode and requested fields.
8. If invalid, repair formatting once without changing the analysis result. Do not call another analysis tool after successful validation.

## Commands

```bash
python skills/tableagent-answer-validation/scripts/validate_final_answer.py --answer answer.txt --mode numeric --require-final-marker
python skills/tableagent-answer-validation/scripts/validate_final_answer.py --answer answer.txt --mode json_array --required-fields entity year value --key-fields entity year --evidence skill_evidence/analysis.json --evidence-rows-key selected_rows --round-digits 4
python skills/tableagent-answer-validation/scripts/validate_final_answer.py --answer answer.txt --mode json_array --required-fields driver year value --key-fields driver year --canonical-values canonical_entities.json --canonical-fields driver
```

## Failure States

- `missing_final_marker`: add one scalar final line.
- `invalid_json_contract`: repair syntax or top-level type; do not change evidence.
- `missing_or_extra_fields`: emit exactly the requested schema.
- `duplicate_key_rows`: deduplicate only by returning the already-selected evidence rows; never average duplicates silently.
- `noncanonical_entity_label`: replace the label with the exact source-dimension label while preserving the selected entity ID and computed values.
- `unsupported_value`: no final claim until retained evidence reproduces it.
- `result_set_incomplete`: add omitted selected rows or remove rows not supported by the selection artifact.
- `evidence_mismatch`: copy the selected evidence rows again; do not manually recompute or reorder values.
