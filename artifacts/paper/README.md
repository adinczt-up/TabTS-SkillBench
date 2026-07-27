# Paper result reproduction

This package contains the authoritative aggregate results used by the paper and
the task-paired outcomes used by its component-ablation analysis. It rebuilds:

- Table 2;
- Table 3;
- Figures 4, 5, 7, and 8;
- the headline outcome, process, cost, and correlation values reported with
  those tables and figures.

Only the final 251-task benchmark is represented. The release contains no raw
model responses, prompts, reasoning, shell commands, execution traces, dataset
rows, workspace paths, credentials, or private service endpoints.

## Reproduce

From the repository root:

```bash
python scripts/paper/reproduce_all.py
python tools/verify_paper_results.py
```

Generated tables, figures, and the derived summary are written to
`artifacts/paper/reproduced/`.

## Inputs

- `results/main_aggregate_results.json` is the canonical structured source for
  the nine model-harness configurations and three Skill conditions.
- `results/main_aggregate_results.csv` is a human-readable equivalent.
- `results/ablation_paired_outcomes.csv` contains the six task-paired binary
  comparisons needed to recompute Table 3.
- `manifests/` fixes the experiment dimensions, metric units, output inventory,
  and paper-facing verification targets.

## Determinism

Table 3 uses the published fixed bootstrap seeds and 5,000 task-level resamples.
Figure 8 computes each condition's Pearson statistic from the one-decimal
Table 2 values shown in the paper.
All SVG figures are generated without network access or external plotting
services.
