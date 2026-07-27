# TabTS-SkillBench 中文说明

> **Research release（`0.1.0`）。** 本仓库包含完整的 251 题 benchmark、
> evaluator、Skill library、统一数据准备流程和论文结果重建包。

本仓库包含 251 道多表时序分析任务、确定性 evaluator contract、Gold、Nanobot adapter
及 47-module Skill library。其中 43 个 Skill 含 executable script，25 个属于
benchmark-active routed Skills，23 个属于 required-execution Skills；这些数字口径不同。

公开任务位于 `benchmark/tasks/`，Gold 和完整 evaluator task 位于
`benchmark/evaluator/`。正式运行时，pipeline 会生成仅含执行必要字段的 runner task
view；默认使用普通复制 staging 数据并校验 SHA-256。Gold-sensitive formal run 必须在
Linux 上启用 Bubblewrap，sandbox 不可用时应直接失败。

`benchmark/manifests/task_set_251.json` 中记录的 251 道题构成当前正式发布的完整
TabTS-SkillBench task set。对外报告时应注明 task-set version，并保持题目成员不变。

当前仓库不打包或再分发六个上游数据源。统一的数据准备流程为：

```bash
tabts-bench data guide
tabts-bench data prepare
tabts-bench data verify
```

工具不会代表用户接受第三方条款，也不会自动下载标记为
`user_download_required` 的数据。H&M 和 Event 必须由用户本人登录 Kaggle、阅读并接受
对应竞赛规则，再通过官方页面或自己的已认证 Kaggle CLI 下载。逐数据源许可、来源布局和
准备指导见 `data_sources.yaml`、`DATA_LICENSES.md` 和 `data/README.md`。

论文九个 model-harness 配置的权威三轮汇总结果、六项 paired ablation，以及
Table 2、Table 3、Figures 4/5/7/8 的确定性重建脚本位于 `artifacts/paper/`：

```bash
python scripts/paper/reproduce_all.py
python tools/verify_paper_results.py
```

该复现包只包含最终 251 题的脱敏汇总和必要的二元 paired outcomes，不包含原始模型
输出、prompt、reasoning、命令、trace、数据行、凭证或私有服务地址。
