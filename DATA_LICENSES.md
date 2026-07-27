# Data Licenses and Redistribution Status

This repository does not redistribute standardized table binaries. Dataset
provenance, acquisition instructions, source layouts, and machine-readable
release gates are recorded in `data_sources.yaml`. Run
`tabts-bench data guide` before obtaining any upstream source.

Current status:

| Dataset | Upstream | Recorded license | Redistribution status |
|---|---|---|---|
| `azure-pdm` | Microsoft Azure Predictive Maintenance sample | Exact five-table snapshot license not yet confirmed | `review_required` |
| `bdg2` | Building Data Genome Project 2 v1.0 | CC BY-SA 4.0 | `local_preparation_only` |
| `rel-f1` | RelBench `rel-f1` / F1DB | CC BY 4.0 | `local_preparation_only` |
| `rel-stack` | RelBench `rel-stack` / Stack Exchange | CC BY-SA version depends on contribution date | `local_preparation_only` |
| `rel-hm` | H&M Kaggle competition | Competition-specific terms | `user_download_required` |
| `rel-event` | Event Recommendation Engine Kaggle competition | Competition-specific terms | `user_download_required` |

The RelBench software repository is MIT-licensed, but that software license
does not replace the terms governing each underlying dataset. H&M and Event
require the user to obtain the datasets through the corresponding Kaggle
competitions after personally reviewing and accepting the applicable rules.
The benchmark tooling does not log in, accept terms, or download these sources
on the user's behalf. Stack Exchange contributions span multiple CC BY-SA
versions based on contribution date.

Do not publish a combined data archive. A future redistribution decision
requires a pinned upstream version, retrieval date, raw checksum, verified
attribution text, and explicit approval for every included source. The current
supported workflow is user-managed acquisition under the upstream terms,
followed by deterministic local preparation and released-output hash
verification. This file is release engineering metadata, not legal advice.
