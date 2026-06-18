# HANDOFF — 2026-06-18

## 项目一句话

LLM tool-calling 零售客服 agent — Python FastAPI + React Workbench + 7 层写安全 Guard + eval 体系。

## 本会话做了什么

实现了 Harness Engineering 优化报告 §3 Agent Loop 设计中的 3 个优化项：

| § | 优化项 | 状态 |
|---|--------|------|
| 3.1 | 方案B：成功写操作 observation 注入预计算金额字段 | ✅ |
| 3.2 | 扩展 premature refusal 检测覆盖全部 8 个写工具 + status-based 拒绝 | ✅ |
| 3.3 | Guard block 不计入 consecutive failure（修复 + 回归测试） | ✅ |

### §3.1 详情

新增 `_enrich_success_observation()` 方法。取消/改商品/退货/换货成功后，observation 自动携带 `_precomputed` 字段（old_total、price_difference、gift_card_balance、most_expensive_item 等），LLM 直接读取无需自行计算。5 个 `_maybe_correct_*` 后验修正方法可大幅简化。

### §3.2 详情

- `_WRITE_INTENT_MAP` 从 4 个工具扩展到 8 个（新增 modify_pending_order_items、modify_pending_order_payment、modify_pending_order_shipping_method、modify_user_address）
- `_REFUSAL_PATTERNS` 新增 2 个 status-based 拒绝模式
- `_detect_premature_refusal` 从仅检查 ownership mismatch 改为同时检查 status-based 拒绝
- `_force_write_tool_call` 新增 4 个工具的句柄

### §3.3 详情

修复了计数 bug：原 `elif blocked: pass` 让 guard block 仍递增 consecutive_tool_failures。改为 `all_failed_technical = False`，确保 guard block 不触发「连续失败转人工」。追加 4 个回归测试锁定行为。

## 当前 Eval 基线

| 子集 | Pass |
|------|------|
| generalized_mvp (30) | **97%**（29/30，剩余 1 case 为 LLM flaky） |

命令：`uv run phase2-eval --subset <name> --live --max-workers 50`

## 下一步

1. **分析报告 §4.1/6.2** — Token-aware context budget（自适应消息窗口）
2. **分析报告 §1.1** — 提示词精简压缩
3. **分析报告 §3.4** — Multi-Provider 支持（Anthropic 对比 eval）

## 关键文件速查

- 入口：`app/agent/runtime.py` — `AgentRuntime.handle_user_message()`
- Agent loop：`app/agent/llm_agent.py` — `AgentLoop.run_turn()`
- Guard：`app/agent/guard.py` — `WriteActionGuard.check()`
- 工具注册：`app/tools/registry.py`
- Prompt：`prompts/llm_agent_system_v001.md`
- 分析报告：`docs/superpowers/specs/2025-06-16-harness-engineering-optimization.md`
- 开发者指南：`CLAUDE.md`

## Recent
- **PR opened 2026-06-18** (feat/agent-loop-optimization): fix: update agent behavior and regression coverage
- **PR opened 2026-06-18** (feat/agent-loop-optimization): docs: auto PR creation handoff update (+1 more)
- **PR opened 2026-06-18** (feat/agent-loop-optimization): docs: update HANDOFF.md with §3 Agent Loop design outcomes
- **Merged 2026-06-18**: feat/agent-loop-optimization — §3 Agent Loop 设计优化
- **Merged 2026-06-17**: auto: staged all changes
- **Merged 2026-06-16**: fix: Harness Engineering Bug 修复 - 全量 eval pass rate 72.8% -> 79.5%
