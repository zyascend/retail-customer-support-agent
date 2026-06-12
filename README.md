# Retail Customer Support Agent

基于 tau3-bench retail 数据的交易型零售客服 Agent。

## 从这里开始

- [技术架构文档](./TECHNICAL_ARCHITECTURE.md)

## Phase 0：基线复现

Phase 0 以离线验证为主。在构建项目自己的 Agent workflow 之前，先验证本地 tau2-bench retail 数据是否可用，并汇总已有 retail benchmark 结果。

### 前置条件

- 安装 `uv`：https://docs.astral.sh/uv/getting-started/installation/
- 保持本地 tau2-bench checkout 位于：

```text
/Users/theyang/Documents/ai/AgentProject/data_sources/raw/tau2-bench
```

如果你的 checkout 在其他目录，请复制 `.env.example` 为 `.env`，并覆盖 `TAU2_BENCH_ROOT` 和 `TAU2_DATA_DIR`。

### 离线检查

验证本地源码和 retail 数据：

```bash
uv run phase0-check
```

汇总历史 retail baseline 结果：

```bash
uv run phase0-report \
  --result /Users/theyang/Documents/ai/AgentProject/data_sources/raw/tau2-bench/data/tau2/results/final/gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json
```

报告会写入 `artifacts/phase0/`。该目录有意被 git 忽略。

### 可选 Live Smoke Test

Phase 0 的 live smoke test 是可选项，因为它需要 provider API key 和 tau2 runtime 依赖。请先在环境变量或 `.env` 中配置 provider key 和模型名，然后运行：

```bash
uv run phase0-smoke --domain retail --num-tasks 1 --num-trials 1
```

如果没有 API key，`phase0-smoke` 会成功退出，并显示 skipped 信息。

### 本地单元测试

```bash
python3 -m unittest discover -s tests
```

## 代码结构

核心实现按产品能力组织，而不是按迭代 phase 切目录：

```text
app/agent/   guarded workflow runtime、prompts、providers、state models
app/tools/   retail adapter、registry、gateway
app/eval/    curated cases、eval runner、failure labels
app/ops/     trace 和 serialization helpers
app/cli/     chat 和 eval 命令入口
prompts/     带 hash metadata 的文件版本化 LLM prompts
```

带 phase 名称的 CLI 命令主要用于保持 roadmap 清晰；实际实现放在上面的能力包中。

## Phase 1：Guarded Workflow Agent

Phase 1 增加 CLI-first 的 guarded agent runtime。它会完成用户认证、加载 retail context、创建 pending write actions、要求显式确认、通过 gateway 执行 retail tools，并写出可回放的 trace artifact。

运行 scripted smoke conversation：

```bash
uv run phase1-chat --script examples/chat/cancel_order.json
```

如需走 LLM-backed path，请在本地 `.env` 中配置 DeepSeek：

```text
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEFAULT_AGENT_MODEL=deepseek-v4-flash
AGENT_LLM_TIMEOUT_SECONDS=30
AGENT_LLM_MAX_RETRIES=2
```

然后运行：

```bash
uv run phase1-chat --script examples/chat/cancel_order.json --require-llm
```

如果没有 `DEEPSEEK_API_KEY`，Phase 1 会回退到 deterministic rules，以保证本地测试和 guard checks 可以离线、可重复运行。

运行交互式会话：

```bash
uv run phase1-chat --interactive
```

Trace artifacts 会写入：

```text
artifacts/phase1/runs/<run_id>.json
```

## Phase 2：Curated Eval Runner

运行 curated MVP eval subset。它覆盖 lookup、写操作、confirmation flows、被 guard 阻止的 policy violations、wrong-user access 和 human transfer：

```bash
uv run phase2-eval --subset curated_mvp --trials 1
```

强制使用 LLM-backed path：

```bash
uv run phase2-eval --subset curated_mvp --trials 1 --require-llm
```

Eval progress 默认打印到 stderr，这样长时间 LLM-backed run 可以显示当前 case 和每个 case 的耗时，同时不会污染 `--json` stdout。机器驱动的安静运行可以使用 `--no-progress`。

Eval summary 会写入：

```text
artifacts/phase2/eval_runs/<eval_run_id>.json
```

供 dashboard 和 replay tooling 使用的稳定 report artifact 会写入：

```text
artifacts/phase2/reports/<eval_run_id>.json
```

两类 artifact 都包含 `schema_version`、dataset paths、code commit、model settings、prompt file hashes、trace paths、DB hashes、replay metadata、failure labels 和 aggregate metrics。当前契约版本为 `phase2.eval_run_summary.v1` 和 `phase2.eval_report.v1`。

指标定义：

- `pass_1`：所有 trials 中按单条 result 计算的原始通过率。
- `pass_k`：每个 unique case 的所有 trials 都通过时才算通过；该指标是通过的 unique case 占比。
- `db_accuracy`：可检查 DB 的 results 中，最终状态匹配预期订单状态或 no-write hash invariant 的比例。
- `tool_call_success_rate`：成功 tool calls / 全部 tool calls；预期内的 guard blocks 单独统计，不算 tool errors。
- `guard_block_rate`：blocked tool calls / 全部 tool calls。
- `mutation_error_rate`：标记为 no-write 的 case 中，仍发生写入或 DB hash 变化的比例。

对比两个 Phase 2 artifacts：

```bash
uv run phase2-eval --compare \
  artifacts/phase2/eval_runs/<baseline>.json \
  artifacts/phase2/eval_runs/<candidate>.json
```

## Phase 3：Trace Viewer + Eval Dashboard

Phase 3 使用 Phase 2 的稳定 report artifact 生成本地静态 dashboard。它包含 eval 指标总览、case 过滤、失败样本列表，以及每个样本的 transcript、agent steps、tool calls、policy checks、write audit 和 final state 只读回放。

```bash
uv run phase3-dashboard artifacts/phase2/reports/<eval_run_id>.json
```

默认输出到：

```text
artifacts/phase3/dashboard/<eval_run_id>/index.html
artifacts/phase3/dashboard/<eval_run_id>/dashboard-data.json
```

Dashboard 默认会对 trace 中常见邮箱、电话、地址、支付字段做脱敏。如需生成原始调试版：

```bash
uv run phase3-dashboard artifacts/phase2/reports/<eval_run_id>.json --no-redact
```

## Phase 4：Hybrid Ops Workbench

Phase 4 增加一个本地单会话 workbench，用于 scripted 和 manual agent demo。它展示 run controls、business state、pending actions、conversation、timeline、tool calls、guard blocks 和 write audit details。

启动 Python API：

```bash
uv run phase4-workbench
```

在另一个终端启动 React workbench：

```bash
cd workbench
npm install
npm run dev
```

然后打开：

```text
http://localhost:5173
```

默认模式是 deterministic/offline，不需要 API key。如果配置了 `DEEPSEEK_API_KEY`，UI 也会开放 LLM mode。
