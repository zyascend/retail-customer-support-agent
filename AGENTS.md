# AGENTS.md

> Read by AI coding agents on session start. Also read `HANDOFF.md` for latest progress.

## Project

LLM tool-calling 零售客服 agent。用户通过自然语言查询/修改订单——查状态、取消、退货、换货、改地址、改支付方式、转人工。所有写操作经 7 层 Guard 校验后才执行。

## Quick start

```bash
uv sync --extra dev
uv run phase2-eval --subset generalized_mvp --live --max-workers 50  # 跑 eval
uv run python -m pytest tests/ -v                                     # 全量测试
```

## Architecture

```
user msg → AgentRuntime → AgentLoop ──LLM──→ DeepSeek
                │              │
                ▼              ▼
         preflight        ToolGateway ──→ WriteActionGuard (7层)
         (身份/确认)         │
                            ▼
                       RetailAdapter (tau2-bench / local db.json)
```

- `app/agent/runtime.py` — 入口，preflight + AgentLoop 编排
- `app/agent/llm_agent.py` — while-loop: LLM ↔ tool execute，max 14 轮
- `app/agent/guard.py` — 写安全：auth→ownership→read-before-write→policy→locks→idempotency
- `app/agent/confirmation.py` — 用户确认/拒绝/变更的关键词解析
- `app/tools/registry.py` — 工具发现 + LLM schema 生成
- `app/tools/gateway.py` — 唯一工具执行入口，写操作必经 Guard
- `prompts/llm_agent_system_v001.md` — 系统 prompt 模板

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

## Commit 规范

`<type>: 中文描述` — feat/fix/chore/docs/refactor/test。分支: `git checkout -b <name>`。

## HANDOFF

HANDOFF.md 由 `/pr` 和 `/prm` 自动更新。记录 eval 基线、最近改动、下一步计划。
