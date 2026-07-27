# Contributing to TabTS-SkillBench

Small, reviewable pull requests are preferred.

## Before opening a pull request

1. Create a focused branch and avoid unrelated formatting or refactors.
2. Do not commit API keys, private traces, licensed datasets, or machine-specific
   paths.
3. Preserve the released 251-task membership and its versioned task-set manifest.
4. Keep runner-visible task inputs separate from evaluator-only contracts, Gold,
   routing labels, and Oracle SQL.
5. Add or update tests for behavioral changes.

Run the local release checks:

```bash
python -m pip install -e ".[dev]"
ruff check benchmark_eval isolated_benchmark_runner tools tests
python tools/verify_public_release.py --root .
python -m benchmark_eval.cli validate \
  --experiment configs/benchmark.yaml \
  --models-config configs/models.example.yaml
python -m pytest -q
python -m build --wheel --sdist
```

## Changes to tasks, Skills, or scoring

A proposal that changes task membership, Gold, a contract, a Skill route, retry
policy, answer repair, or a metric must describe:

- the scientific reason for the change;
- the affected task IDs or Skill names;
- whether published scores remain comparable;
- how the change was validated;
- any version bump or migration required.

Do not silently replace existing tasks or overwrite published results.

## Dataset contributions

Add exact source, version, retrieval date, upstream license, redistribution
status, required attribution, transformation path, and checksums to
`data_sources.yaml`. Dataset redistribution requires explicit approval; a public
download page alone is not sufficient evidence.

## Adapter contributions

Adapters must emit the normalized trace contract, distinguish infrastructure
retries from agent failures, and execute formal evaluations in a filesystem
sandbox that does not expose evaluator-only files.

## Reporting security issues

Follow `SECURITY.md`. Do not open a public issue for a suspected sandbox escape,
Gold leak, secret exposure, or arbitrary-code-execution vulnerability.
