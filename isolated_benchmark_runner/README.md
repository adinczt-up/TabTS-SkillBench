# Isolated Benchmark Runner

This folder contains a small runner for executing `datasets/task.json` tasks in
fresh nanobot workspaces. It is designed for skill on/off comparisons without
cross-task memory or skill contamination.

## What It Does

- Creates a new run directory under `runs/<task_id>/<skill_mode>/<run_id>/`.
- Creates a fresh nanobot workspace for every run.
- Copies only the task data assets into `workspace/datasets/`.
- Copies task-declared skills only when `--skill-mode on` is used.
- Generates a run-local `config.json` with:
  - `tools.web.enable=false`
  - `tools.restrictToWorkspace=true`
  - `tools.my.enable=false`
  - `idleCompactAfterMinutes=0`
  - built-in skills hidden via `disabledSkills`
- Can optionally execute every turn through nanobot.
- Writes evaluator-friendly unified outputs:
  - `final_output.md`
  - `final_output.json` when the final answer is parseable JSON
  - `task_result.json`
  - `responses.jsonl`
- Saves per-turn response files and, for CLI backend, stdout/stderr logs.
- Checks that no new unexpected skills were created during the run.

## Prepare Only

From the repository root:

```powershell
python isolated_benchmark_runner\run_isolated_task.py --skill-mode both
```

This creates both `skill_on` and `skill_off` isolated environments but does not
call the model. Without `--task-id` or `--all-tasks`, the runner uses the first
task in `task.json` for backward compatibility.

## Execute The Task

```powershell
python isolated_benchmark_runner\run_isolated_task.py --skill-mode on --execute
python isolated_benchmark_runner\run_isolated_task.py --skill-mode off --execute
```

By default the runner uses the direct Python backend and captures clean
`response.content`, avoiding terminal formatting in benchmark outputs.

You can still force the CLI backend:

```powershell
python isolated_benchmark_runner\run_isolated_task.py --skill-mode on --execute --backend cli
```

The CLI backend calls `python -m nanobot agent` and additionally stores
stdout/stderr logs.

## Multiple Tasks

List task ids:

```powershell
python isolated_benchmark_runner\run_isolated_task.py --list-tasks
```

Run selected tasks:

```powershell
python isolated_benchmark_runner\run_isolated_task.py `
  --task-id task_company_weekly_order_risk,task_company_weekly_sales_performance `
  --skill-mode both `
  --run-id exp_001 `
  --execute
```

Run every task in `task.json`:

```powershell
python isolated_benchmark_runner\run_isolated_task.py --all-tasks --skill-mode both --run-id exp_001 --execute
```

## Provider Config

By default the runner imports provider/model settings from:

```text
%USERPROFILE%\.nanobot\config.json
```

Use another base config with:

```powershell
python isolated_benchmark_runner\run_isolated_task.py --base-config path\to\config.json --skill-mode on
```

Only provider settings and agent default model-related settings are copied; the
workspace, memory, sessions, tools, channels, and skill controls are overridden
for isolation.

## Useful Options

```text
--task-json datasets\task.json
--task-id task_gaokao_shandong_2025_recommendation
--all-tasks
--list-tasks
--skill-mode on|off|both
--skill-policy available|required-read|force-use|preload
--run-id custom_name
--execute
--keep-going
--python path\to\python.exe
--backend direct|cli
```

`--skill-policy` only affects `skill_on`. `available`, `required-read`, and
`preload` use description-only skill stubs. `force-use` copies the full declared
task skill and marks `SKILL.md` with `always: true`, so nanobot loads it into
the system prompt as an Active Skill on every turn. Task instructions and local
data take precedence on conflicts.

`--keep-going` continues later turns if a prior turn fails. Without it, the
runner stops on the first non-zero nanobot exit code.

`--task-id` can be repeated or comma-separated.

## Unified Outputs

After `--execute`, each run directory contains:

```text
final_output.md
final_output.json       # only when the final answer can be parsed as JSON
task_result.json
skill_usage.json
responses.jsonl
outputs/
  turn_00.response.md
  turn_01.response.md
  ...
```

Use `final_output.json` for JSON-based evaluators when present. Otherwise use
`final_output.md`. `task_result.json` always exists and includes metadata,
per-turn records, skill usage, and the final output either as parsed JSON or raw
text. `skill_usage.json` records whether skill descriptions were preloaded,
whether full skills were loaded into the system prompt, and whether the session
trace contains `read_file` calls for allowed `SKILL.md` files.

## Scoring

Score a completed run against `task.json` turn-level `score_points`.
The default mode is LLM judging:

```powershell
python isolated_benchmark_runner\evaluate_task_outputs.py --run-root runs\<task_id>\skill_on\<run_id>
```

The evaluator normally infers `task_id` from the run `manifest.json`. It also
supports batch evaluation:

```powershell
python isolated_benchmark_runner\evaluate_task_outputs.py --run-id exp_001 --skill-mode both --all-tasks
```

For batch evaluation, each run still gets its own `evaluation_result.json` and
`evaluation_report.md`; an `evaluation_summary.json/.md` is also written.

Override the judge provider/model if needed:

```powershell
python isolated_benchmark_runner\evaluate_task_outputs.py `
  --run-root runs\<task_id>\skill_on\<run_id> `
  --judge-config path\to\config.json `
  --judge-provider volcengineCodingPlan `
  --judge-model ark-code-latest
```

Use the old deterministic matcher with:

```powershell
python isolated_benchmark_runner\evaluate_task_outputs.py --judge rule --run-root runs\<task_id>\skill_on\<run_id>
```

The evaluator writes:

```text
evaluation_result.json
evaluation_report.md
```

Each score point is worth 1 point. The result includes per-point pass/fail
details, judge reasons, per-turn subtotals, and an overall score/accuracy.
LLM judge no longer falls back to rule matching by default; add
`--rule-fallback` if you want that behavior.

## Notes

- Use `nanobot agent`, not `nanobot gateway`, for these runs. Gateway registers
  Dream as a background job; Dream can write memory and may create skills.
- The generated workspace is the isolation boundary. Delete a run folder to
  remove all sessions, memory, copied data, logs, and generated files for that
  run.
- For fair skill comparison, run `skill_on` and `skill_off` with the same model,
  same task turns, and fresh run ids.
