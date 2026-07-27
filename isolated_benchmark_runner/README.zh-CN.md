# 隔离式 Nanobot Benchmark Runner

这个文件夹提供一个小型 runner，用来把 `datasets/task.json` 里的任务放进全新的 nanobot workspace 中运行。核心目标是做 skill 开关对比，同时避免不同任务、不同轮次实验之间出现 memory、session、skill 污染。

## 它会做什么

- 每次运行都会新建目录：`runs/<task_id>/<skill_mode>/<run_id>/`。
- 每个 run 都有独立的 `workspace/` 和 `config.json`。
- 只复制当前任务声明的数据文件到 `workspace/datasets/`。
- `--skill-mode on` 时，只复制任务声明的 skill。
- `--skill-mode off` 时，不复制任何任务 skill，并在配置里禁用它。
- 禁用联网工具：`tools.web.enable=false`。
- 限制文件访问在 workspace 内：`tools.restrictToWorkspace=true`。
- 禁用 `my`、图片生成、MCP 等额外工具入口。
- 默认不执行模型，只准备环境；加 `--execute` 才会逐轮调用 nanobot。
- 执行后会生成统一测评产物：
  - `final_output.md`
  - 如果最终答案可解析为 JSON，则生成 `final_output.json`
  - `task_result.json`
  - `responses.jsonl`
- 每轮会保存干净的 response 文件；如果使用 CLI 后端，还会保存 stdout/stderr。
- 执行后会检查是否产生了非白名单 skill。

## 目录结构

准备或执行后会生成类似目录：

```text
runs/
  task_gaokao_shandong_2025_recommendation/
    skill_on/
      run_20260527_001/
        config.json
        manifest.json
        prompts/
        workspace/
          datasets/
            2025年分段表.xls
            山东省2025年普通类常规批第1次志愿投档情况表.xls
          skills/
            gaokao-advisor/
              SKILL.md
    skill_off/
      run_20260527_001/
        config.json
        manifest.json
        prompts/
        workspace/
          datasets/
            ...
          skills/
```

`skill_on` 和 `skill_off` 是两套完全独立的 workspace，可以直接做对比。

## 只准备环境

在仓库根目录下运行：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py --skill-mode both
```

这会对 `task.json` 中第一个任务同时生成 `skill_on` 和 `skill_off` 两套环境，但不会调用模型。

如果你只想准备其中一种：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py --skill-mode on
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py --skill-mode off
```

## 执行任务

加上 `--execute` 后，runner 会按 `task.json` 中的 turns 逐轮调用 nanobot：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py --skill-mode on --execute
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py --skill-mode off --execute
```

默认执行后端是 `direct`，会直接调用 nanobot 的 Python 接口并捕获干净的 `response.content`，避免把终端样式、日志、机器人标题混进测评输出。

如果你想使用原始 CLI 方式，可以显式指定：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py `
  --skill-mode on `
  --execute `
  --backend cli
```

CLI 后端内部会调用 `python -m nanobot agent`，同时保存 stdout/stderr 日志。

同一个任务的多轮对话会使用同一个 session，因此后续轮次可以继承前面回答中的上下文。但不同 run 的 session 文件在不同 workspace 下，不会互相影响。

## 多任务运行

查看当前 `task.json` 中的全部任务：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py --list-tasks
```

运行多个指定任务，`--task-id` 可以重复，也可以用逗号分隔：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py `
  --task-id task_company_weekly_order_risk,task_company_weekly_sales_performance `
  --skill-mode both `
  --run-id exp_001 `
  --execute
```

运行 `task.json` 里的全部任务：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py `
  --all-tasks `
  --skill-mode both `
  --run-id exp_001 `
  --execute
```

批量运行仍然会为每个任务建立独立目录：`runs/<task_id>/<skill_mode>/<run_id>/`。

## 常用参数

```text
--task-json datasets\task.json
```

指定任务列表文件。

```text
--task-id task_gaokao_shandong_2025_recommendation
```

指定要运行的任务。不传时默认使用 `task.json` 中第一个任务。可以重复传入，也可以用逗号分隔多个任务。

```text
--all-tasks
```

运行 `task.json` 里的全部任务。

```text
--list-tasks
```

列出 `task.json` 中所有任务 id 后退出。

```text
--skill-mode on|off|both
```

控制是否提供任务声明的 skill。

```text
--skill-policy available|required-read|force-use|preload
```

控制 `skill_on` 时 skill 的使用方式：

- `available`：只把任务声明的 skill 放进 workspace 并暴露给 nanobot，模型可以自己决定是否读取。这是默认值。
- `required-read`：在每轮 prompt 中明确要求模型先用 `read_file` 读取 `skills/<skill>/SKILL.md`，但该文件是 description-only 影子文件，不包含原始 skill 正文；是否采纳 skill 仍由模型根据任务判断。
- `force-use`：复制任务声明的完整 skill，并给 `SKILL.md` 标记 `always: true`，让 nanobot 把完整 skill 作为 `Active Skills` 加载到系统提示词；模型每一轮都能看到并必须使用该 skill。
- `preload`：runner 只把允许 skill 的 description 预加载进每轮 prompt，不预加载原始完整 `SKILL.md`。

```text
--run-id custom_name
```

指定本次 run 的名字。不传时自动生成时间戳。

```text
--execute
```

真正调用 nanobot 执行任务。没有这个参数时只准备目录和配置。

```text
--overwrite
```

如果同名 run 目录已存在，允许删除并重建。

```text
--keep-going
```

某一轮失败后继续跑后续轮次。默认遇到失败就停止。

```text
--python .\.venv\Scripts\python.exe
```

指定执行 nanobot 时使用的 Python。

```text
--backend direct|cli
```

指定执行后端。默认 `direct`，更适合测评；`cli` 更接近手工命令行运行。

## Provider 配置

默认会从下面这个文件读取 provider/model 设置：

```text
%USERPROFILE%\.nanobot\config.json
```

runner 只复用 provider 和模型相关配置；workspace、工具、skill、memory/session 设置都会被本次 run 的隔离配置覆盖。

如果要指定另一个基础配置：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py `
  --base-config path\to\config.json `
  --skill-mode on
```

注意：生成的 run-local `config.json` 可能包含 API key，所以 `runs/` 已经加入 `.gitignore`，不要手动提交 run 目录。

## Skill 开关逻辑

每个任务会按自己的 `skills` 字段复制白名单 skill。例如某个任务声明：

```json
"skills": ["gaokao-advisor"]
```

则该任务运行时：

- `--skill-mode on`：workspace 里只会有任务声明的 skill。默认和 `required-read`/`preload` 使用 description-only 影子文件；`force-use` 使用完整 `SKILL.md` 并加载到系统提示词。
- `--skill-mode off`：workspace 的 `skills/` 为空，并且 `disabledSkills` 里会禁用 `gaokao-advisor`。
- 其他 dataset skills 和 nanobot 内置 skills 都会写入 `disabledSkills`，避免被模型看到或调用。不同任务各自使用自己的 skill 白名单。

runner 还会在每轮执行后检查 `workspace/skills/`。如果发现非白名单 skill，说明环境被污染，会直接报错。

注意：`--skill-mode on` 默认只代表“这个 skill 可见、可用”，不保证模型一定会读取它。需要强制观察轨迹里的 skill 读取行为时，建议使用：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py `
  --skill-mode on `
  --skill-policy required-read `
  --execute
```

如果你更关心“模型一定拿到 skill 内容”，而不是轨迹里是否出现 `read_file`，使用：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py `
  --skill-mode on `
  --skill-policy preload `
  --execute
```

## 为什么不用 gateway

建议 benchmark 使用 `nanobot agent -m`，不要用 `nanobot gateway`。

原因是 gateway 会注册 Dream 后台任务。Dream 会处理历史、写入 memory，甚至可能根据对话创建新的 skill。对 benchmark 来说，这会破坏“每次任务独立初始化、skill 可控”的假设。

这个 runner 使用 CLI 单轮调用方式，不启动 Dream cron。

## 输出文件

执行后会在 run 目录下生成统一测评产物：

```text
final_output.md
final_output.json
task_result.json
skill_usage.json
responses.jsonl
outputs/
  turn_00.response.md
  turn_01.response.md
  ...
```

其中：

- `final_output.md`：最后一轮的原始最终答案，始终生成。
- `final_output.json`：如果最后一轮答案能解析成 JSON，则生成这个文件，适合直接给规则测评器读取。
- `task_result.json`：统一结果文件，包含任务元信息、skill 模式、每轮记录、最终输出；如果最终输出能解析为 JSON，`final_output` 字段就是 JSON 对象，否则是原始文本。
- `skill_usage.json`：记录本次 run 是否预加载 skill description、是否将完整 skill 加载进系统提示词，以及 session 轨迹中是否出现读取 `skills/<skill>/SKILL.md` 的 `read_file` 调用。
- `responses.jsonl`：每轮一行，记录 return code、response 路径和内容。
- `turn_xx.response.md`：每轮干净回复。
- 如果使用 `--backend cli`，还会额外生成 `turn_xx.stdout.txt` 和 `turn_xx.stderr.txt`。

## 打分测评

执行完成后，可以用 `evaluate_task_outputs.py` 根据 `task.json` 中每轮的 `score_points` 自动打分。默认使用 LLM judge，通过提示词逐轮评估每个 score point：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\evaluate_task_outputs.py `
  --run-root runs\task_gaokao_shandong_2025_recommendation\skill_on\<run_id>
```

评分器会优先读取 run 目录下的 `manifest.json` 自动识别 `task_id`，因此通常不需要手动传 `--task-id`。如果传入的是父目录，评分器会递归查找其中的 run：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\evaluate_task_outputs.py `
  --run-root runs `
  --run-id exp_001 `
  --skill-mode on
```

也可以按 `run_id` 批量评估多个任务：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\evaluate_task_outputs.py `
  --run-id exp_001 `
  --skill-mode both `
  --all-tasks
```

批量评估会在每个 run 目录写入各自的 `evaluation_result.json` 和 `evaluation_report.md`，并额外生成一个汇总文件：

```text
evaluation_summary.json
evaluation_summary.md
```

默认会使用该 run 目录下的：

```text
<run_root>/config.json
```

作为 judge 的 provider/model 配置。也可以手动指定：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\evaluate_task_outputs.py `
  --run-root runs\task_gaokao_shandong_2025_recommendation\skill_on\<run_id> `
  --judge-config path\to\config.json `
  --judge-provider volcengineCodingPlan `
  --judge-model ark-code-latest
```

如果你想使用旧的离线规则匹配方式：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\evaluate_task_outputs.py `
  --judge rule `
  --run-root runs\task_gaokao_shandong_2025_recommendation\skill_on\<run_id>
```

评分器会读取：

```text
<run_root>/responses.jsonl
```

如果没有 `responses.jsonl`，会尝试读取：

```text
<run_root>/task_result.json
<run_root>/outputs/turn_xx.response.md
```

评分输出：

```text
evaluation_result.json
evaluation_report.md
```

`evaluation_result.json` 结构包含：

```json
{
  "task_id": "...",
  "score": 26.0,
  "max_score": 27.0,
  "accuracy": 0.9629,
  "turns": [
    {
      "idx": 0,
      "score": 3.0,
      "max_score": 3.0,
      "accuracy": 1.0,
      "points": [
        {
          "score_point": "...",
          "score": 1.0,
          "max_score": 1.0,
          "passed": true,
          "matched": [],
          "missing": []
        }
      ]
    }
  ]
}
```

当前默认评分方式是 LLM 评分：每一轮调用一次 judge 模型，把当前轮问题、score_points 和模型回答交给 LLM 判断。每个 score point 默认 1 分，通过得 1，不通过得 0；每轮小计，最后汇总总分。

LLM judge 的评分原则包括：

- 接受等价表述、JSON、表格、中文/英文字段名混合、实体名前带代码等格式差异。
- 对明确要求的日期、数值、实体名、字段、公式、阈值、文件路径和数据源严格判定。
- 如果 score point 明确规定计算公式、单位、范围、排序、筛选或排除条件，回答必须满足这些约束。
- 如果回答保留了任务明确排除的记录类型，则判错。

默认不再自动回退到规则评分，避免非高考/非固定格式任务被简单规则误判。如果希望 LLM judge 失败时使用通用规则兜底，可以加：

```powershell
--rule-fallback
```

例如同时跑和评估 skill on/off：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py --skill-mode both --run-id gaokao_exp_001 --execute

.\.venv\Scripts\python.exe isolated_benchmark_runner\evaluate_task_outputs.py `
  --run-root runs\task_gaokao_shandong_2025_recommendation\skill_on\gaokao_exp_001

.\.venv\Scripts\python.exe isolated_benchmark_runner\evaluate_task_outputs.py `
  --run-root runs\task_gaokao_shandong_2025_recommendation\skill_off\gaokao_exp_001
```

## 推荐实验流程

1. 先准备两套环境：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py --skill-mode both --run-id gaokao_exp_001
```

2. 检查 `runs/.../manifest.json`，确认数据和 skill 复制正确。

3. 分别执行：

```powershell
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py --skill-mode on --run-id gaokao_exp_001 --overwrite --execute
.\.venv\Scripts\python.exe isolated_benchmark_runner\run_isolated_task.py --skill-mode off --run-id gaokao_exp_001 --overwrite --execute
```

4. 对比 `skill_on` 和 `skill_off` 下的 `final_output.json` 或 `task_result.json`。

## 已知边界

- runner 负责准备、执行任务和生成统一输出；`evaluate_task_outputs.py` 负责按 `score_points` 打分。
- `skill_on` 默认表示 skill 可见、可读，不保证模型一定会读取 skill；需要更强约束时使用 `--skill-policy required-read`、`--skill-policy force-use` 或 `--skill-policy preload`。
- 隔离依赖 workspace 边界；不要手动把外部文件复制进 run workspace。
