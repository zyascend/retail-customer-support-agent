# 零售客服智能 Agent

一个面向零售客服场景的 LLM tool-calling Agent，内建 7 层写安全护栏、显式用户确认和全链路 trace。基于 tau2-bench retail 数据构建，定位为 AI Agent 工程作品集项目：展示真实 LLM 工具调用、安全写操作和可审计运行时三项核心能力。

> 启动 Workbench（需配置 `DEEPSEEK_API_KEY`，见下方快速开始）后，打开 `http://localhost:5173` 即可交互式体验 14 个按用户旅程分组的精选案例。

## 解决的问题

零售客服 Agent 面临三个核心挑战：

1. **写操作安全** — 取消订单、修改支付方式、退换货等操作不能误触发，更不能越权执行。每一次写入都需要用户显式确认，并通过多层护栏检查。
2. **意图消歧** — 用户说"我想改一下订单"，可能意味着取消、换商品、改地址、改支付方式。Agent 必须从非结构化自然语言中提取出结构化的意图和槽位。
3. **全链路可审计** — 每一次决策、每一次工具调用、每一次数据库变更，都必须追溯到具体的策略规则，并提供操作前后的哈希对比和幂等键。

本项目的原则是：LLM 负责理解意图和选择工具；代码负责工具边界、写入护栏、确认流程和审计证据。

## 架构概览

```
user message → pre-flight checks → AgentLoop → ToolGateway / WriteActionGuard
→ tool observation → assistant response → trace artifact
```

**LLM tool-calling runtime**: `AgentLoop` 使用 provider 的 `chat_with_tools()` 选择工具、读取 observation 并生成回复。运行时保留 pre-flight 层处理待确认写操作和身份 shortcut。

**7 层写护栏**: 身份认证 → 显式确认 → 所有权校验 → 先读后写 → 策略合规 → 资源锁 → 幂等性。每一次写操作在真正执行前，都必须依次通过全部七层检查。

**Workbench**: 基于 FastAPI 的交互式可视化界面，仅支持 `llm` 模式运行，需配置 `DEEPSEEK_API_KEY`。未配置 provider 时运行时安全转人工。

## 关键设计决策

- **运行时边界清晰** — 默认 `AgentRuntime` 需要真实 LLM provider；没有 provider 时会安全返回转人工消息。无 `offline_demo` 或降级模式。
- **工具调用受控** — LLM 只能通过 schema 暴露的工具行动；所有写工具都必须经过 `ToolGateway` 和 `WriteActionGuard`。
- **写操作单一事实来源** — `app/agent/action_specs.py` 定义了全部 7 种写操作。护栏规则、工具注册表、LLM 提示词中的 `{tool_catalog}` 模板和写操作参数约束，全部由此派生。新增一种写操作只需改这一个文件。

## 快速开始

```bash
# 1. 安装依赖
uv sync --extra dev

# 2. 配置 LLM provider（Workbench 和 live eval 需要）
# 在 .env 中设置：
#   DEEPSEEK_API_KEY=sk-...
#   DEEPSEEK_BASE_URL=https://api.deepseek.com
#   DEFAULT_AGENT_MODEL=deepseek-v4-flash

# 3. 启动 Workbench（需 DEEPSEEK_API_KEY）
uv run workbench &                  # Python API → :8765
cd workbench && npm install && npm run dev   # React 界面 → :5173

# 4. 运行 eval（需 DEEPSEEK_API_KEY）
uv run phase2-eval --subset curated_mvp --trials 1 --live

# 5. 运行测试（无需 API key）
uv run python -m pytest tests/ -q
```

> 未配置 `DEEPSEEK_API_KEY` 时，AgentLoop 会安全转人工。项目不提供离线/降级模式。

## Demo 导览

打开 `http://localhost:5173`，按用户旅程分组体验 14 个案例：

| 分组 | 包含案例 | 展示内容 |
|------|---------|----------|
| 🔐 身份认证 | 姓名+邮编验证查订单 | 用户身份识别流程 |
| ✅ 成功写操作 | 取消订单、退货、换商品、改支付方式 | 带确认的完整写操作链路 |
| 🛡️ 写保护阻止 | 越权访问他人订单、跨商品替换、礼品卡余额不足 | 护栏各层拦截未授权写入 |
| 🔄 用户确认流程 | 拒绝取消确认 | 用户侧拒绝交互 |
| 📞 边界能力 | 转接人工客服 | 不支持操作的升级流转 |
| 🧪 Synthetic 世界 | 升级配送方式 | 合成数据场景 |
| 🧬 生成场景 | 取消订单 L1、配送升级 L2、折扣请求 L1 | LLM 生成的多样化变种 |

**Timeline 中的关键证据**: 选中任意案例，点击「运行全部」，然后在 timeline 中查看：
- pre-flight、AgentLoop、工具调用和 observation
- 护栏阻止详情或待确认写操作
- 写入审计记录（操作前后 DB 哈希、幂等键）

## Eval 结果

| 指标 | curated_mvp（11 case） | generalized_mvp（30+ case） |
|------|----------------------|----------------------------|
| live LLM | 需 `--live` 和 `DEEPSEEK_API_KEY` | 需 `--live` 和 `DEEPSEEK_API_KEY` |
| 并行执行 | `--max-workers` 支持 | `--max-workers` 支持 |
| trace | 每次运行输出 JSON artifact | 每次运行输出 JSON artifact |
| baseline 对比 | `--compare` 双 JSON 对比 | `--compare` 双 JSON 对比 |

失败分类体系包含 14 种有序标签（llm_json_failure → auth_failure → wrong_intent → ...），确保精准定位问题。

Live baseline 运行：

```bash
uv run phase2-eval --subset curated_mvp --trials 1 --max-workers 1 --live
uv run phase2-eval --subset generalized_mvp --trials 1 --max-workers 1 --live
```

查看 triage 报告：

```bash
uv run python -m app.eval.live_triage artifacts/phase2/reports/<eval-run-id>.json
```

Eval report 记录 `baseline_metadata`（model、provider、prompt/tool/action-spec hash）、`total_token_usage`、`average_llm_loop_iterations`、tool call / guard block 指标、`auto_load_count`、`premature_refusal_corrected_count` 和失败 root cause。

Phase 10 后，LLM tool schema 的 description 包含 when-to-use / when-not-to-use / required-prior-read / guard-block guidance；参数 schema 也包含更强的 order/item/payment pattern 约束，方便用 `tool_schema_hash` 追踪 prompt/schema 优化影响。

## 项目结构

```text
app/agent/       — AgentLoop、SessionState、提示词、确认流、写护栏
app/tools/       — retail 适配器、工具注册表、写操作网关
app/eval/        — curated + generalized eval 案例、运行器、失败分类
app/workbench/   — Workbench API（FastAPI 后端）、AgentOps 可视化
app/ops/         — 序列化、追踪（TraceWriter）
app/config.py    — AppConfig 配置加载
workbench/       — Workbench React 前端
prompts/         — LLM agent 系统提示词（单文件，SHA-256 版本追踪）
docs/            — 设计文档、实施计划、架构参考、审计报告
```

## 开发指南

```bash
# Lint 与格式化
uv run ruff check .
uv run ruff format --check .

# 运行单个测试
uv run python -m pytest tests/test_agent_core.py -v

# 运行脚本模式对话（需 DEEPSEEK_API_KEY）
uv run phase1-chat --script examples/chat/cancel_order.json

# 启动 Workbench
uv run workbench
```

深度架构参考见 [`docs/portfolio-architecture.md`](docs/portfolio-architecture.md)。

完整路线图见 [`docs/long-term-optimization-path.md`](docs/long-term-optimization-path.md)。

设计审计报告见 [`docs/design-audit.md`](docs/design-audit.md)。
