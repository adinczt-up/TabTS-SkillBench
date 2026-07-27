## Summary

Describe the focused change and why it is needed.

## Benchmark impact

- Affected task IDs or Skill names:
- Changes task membership, Gold, contracts, routing, metrics, retry policy, or
  result comparability: Yes / No
- Version or migration needed: Yes / No

## Validation

- [ ] `ruff check benchmark_eval isolated_benchmark_runner tools tests`
- [ ] `python tools/verify_public_release.py --root .`
- [ ] `python -m benchmark_eval.cli validate --experiment configs/benchmark.yaml --models-config configs/models.example.yaml`
- [ ] `python -m pytest -q`
- [ ] `python -m build --wheel --sdist`

## Safety

- [ ] Runner-visible inputs remain separated from evaluator-only material.
- [ ] No API keys, private traces, licensed datasets, or machine-specific paths
      are included.
- [ ] Dataset provenance and licensing metadata are updated when applicable.
