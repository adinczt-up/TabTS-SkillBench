# Changelog

All notable release changes will be documented here.

## [0.1.0] - 2026-07-27

### Added

- Unified `tabts-bench data guide|prepare|verify` workflow.
- Machine-checkable source layouts, pinned upstream evidence where available,
  user-controlled Kaggle acquisition guidance, and preparation provenance
  reports with source and output SHA-256 values.
- Authoritative aggregate results for the paper's nine model-harness
  configurations, task-paired outcomes for six ablations, and deterministic
  reconstruction of the reported tables and figures.
- Sanitized runner task view separated from evaluator-only task metadata.
- Fail-closed Bubblewrap mode for formal Linux evaluation.
- Input asset copy staging with pre/post SHA-256 verification.
- Explicit raw-versus-repaired scoring and infrastructure retry metrics.
- Precision-aware partial-credit diagnostics.
- Release verifier, CI workflow, evaluation protocol, security policy, data
  provenance registry, Benchmark Card, and community templates.
- Installable `tabts-skillbench` wheel and source distribution.

### Changed

- Default asset staging changed from hard links to independent copies.
- Public condition name changed to `annotated_preload`; `oracle_skill` remains an
  internal compatibility alias.
- Whole-task retries are restricted to infrastructure failures.
- Repository metadata and Docker image now describe the benchmark rather than
  the upstream Nanobot gateway.

### Known limitations

- Upstream datasets are not bundled and remain governed by their source-specific
  licenses or competition terms.
- Paper-result reconstruction is aggregate-level; raw model runs and execution
  traces are not included.
