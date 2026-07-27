# External Framework Adapter Contract

An external adapter command is configured under
`framework_options.<framework>.command`. The command receives:

- `BENCHMARK_FRAMEWORK`
- `BENCHMARK_MODEL`
- `BENCHMARK_MODEL_PROFILE`
- `BENCHMARK_CONDITION`
- `BENCHMARK_REPEAT`
- `BENCHMARK_TASK_JSON`
- `BENCHMARK_TASK_IDS`
- `BENCHMARK_DATA_ROOT`
- `BENCHMARK_SKILLS_ROOT`
- `BENCHMARK_OUTPUT_ROOT`
- `BENCHMARK_RUN_ID`

`BENCHMARK_TASK_JSON` points to the generated runner task view, not to the
evaluator task file. The wrapper must preserve this boundary and must not mount
the repository or evaluator directory into the agent environment.

For every requested task, write:

```text
<BENCHMARK_OUTPUT_ROOT>/<task_id>/<BENCHMARK_RUN_ID>/task_result.json
```

The JSON object must include `task_id`, `status`, `failure_reason`, and
`final_output`. Use `status: infrastructure_error` only for provider/runtime
failures eligible for retry. Output-contract failures are agent failures.
