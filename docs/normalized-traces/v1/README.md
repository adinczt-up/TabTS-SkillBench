# Normalized trace v1 synthetic examples

These three records are **synthetic contract and scoring examples**. They are
not paper experiment runs, are not derived from model sessions, and contain no
benchmark dataset rows, prompts, reasoning, or executed commands. They cannot
be used to validate or reconstruct any number reported in the paper.

The package contains:

- `normalized-trace.schema.json`: JSON Schema Draft 2020-12 for the flattened
  output of `benchmark_eval.schema.TraceRecord.to_dict()`;
- `synthetic-normalized-traces.jsonl`: exactly three synthetic traces labeled
  Nanobot, Codex, and Claude Code, covering success, a process-operation
  mismatch, and an answer mismatch; and
- `fixture-manifest.json`: the explicit `synthetic: true` labels, invented
  scoring contract, outcome classes, and expected scorer outputs.

The harness names are labels used only to demonstrate framework-agnostic
normalization. They do not claim that any named harness produced these records.
All table names, answer values, identifiers, tool results, and the scoring
contract are invented for this package.

All three harness executions use `status: completed`; the examples isolate
scoring outcomes rather than runtime failures. The process-error case returns
the invented correct answer but records the wrong temporal operation. The
answer-error case records the expected operation but returns an invented wrong
value.

Run the executable contract checks with:

```bash
python -m pytest -q tests/test_normalized_trace_examples.py
```

The test validates every JSONL record against the versioned schema, checks that
the schema keys stay synchronized with `TraceRecord`, round-trips each record
through `TraceRecord.from_dict()`, invokes the existing `score_trace()` pipeline,
and compares the outputs with `fixture-manifest.json`.
