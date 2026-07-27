---
name: tableagent-two-period-volatility-change
description: Use when a validated group-period table asks for sample volatility separately before and after an explicit split, then signed or absolute change and group ranking. Requires unique group-period rows, a split, minimum periods on both sides, and ddof=1. Do not use for one-window volatility, rolling volatility, raw-row variance, quantile spread, or change in means.
---

# Two-Period Volatility Change

1. Reject duplicate group-period rows and parse the split at the declared frequency.
2. Assign periods `< split` to early and `>= split` to late unless the question says otherwise.
3. Require the declared minimum period count in both partitions.
4. Compute sample standard deviation (`ddof=1`) separately and `change=late-early` without rounding.
5. Rank on the requested signed or absolute raw change with deterministic group ties.
6. Answer only from evidence rows.

```bash
python skills/tableagent-two-period-volatility-change/scripts/execute_analysis.py --file prepared.parquet --group segment --time month --value metric --frequency month --split 2015-07 --min-early 2 --min-late 2 --top-k 3 --output skill_evidence/tableagent-two-period-volatility-change.json
```

Failure states: `duplicate_group_period`, `insufficient_early_periods`, `insufficient_late_periods`, `no_valid_groups`.
