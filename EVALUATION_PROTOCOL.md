# Evaluation Protocol

## Scope

This protocol applies to scored TabTS-SkillBench runs. A run is only comparable
when task membership, evaluator contracts, model profile, harness version,
condition, repeat index, and input hashes are recorded.

The public condition name is `annotated_preload`. The runtime identifier
`oracle_skill` is a compatibility alias and must not be interpreted as exposing
Gold answers or an Oracle solver to the agent.

## Agent/evaluator boundary

The agent runner may receive only the generated runner task view, staged task
tables, and Skills allowed by the condition. Evaluator tasks, Gold,
Oracle SQL, evaluator-only metadata, and the repository checkout must not be mounted
inside the agent sandbox.

Formal Nanobot runs use `runtime.sandbox: bwrap`. If Bubblewrap is unavailable,
execution must fail closed. `tools.restrictToWorkspace` alone is not considered
a sufficient Gold-isolation boundary.

## Input staging

The release default is `asset_mode: copy`. Source and staged files are checked
against the task-declared SHA-256 value. Hard links are not permitted for formal
scores because an agent write could mutate shared benchmark inputs.

## Attempts, retries, and repair

- One task attempt contributes one result to the denominator.
- Whole-task retries are allowed only for classified infrastructure failures,
  such as provider rate limits, connection failures, or missing/corrupt runner
  output.
- Output-format or answer-contract failures are agent failures and must not
  trigger a whole-task retry.
- At most one format-only repair turn may be used. It must not call tools,
  inspect files, recompute, or introduce new analysis.
- Reports must separate raw success, after-repair success, repair rate,
  infrastructure retry rate, and attempt count.

`partial_credit_score` is retained as the paper-compatible field-recall
diagnostic. New analyses should additionally report `partial_credit_f1`,
`row_f1`, and `field_f1`; these precision-aware metrics penalize extra rows,
duplicate keys, and extra fields.

## Task-set identity

The 251 tasks listed in `benchmark/manifests/task_set_251.json` are the complete
release task set. Every result must record the task-set version and must use the
exact released membership unless it is explicitly labeled as a separate
ablation.

## Minimum run manifest

Each reported experiment must record:

- repository commit and dirty-state flag;
- evaluator contract and task-set hashes;
- exact model identifier, provider, region, and call date;
- framework and adapter versions;
- condition and independent repeat index;
- model parameters and retry/repair policy;
- input asset hashes;
- normalized per-task results, failures, and denominator.
