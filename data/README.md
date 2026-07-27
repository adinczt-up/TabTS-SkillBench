# Benchmark data preparation

TabTS-SkillBench does not redistribute a combined copy of the six upstream
datasets. Users obtain each source under its own terms, materialize the
documented source layout, and then run one local preparation command.

The tooling never accepts third-party terms on a user's behalf and never
automatically downloads sources marked `user_download_required`.

## 1. Review source-specific instructions

```bash
tabts-bench data guide
```

For one source:

```bash
tabts-bench data guide --datasets rel-hm
```

The authoritative machine-readable registry is `../data_sources.yaml`.

## 2. Obtain and prepare upstream inputs

Use `data/sources/` by default. The preparation command searches recursively
for the layouts recorded in `data_sources.yaml`, so an existing audited
RelBench cache can be copied or symlinked beneath this directory.

H&M and Event require the user to sign in to Kaggle, personally review and
accept the applicable competition rules, download through the official Kaggle
interface or their own authenticated Kaggle CLI, and materialize the RelBench
Parquet cache. Do not commit or redistribute those archives or derived tables
unless you have separate written permission.

The released transformations were developed against the RelBench v1.1.0 source
definition. Install it only in a dedicated data-preparation environment:

```bash
python -m pip install "relbench==1.1.0"
```

For `rel-f1` and `rel-stack`, RelBench can materialize its versioned cache:

```bash
python -c 'from relbench.datasets import get_dataset; get_dataset("rel-f1", download=True).get_db()'
python -c 'from relbench.datasets import get_dataset; get_dataset("rel-stack", download=True).get_db()'
```

For H&M and Event, do not use `download=True`. After personally accepting the
Kaggle rules and downloading the archives, place them in the exact working
layouts printed by `tabts-bench data guide`, then call
`get_dataset(..., download=False).get_db()`. This ensures the benchmark does
not bypass the upstream access flow.

Locate the resulting RelBench cache with:

```bash
python -c 'import pooch; print(pooch.os_cache("relbench"))'
```

Copy or symlink the required dataset cache beneath `data/sources/`, or pass the
cache directory directly:

```bash
tabts-bench data prepare --source-root /path/to/relbench/cache
```

## 3. Standardize and verify

Install the data dependencies:

```bash
python -m pip install -e ".[benchmark]"
```

Prepare every source:

```bash
tabts-bench data prepare
```

Prepare selected sources:

```bash
tabts-bench data prepare --datasets rel-f1 bdg2
```

The default output is:

```text
data/skillmtts/standardized/<dataset>/tables/*
```

`data prepare` checks that all required upstream inputs exist before running.
It then calls the deterministic standardizer, verifies outputs against
`../benchmark/manifests/assets_sha256.json`, and writes
`data/skillmtts/standardized/preparation_report.json`.

Re-run verification without changing data:

```bash
tabts-bench data verify
```

Formal evaluation requires all 39 released asset hashes to match. A missing
file or hash mismatch is an error, not a warning.
