# TabTS-SkillBench Benchmark Card

## Summary

TabTS-SkillBench evaluates whether data-analysis agents can select and execute
procedural Skills for multi-table temporal tasks. The current benchmark release
contains 251 tasks across 30 task families.

## Intended use

The benchmark is intended for:

- controlled research on Skill routing and execution;
- paired comparison of agent conditions under a fixed protocol;
- diagnosis of temporal reasoning, joins, entity universes, and output-contract
  failures;
- reproduction of the released paper aggregate results.

It is not intended to measure general intelligence, production safety, or
real-world business value.

## Conditions

- `baseline`: no benchmark Skill library.
- `self_route`: the agent chooses from the permitted Skill library.
- `annotated_preload`: the benchmark-annotated Skill is preloaded. This is not an
  Oracle condition; `oracle_skill` is retained only as an internal compatibility
  alias.

The release contains 47 Skill modules. Of these, 43 contain scripts, 25 are
used by the benchmark's routed condition, and 23 are required-execution Skills
for at least one released task.

## Task set

The 251 tasks listed in `benchmark/manifests/task_set_251.json` constitute the
complete released TabTS-SkillBench task set. The manifest versions the exact
membership used for comparable evaluation.

Scores must identify the task-set version. Any modification to task membership,
Gold, or contracts is a distinct benchmark version and requires an explicit
compatibility analysis.

## Data and licensing

The benchmark references six upstream data sources. Redistribution approval is
not complete for every source. `data_sources.yaml` records the current
source-level provenance and release gate; `DATA_LICENSES.md` explains the
restrictions. Users must not assume that the repository license covers upstream
data.

## Evaluation

Strict Success is the primary outcome. Diagnostic outputs include raw and
after-repair success, row/field precision and recall, partial-credit F1, repair
rates, and infrastructure retry rates.

Formal evaluation requires:

- runner-visible sanitized task input;
- evaluator-only Gold, contracts, routes, and Oracle material outside the
  runner filesystem;
- read-only Skill and data inputs where supported;
- a writable task scratch directory;
- a supported Bubblewrap sandbox on Linux;
- exact input checksum validation.

See `EVALUATION_PROTOCOL.md` for the normative protocol.

## Known limitations

- Some upstream sources require the user to accept source-specific terms and
  download data manually before running the unified preparation command.
- Process metrics are observable trace proxies and may miss behavior hidden
  inside generated helper code.
- Formal sandbox behavior has not yet been validated by a release canary in CI.
- Benchmark-specific copyright ownership and license grants are pending.

## Reporting results

Reports should include:

- repository version or commit;
- task-set name and hash;
- model and harness identifiers;
- condition, repeats, and decoding parameters;
- sandbox and asset-staging mode;
- raw and after-repair outcomes;
- infrastructure failures and retries;
- all exclusions and missing tasks.

Do not compare scores across changed task sets, Gold, contracts, or retry
policies without an explicit compatibility analysis.
