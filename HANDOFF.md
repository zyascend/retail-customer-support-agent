# HANDOFF — 2026-06-18

## 项目一句话

LLM tool-calling 零售客服 agent — Python FastAPI + React Workbench + 7 层写安全 Guard + eval 体系。

## 本会话做了什么

实现了 Harness Engineering 优化报告 §3（Agent Loop）和 §4（上下文管理）共 6 个优化项：

| § | 优化项 | 状态 |
|---|--------|------|
| 3.1 | 成功写操作 observation 注入预计算金额字段 | ✅ |
| 3.2 | 扩展 premature refusal 检测覆盖全部 8 个写工具 | ✅ |
| 3.3 | Guard block 不计入 consecutive failure | ✅ |
| 4.1/6.2 | Token-aware 上下文预算（固定 6 条 → 8000 token budget） | ✅ |
| 4.2 | ContextBuilder 语义化（Locks → Active safeguards） | ✅ |
| 4.3 | LoadedContext 订单 ID 去重 | ✅ |

### §4 上下文管理详情

- **4.1 Token 预算**: `_build_messages` 从 `messages[-6:]` 改为 token-aware 截断（`_truncate_history`），超预算时生成启发式摘要 `[Earlier: ...]`。`TurnContext` 新增 `context_truncation_count/summary`。
- **4.2 语义化**: `Locks:` → `Active safeguards:`（`cancellation in progress for #W123`）；guard block 错误码 → 可读描述；`_guard_block_observation` 不再泄漏原始 `block_context`。
- **4.3 ID 去重**: 提取共享 `_canonical_order_id()`（guard.py），订单 ID 统一 `#W\d+` 单 key 存储，非标准 ID 自动 fallback。

## 当前 Eval 基线

| 子集 | Pass |
|------|------|
| curated_mvp (11) | **100%** |
| generalized_mvp (30) | **100%** |
| synthetic_seeded_v1 (7) | **57%**（4/7，baseline 一致，无回归） |

命令：`uv run phase2-eval --subset <name> --live --max-workers 50`

## 下一步

按 Harness Engineering 优化报告优先级：

1. **§1.1** — 提示词精简压缩（18 条规则 → 8-10 条，CRITICAL 段 35 行 → 5 行）
2. **§1.3** — 添加显式停止条件
3. **§8.1** — JSON Repair 容错
4. **§2.3** — 参数 Schema 补全（state enum、zip regex、email regex）
5. **§5.1** — Guard 检查顺序调整（硬性 policy block 优先于 confirmation）

## 关键文件速查

- 入口：`app/agent/runtime.py`
- Agent loop：`app/agent/llm_agent.py`（`_build_messages`、`_truncate_history`、`_canonical_order_id`）
- Guard：`app/agent/guard.py`（`_canonical_order_id`、`_validate_read_before_write`）
- Context builder：`app/agent/context_builder.py`（`_describe_lock`、语义描述）
- 工具网关：`app/tools/gateway.py`（`_guard_block_observation`、`_update_loaded_context`）
- 分析报告：`docs/superpowers/specs/2025-06-16-harness-engineering-optimization.md`

## Recent
- **Merged 2026-06-18**: feat: 上下文管理三项优化 — token 预算截断、Guard 语义化、订单 ID 去重 (#44)
- **Merged 2026-06-18**: feat: Agent Loop 设计优化 — §3.1~3.3 (#43)
- **Merged 2026-06-17**: auto: staged all changes (#41)
- **Merged 2026-06-16**: fix: Harness Engineering Bug 修复 — 全量 eval 72.8% → 79.5%
