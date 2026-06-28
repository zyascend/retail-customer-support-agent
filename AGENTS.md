# AGENTS.md

> Read by AI coding agents on session start. Also read `HANDOFF.md` for latest progress.

## ⚡ 省 Token 优先策略

本项目已通过 `codebase-memory-mcp` 建立完整的代码知识图谱（3,023 节点 / 10,402 边），**优先使用以下 MCP 工具探索代码，而非直接 Read/Grep/Bash**，可大幅节省 Token：

| 场景 | 推荐工具 |
|------|---------|
| 找函数定义 / 类 / 接口 | `search_graph` + `get_code_snippet` |
| 理解调用上下游 | `trace_path`（支持 calls / data_flow / cross_service） |
| 理解架构分层 | `get_architecture` |
| 批量 grep 搜索 | `search_code`（比 grep 更紧凑，支持语义上下文） |
| 追踪变更影响 | `detect_changes` |

**避免**：直接用 `Read` 读大文件全文、用 `Bash` 跑 grep/find/awk。先用 MCP 定位到具体函数/行，再按需局部读取。

## Project

LLM tool-calling 零售客服 agent。用户通过自然语言查询/修改订单——查状态、取消、退货、换货、改地址、改支付方式、改配送方式、转人工。所有写操作经 7 层 Guard 校验后才执行。

## Quick start

```bash
uv sync --extra dev
uv run phase2-eval --subset generalized_mvp --live --max-workers 50  # 跑 live eval
uv run flywheel check --no-progress --json                           # golden 回归检查
uv run python -m pytest tests/ -v                                     # 全量测试
```

## Architecture

```
user msg → AgentRuntime → AgentLoop ──LLM──→ DeepSeek (default)
                │              │
                ▼              ▼
         preflight        ToolGateway ──→ WriteActionGuard (7层)
         (身份/确认)         │              │
                            ▼              ▼
                       RetailAdapter   Skill Registry (8 skills)
                            │
                            ▼
                  tau3-bench / local db.json
```

- `app/agent/runtime.py` — 入口，preflight + AgentLoop 编排
- `app/agent/llm_agent.py` — while-loop: LLM ↔ tool execute，max 14 轮；含 token-aware 截断、premature refusal 纠正、数值修正
- `app/agent/guard.py` — 写安全：auth→ownership→read-before-write→policy→locks→idempotency
- `app/agent/confirmation.py` — 用户确认/拒绝/变更的关键词解析
- `app/agent/context_builder.py` — 语义化上下文描述（Active safeguards、loaded context 去重）
- `app/tools/registry.py` — 工具发现 + LLM schema 生成（含 when-to-use/when-not-to-use）
- `app/tools/gateway.py` — 唯一工具执行入口，写操作必经 Guard
- `app/skills/registry.py` — 8 个 SkillSpec 版本化单元；skill hash 用于 eval 归因；prompt 注入 `{skill_guidance}`
- `app/eval/flywheel.py` — 数据飞轮：collect bad case → generate variant → golden promote → check regression
- `app/eval/bad_case_store.py` — Bad case 持久化存储与 rehydrate
- `app/eval/golden_set.py` — Golden 回归用例管理
- `app/synthetic/generator.py` — Seed-based LLM 合成数据生成（含语言变体、oracle 验证）
- `app/ops/tracing.py` — TraceWriter，全链路审计输出
- `app/workbench/agentops.py` — AgentOps 服务，trace 可视化 + KV cache 统计
- `prompts/llm_agent_system_v001.md` — 系统 prompt 模板，含 `{skill_guidance}` 和 `{tool_catalog}` 占位符

## 写操作（8 个）

| 工具 | 前置条件 | 关键约束 |
|------|---------|---------|
| `cancel_pending_order` | pending | reason: "no longer needed"/"ordered by mistake" |
| `return_delivered_order_items` | delivered | item_ids 来自 get_order_details |
| `exchange_delivered_order_items` | delivered | old/new 数量匹配，new 同 product 且 available |
| `modify_pending_order_items` | pending | 同上 + 多商品一次调用 |
| `modify_pending_order_payment` | pending | 不能用于 cover replacement charges |
| `modify_pending_order_address` | pending | 需要完整地址 |
| `modify_pending_order_shipping_method` | pending | standard/express/overnight |
| `modify_user_address` | — | user_id 必须是认证用户 |

**单事实源**: `app/agent/action_specs.py` — 所有写操作的定义都从这里派生。

## 关键不变量

1. **写操作绝不绕过 Guard** — `ToolGateway` 是唯一入口
2. **LLM 绝不拒绝写操作** — 必须先调 write tool，让 Guard 决定（见 prompt CRITICAL 段）
3. **order_id 格式** — 正则 `#?(?:W)?(\d{7,})` → 规范化为 `#W\d+`
4. **Guard block ≠ failure** — block 是预期行为，不计入 consecutive_failure
5. **确认后不重做** — continuation prompt 含 "Do NOT repeat"

## 常见 footgun

- 改 `_normalize_order_id_argument` 的正则时注意多 `#` 前缀
- `AgentLoop` 的 `_maybe_correct_*` 方法只覆盖 5 种计算场景，新增场景需新增方法
- tau eval 的 order/user 数据来自外部 DB，不是 `db.json`
- `ConfirmationResolver` 的 `confirm < 2` 守卫不能随便改——会影响中英文混合场景
- `flywheel collect` 依赖 `--subset` 做 case rehydrate；report 不含 subset 时必须显式传入
- `flywheel generate` 只有带 `seed + variant_type` 的 synthetic/generalization case 才会生成变体
- `flywheel golden promote` 必须显式加 `--confirm`，否则直接失败
- 新增 Skill: 必须在 `skills/registry.py` 添加 `SkillSpec`，同时在 `action_specs.py` 定义写操作元数据
- `ENABLE_THINK_TOOL` 实验工具默认关闭，需全量 live eval A/B 后才能决定是否启用

## Eval 基线（2026-06-18）

| 子集 | Pass Rate |
|------|-----------|
| curated_mvp (11) | **100%** |
| generalized_mvp (30) | **100%** |
| synthetic_seeded_v1 (7) | **57%** (4/7, baseline 一致) |

Run: `uv run phase2-eval --subset <name> --live --max-workers 50`

## Commit 规范

`<type>: 中文描述` — feat/fix/chore/docs/refactor/test。分支: `git checkout -b <name>`。

## HANDOFF

HANDOFF.md 由 `/pr` 和 `/prm` 自动更新。记录 eval 基线、最近改动、下一步计划。
