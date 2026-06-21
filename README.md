# 零售客服智能 Agent

LLM tool-calling 零售客服 Agent。内建 7 层写安全护栏，每次写入都需用户确认，全链路可追溯。基于 tau2-bench retail 数据构建，定位为 AI Agent 工程作品集项目。

> 启动 Workbench（需配置 `DEEPSEEK_API_KEY`，见下方快速开始）后，打开 `http://localhost:5173` 即可交互式体验 14 个按用户旅程分组的精选案例。

## 解决的问题

零售客服 Agent 要解决三个问题：

1. **写操作安全** — 取消订单、改支付、退换货不能误触发，也不能越权。每次写入都要用户确认，过七层检查才能执行。
2. **意图消歧** — 用户说"我想改一下订单"，可能是取消、换商品、改地址、改支付。Agent 得从一句话里猜出具体意图和参数。
3. **全链路可审计** — 每个决策、工具调用和数据库变更都能追溯到规则，操作前后有哈希对比和幂等键记录。

本项目的原则很简单：LLM 负责理解意图和选工具；代码负责边界、护栏、确认和审计。

## 架构概览

```
user message → pre-flight checks → AgentLoop → ToolGateway / WriteActionGuard
→ tool observation → assistant response → trace artifact → AgentOps
                              │
                              ▼
                     Skill Registry (8 write skills)
                              │
                              ▼
                    RetailAdapter (tau3-bench / local db.json)
```

**LLM tool-calling runtime**: `AgentLoop` 用 provider 的 `chat_with_tools()` 选工具、读 observation、生成回复。pre-flight 层处理待确认写操作和身份 shortcut。

**7 层写护栏**: 身份认证 → 显式确认 → 所有权校验 → 先读后写 → 策略合规 → 资源锁 → 幂等性。每次写操作执行前都要依次通过这七层。

**Skill 资产化**: 8 个写操作的行为知识（intent pattern、tool 调用链、guard 约束、prompt 指引）已从散落四处的代码收敛到 `app/skills/registry.py` 中的 `SkillSpec` 版本化单元。现在支持 per-skill 评测维度和变更追踪。

**AgentOps**: Workbench 中集成了 AgentLoop trace 可视化，可以查看 guard block 详情、时间线、写入审计记录（操作前后 DB 哈希、幂等键）。

**数据飞轮 (Flywheel)**: Live eval 失败的 case → bad case 沉淀 → 可扩展变体生成 → golden 回归检查。

**Workbench**: 基于 FastAPI + React 的交互界面。支持 14 个精选案例的用户旅程导览、AgentOps trace 浏览器和阶段性 eval 报告可视化。

## 关键设计决策

- **运行时边界清晰** — 默认 `AgentRuntime` 需要真实 LLM provider；没有 provider 时直接转人工。没有 `offline_demo` 或降级模式。
- **工具调用受控** — LLM 只能通过 schema 暴露的工具行动；写工具必须经过 `ToolGateway` 和 `WriteActionGuard`。
- **写操作单一事实来源** — `app/agent/action_specs.py` 定义了全部 8 种写操作。护栏规则、工具注册表、LLM 提示词中的 `{tool_catalog}` 模板和参数约束都从这里派生。Skill 资产化作为第二层组织视图，只做知识版本化，不修改执行模型。
- **Think 工具实验** — `think(reasoning)` 实验工具通过 `ENABLE_THINK_TOOL=true` 开启，用于 live eval A/B 对比。默认关闭。

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

> 未配置 `DEEPSEEK_API_KEY` 时，AgentLoop 会转人工。项目不提供离线/降级模式。

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

### Live Baseline（2026-06-18，模型 deepseek-v4-flash）

| 子集 | Cases | Pass Rate |
|------|-------|-----------|
| curated_mvp | 11 | **100%** |
| generalized_mvp | 30 | **100%** |
| synthetic_seeded_v1 | 7 | **57%**（4/7，无显著回归） |

失败分类体系包含 14 种有序标签（llm_json_failure → auth_failure → wrong_intent → ...），方便定位问题。

### 运行命令

```bash
uv run phase2-eval --subset curated_mvp --trials 1 --max-workers 1 --live
uv run phase2-eval --subset generalized_mvp --trials 1 --max-workers 1 --live
```

查看 triage 报告：

```bash
uv run python -m app.eval.live_triage artifacts/phase2/reports/<eval-run-id>.json
```

Eval report 记录 `baseline_metadata`（model、provider、prompt/tool/action-spec hash、per-skill hash）、`total_token_usage`、`average_llm_loop_iterations`、tool call / guard block 指标、`auto_load_count`、`premature_refusal_corrected_count`、`context_truncation_count` 和失败 root cause。

Phase 10 后，LLM tool schema 的 description 包含 when-to-use / when-not-to-use / required-prior-read / guard-block guidance；参数 schema 有更强的 order/item/payment pattern 约束，用 `tool_schema_hash` 追踪 prompt/schema 优化影响。

### Eval 子集一览

| 子集 | 说明 | 数量 |
|------|------|------|
| `curated_mvp` | 手写核心案例，覆盖 8 种写操作 + lookup + 边界 | 11 |
| `generalized_mvp` | 基于 tau3-bench 任务泛化，每场景多语言变体 | 30 |
| `synthetic_seeded_v1` | 种子 + 变体类型的 LLM 生成场景 | 7 |
| `live` | 需要真实 LLM provider | 全部（加上 `--live`） |

所有子集可并行运行，推荐 `--max-workers 10` 平衡速度和限流。

```bash
uv run phase2-eval --subset all --live --max-workers 10 --json --no-progress
```

## 项目结构

```text
app/agent/       — AgentLoop、SessionState、提示词、确认流、写护栏
app/tools/       — retail 适配器、工具注册表、写操作网关
app/eval/        — curated + generalized eval 案例、运行器、失败分类、飞轮数据、golden 回归
app/skills/      — Skill 资产定义与注册表（per-skill 版本化行为单元）
app/synthetic/   — 合成数据生成（seed-based 变体、语言变体、oracle）
app/workbench/   — Workbench API（FastAPI 后端）、AgentOps 可视化
app/ops/         — 序列化、追踪（TraceWriter）、哈希工具
app/cli/         — CLI 入口（chat、eval、flywheel、workbench）
app/config.py    — AppConfig 配置加载
workbench/       — Workbench React 前端（Vite + TypeScript）
prompts/         — LLM agent 系统提示词（单文件，SHA-256 版本追踪）
cases/           — bad case 收集、golden 回归用例
docs/            — 设计文档、实施计划、架构参考、审计报告、技术复盘
```

## Flywheel / Golden SOP

把 live eval 的失败样本沉淀为 bad case、扩展可泛化变体、提升为 golden，然后持续做回归检查。

**适用场景**
- 刚跑完 `--live` eval，想把真实失败沉淀下来
- 要把某个已知 bad case 升级成长期回归用例
- 改了 prompt / guard / runtime，想确认 golden 没被改坏

**推荐流程**
1. 先跑 live eval，拿到 report JSON
2. 用 `flywheel collect` 收集失败 case 到 `cases/bad_cases/<date>.yaml`
3. 如果 case 带 `seed + variant_type`，用 `flywheel generate` 生成 gate 变体
4. 用 `flywheel golden promote --confirm` 把关键 case 放进 `cases/golden.yaml`
5. 用 `flywheel check` 跑 golden 回归；出现 `regression` / `missing` 时退出码为 `1`

```bash
# 1. 跑 live eval（推荐先从 generalized_mvp 或目标 live subset 开始）
uv run phase2-eval --subset generalized_mvp --live --max-workers 10 --json --no-progress

# 2. 收集 bad case（report 路径来自上一步输出）
uv run flywheel collect \
  --report artifacts/phase2/reports/<eval-run-id>.json \
  --subset generalized_mvp \
  --date 2026-06-20

# 3. 生成可扩展变体（仅对带 seed + variant_type 的 case 生效）
uv run flywheel generate --input cases/bad_cases/2026-06-20.yaml

# 4. 把关键 case 提升进 golden（必须加 --confirm）
uv run flywheel golden promote \
  --input cases/bad_cases/2026-06-20.yaml \
  --case-id <case_id> \
  --confirm

# 5. 跑 golden 回归检查
uv run flywheel check --no-progress --json
```

**常见情况**
- `collect` 依赖 `--subset` 做 case rehydrate；report 不含 subset 时必须显式传入
- `generate` 会跳过手写 case；只有带 `seed + variant_type` 的 synthetic/generalization case 才会生成变体
- `promote` 目前是非交互式确认，漏掉 `--confirm` 会直接失败
- `check` 在 `cases/golden.yaml` 为空时返回空结果，不会报错
- golden 里某条 case 失败显示为 `regression`；缺少执行结果显示为 `missing`

## 近期技术优化

### Skill 资产化（PR #55）

把 8 个高频写操作的行为知识从分散的代码中收敛到 `app/skills/registry.py` 的 `SkillSpec` 版本化单元。每个 Skill 包含 intent pattern、entry tool、required read、guard constraint、prompt guidance 和 few-shot example。

效果：
- 新增写操作只需改 `action_specs.py` + `skills/registry.py`，不用改 prompt 和 runtime
- 评测维度按 skill_id 拆分，可以独立追踪每个 skill 的通过率
- 每个 SkillSpec 记录变更 hash，prompt/schema 优化时可精准归因

### DeepSeek KV Cache 优化（PR #50）

把动态 `state_summary` 从 system prompt 剥离到 messages 末尾，保持 system prompt 作为稳定前缀，提升 KV Cache 命中率。在 `app/workbench/agentops.py` 中接入了 KV Cache 命中统计（`cache_hit_tokens` / `cache_miss_tokens`），支持 A/B 对比。

### 工具定义优化（PR #46）

三项并行改进：参数 schema 补全（state 枚举、zip regex、country 约束）+ 工具描述单一事实源（docstring → dict → name 四层 fallback）+ 实验性 `think(reasoning)` 工具（默认关闭，通过 `ENABLE_THINK_TOOL=true` 开启 A/B 测试）。

### 上下文管理优化（PR #44）

三项优化：token-aware 上下文预算（固定 6 条 → 8000 token L4 预算，超限时生成摘要）+ Guard 输出语义化（`Locks:` → `Active safeguards:`）+ 订单 ID 去重（统一 `#W\d+` 单 key 存储）。

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

技术复盘：
- [Skill 资产化技术复盘](docs/optimize/skill-assetization-retrospective.md)
- [DeepSeek KV Cache 优化技术复盘](docs/optimize/deepseek-kv-cache-optimization-retrospective.md)
