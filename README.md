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

```
retail-customer-support-agent/
├── README.md                         # 项目文档
├── AGENTS.md                         # AI agent 会话上下文指南
├── HANDOFF.md                        # 跨会话 handoff 上下文
├── TECHNICAL_ARCHITECTURE.md         # 技术架构深度文档
├── pyproject.toml                    # Python 项目配置（hatchling 构建）
├── reasonix.toml                     # Reasonix 工作流配置
├── .env.example                      # LLM provider 环境变量模板
├── prompts/                          # LLM 系统提示词
│   └── llm_agent_system_v001.md      # 单文件系统 prompt（SHA-256 版本追踪）
├── app/                              # 核心应用代码
│   ├── __init__.py
│   ├── config.py                     # AppConfig 配置加载（环境变量 + .env）
│   ├── pydantic_compat.py            # Pydantic v2 兼容层
│   ├── agent/                        # Agent 运行时核心
│   │   ├── __init__.py
│   │   ├── runtime.py                # AgentRuntime 入口（preflight + AgentLoop 编排）
│   │   ├── llm_agent.py              # AgentLoop while-loop（LLM ↔ tool execute，max 14 轮）
│   │   ├── guard.py                  # 7 层写安全护栏（auth→ownership→read-before-write→policy→locks→idempotency）
│   │   ├── confirmation.py           # 用户确认/拒绝/变更的关键词解析
│   │   ├── context_builder.py        # 语义化上下文描述（Active safeguards、loaded context 去重）
│   │   ├── action_specs.py           # 写操作单一事实源（全部 8 种写操作的元数据定义）
│   │   ├── models.py                 # 数据模型（Message、SessionState、AgentStep、ToolCallRequest/Response）
│   │   ├── parsers.py                # 正则解析（姓名+邮编、订单 ID 等）
│   │   ├── prompts.py                # PromptSpec 加载、SHA-256 版本追踪
│   │   ├── providers.py              # LLM provider 抽象（OpenAI / DeepSeek 适配）
│   │   └── tool_observations.py      # 工具调用结果观察数据处理
│   ├── tools/                        # 工具系统
│   │   ├── __init__.py
│   │   ├── registry.py               # 工具发现 + LLM schema 生成（when-to-use/when-not-to-use）
│   │   ├── gateway.py                # 唯一工具执行入口（写操作必经 Guard）
│   │   └── retail_adapter.py         # Retail 数据适配器（tau3-bench 数据库 / 本地 db.json）
│   ├── skills/                       # Skill 资产化
│   │   ├── __init__.py
│   │   ├── spec.py                   # SkillSpec 数据模型（intent pattern、entry tool、guard constraint）
│   │   └── registry.py               # 8 个 SkillSpec 版本化注册表（per-skill 评测维度）
│   ├── eval/                         # 评测系统
│   │   ├── __init__.py
│   │   ├── cases.py                  # EvalCase 定义与 curated/generalized/synthetic 用例管理
│   │   ├── runner.py                 # Eval 运行器（curated/generalized/synthetic 模式）
│   │   ├── baseline.py               # Baseline 对比（compare 双 JSON diff）
│   │   ├── metrics.py                # 评测指标（pass rate、token usage、tool call 统计）
│   │   ├── live_triage.py            # Live eval triage 报告（失败 root cause 分析）
│   │   ├── triage_bundle.py          # 失败分类体系（14 种有序标签）
│   │   ├── tau_loader.py             # tau3-bench 任务 → EvalCase 转换器
│   │   ├── tau_user_simulator.py     # tau3-bench 用户模拟器
│   │   ├── flywheel.py               # 数据飞轮（collect → generate → promote → check）
│   │   ├── bad_case_store.py         # Bad case 持久化存储与 rehydrate
│   │   └── golden_set.py             # Golden 回归用例管理
│   ├── synthetic/                    # 合成数据生成
│   │   ├── __init__.py
│   │   ├── generator.py              # Seed-based LLM 合成场景生成器
│   │   ├── families.py               # 场景族定义与变体生成（Phase 8a generalization）
│   │   ├── adapter.py                # 合成数据适配器
│   │   ├── language_variation.py     # 多语言变体生成
│   │   └── oracle.py                 # Oracle 验证（合成数据正确性判定）
│   ├── workbench/                    # Workbench 后端（FastAPI）
│   │   ├── __init__.py
│   │   ├── api.py                    # FastAPI 应用（REST 端点 + AgentOps 路由）
│   │   ├── cli.py                    # Workbench CLI 入口（uv run workbench）
│   │   ├── session.py                # 会话管理（session_id、state 缓存）
│   │   ├── cases.py                  # Demo 案例定义与加载
│   │   ├── agentops.py               # AgentOps 服务（trace 可视化 + KV cache 统计）
│   │   ├── agentops_models.py        # AgentOps 数据模型
│   │   ├── errors.py                 # 错误处理与 HTTP 异常
│   │   └── snapshot.py               # DB 快照管理
│   ├── ops/                          # 运维与审计
│   │   ├── __init__.py
│   │   ├── tracing.py                # TraceWriter（全链路审计输出）
│   │   └── serialization.py          # 序列化工具（model_dump、哈希计算）
│   ├── cli/                          # CLI 入口
│   │   ├── __init__.py
│   │   ├── chat.py                   # phase1-chat（脚本模式对话）
│   │   ├── eval.py                   # phase2-eval（eval runner CLI）
│   │   └── flywheel.py               # flywheel（数据飞轮 CLI）
│   └── analysis/                     # 任务分析
│       ├── __init__.py
│       └── tau_task_analyzer.py      # tau3 零售任务空间分析器（supported/partial/unsupported 分类）
├── workbench/                        # Workbench 前端（React + TypeScript + Vite）
│   ├── package.json                  # 前端依赖
│   ├── vite.config.ts                # Vite 构建配置
│   ├── tsconfig.json                 # TypeScript 配置
│   └── src/
│       ├── main.tsx                  # React 入口
│       ├── App.tsx                   # 根组件（路由 + 布局）
│       ├── index.css                 # 全局样式
│       ├── types.ts                  # TypeScript 类型定义
│       ├── labels.ts                 # 中文标签映射
│       ├── api.ts                    # Workbench REST API 调用层
│       ├── agentopsApi.ts            # AgentOps API 调用层
│       ├── agentopsTypes.ts          # AgentOps TypeScript 类型
│       ├── caseTreeUtils.ts          # 案例树工具函数
│       └── components/               # React 组件
│           ├── CaseTree.tsx           # 案例树导航
│           ├── Conversation.tsx       # 对话窗口
│           ├── MessageCard.tsx        # 消息气泡组件
│           ├── ToolCallCard.tsx       # 工具调用卡片
│           ├── StepCard.tsx           # AgentStep 卡片
│           ├── Timeline.tsx           # 时间线视图
│           ├── EventDetailPanel.tsx   # 事件详情面板
│           ├── EventCardHelpers.tsx   # 事件卡片辅助函数
│           ├── StatusBadge.tsx        # 状态徽章
│           ├── CollapseButton.tsx     # 折叠/展开按钮
│           ├── WriteAuditCard.tsx     # 写入审计记录卡片
│           ├── BusinessState.tsx      # 业务状态显示
│           ├── AgentOpsBrowser.tsx    # AgentOps 浏览器
│           ├── AgentOpsInspector.tsx  # AgentOps 审查器
│           └── AgentOpsWorkspace.tsx  # AgentOps 工作区
├── tests/                            # 测试
│   ├── test_agent_core.py            # Agent 核心测试
│   ├── test_session_state.py         # SessionState 测试
│   ├── test_context_builder.py       # 上下文构建测试
│   ├── test_tool_observations.py     # 工具观察测试
│   ├── test_tool_schema.py           # 工具 schema 测试
│   ├── test_eval_runner.py           # Eval runner 测试
│   ├── test_eval_cli.py              # Eval CLI 测试
│   ├── test_tau_loader.py            # tau3 加载器测试
│   ├── test_tau_user_simulator.py    # tau3 用户模拟器测试
│   ├── test_tau_task_analyzer.py     # 任务分析器测试
│   ├── test_live_eval_triage.py      # Live triage 测试
│   ├── test_flywheel.py              # Flywheel 数据飞轮测试
│   ├── test_bad_case_store.py        # Bad case 存储测试
│   ├── test_golden_set.py            # Golden 集合测试
│   ├── test_generalization.py        # 泛化测试
│   ├── test_cli_flywheel.py          # Flywheel CLI 测试
│   ├── test_skill_registry.py        # Skill 注册表测试
│   ├── test_synthetic.py             # 合成数据测试
│   ├── test_providers.py             # LLM provider 测试
│   ├── test_workbench_api.py         # Workbench API 测试
│   ├── test_workbench_cases.py       # Workbench 案例测试
│   ├── test_workbench_session.py     # Workbench 会话测试
│   ├── test_workbench_snapshot.py    # Workbench 快照测试
│   ├── test_workbench_agentops.py    # Workbench AgentOps 测试
│   ├── test_workbench_cli.py         # Workbench CLI 测试
│   └── test_workbench_errors.py      # Workbench 错误处理测试
├── examples/                         # 示例数据
│   └── chat/
│       ├── cancel_order.json         # 取消订单对话脚本
│       └── return_order.json         # 退货对话脚本
├── cases/                            # Bad case 收集与 Golden 回归用例
│   ├── bad_cases/                    # 失败案例沉淀（按日期 YAML 文件）
│   └── golden.yaml                   # Golden 回归用例集
├── docs/                             # 文档
│   ├── DESIGN_SPEC.md               # 设计规约
│   ├── portfolio-architecture.md     # 架构深度参考
│   ├── design-audit.md               # 设计审计报告
│   ├── design-llm-agent-tool-calling.md  # LLM Agent tool-calling 设计
│   ├── discussion-llm-agent-architecture.md  # 架构讨论
│   ├── discussion_with_cc.md         # 与 CC 的讨论记录
│   ├── data-flow.md                  # 数据流文档
│   ├── long-term-optimization-path.md  # 长期优化路线图
│   ├── phase5-capability-matrix.md   # Phase 5 能力矩阵
│   ├── tau-task-space-analysis.md    # tau3 任务空间分析
│   └── optimize/
│       ├── skill-assetization-retrospective.md       # Skill 资产化技术复盘
│       └── deepseek-kv-cache-optimization-retrospective.md  # KV Cache 优化技术复盘
└── .worktrees/                       # Git worktrees（实验分支，如 kv-cache-ab）
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
架构图参考见 [`diagrams/agentloop-mermaid.md`](diagrams/agentloop-mermaid.md)。

深度架构参考见 [`docs/portfolio-architecture.md`](docs/portfolio-architecture.md)。

完整路线图见 [`docs/long-term-optimization-path.md`](docs/long-term-optimization-path.md)。

设计审计报告见 [`docs/design-audit.md`](docs/design-audit.md)。

技术复盘：
- [Skill 资产化技术复盘](docs/optimize/skill-assetization-retrospective.md)
- [DeepSeek KV Cache 优化技术复盘](docs/optimize/deepseek-kv-cache-optimization-retrospective.md)
