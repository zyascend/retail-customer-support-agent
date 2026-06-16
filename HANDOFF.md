# HANDOFF — 2025-06-16

## 项目一句话

LLM tool-calling 零售客服 agent — Python FastAPI + React Workbench + 7 层写安全 Guard + eval 体系。

## 本会话做了什么

- 跑完全量 eval：151 cases，baseline pass rate **72.8%**
- 写了 harness engineering 优化分析报告：`docs/superpowers/specs/2025-06-16-harness-engineering-optimization.md`
- 修复 4 个 bug → pass rate **79.5%**（+10 cases）

## 修复的 4 个 bug

| Bug | 文件 | 改动 |
|-----|------|------|
| `##W...` 双 hash ID 导致 ValueError | `app/agent/llm_agent.py:1109` | `lstrip("#")` |
| 确认后 continuation loop 重做已完成操作 | `app/agent/runtime.py:291` | prompt 加 "Do NOT repeat" |
| 确认解析 change 误判优先于 confirm | `app/agent/confirmation.py:147` | +`confirm < 2` 守卫 |
| guard block 计入 consecutive failure | `app/agent/llm_agent.py:168` | 区分 block vs error |

## Eval 基线

| 子集 | Pass |
|------|------|
| generalized_mvp (30) | **100%** |
| tau_retail_supported (69) | 72.5% |
| generalization (45) | 80.0% |
| synthetic_seeded_v1 (7) | 57.1% |

命令：`uv run phase2-eval --subset <name> --live --max-workers 50`

## 下一步

1. **最高 ROI**：分析报告 §2.2 — 添加 `think` 工具，预期解决 remaining wrong_tool/confirmation 失败
2. 分析报告 §3.2 — 扩展 premature refusal 检测覆盖全部 8 个写工具
3. 分析报告 §4.1 — 自适应消息窗口

## 关键文件速查

- 入口：`app/agent/runtime.py` — `AgentRuntime.handle_user_message()`
- Agent loop：`app/agent/llm_agent.py` — `AgentLoop.run_turn()`
- Guard：`app/agent/guard.py` — `WriteActionGuard.check()`
- 工具注册：`app/tools/registry.py`
- Prompt：`prompts/llm_agent_system_v001.md`
- 分析报告：`docs/superpowers/specs/2025-06-16-harness-engineering-optimization.md`
- 实施计划：`docs/superpowers/plans/2025-06-16-harness-bug-fixes.md`
- 开发者指南：`CLAUDE.md`

## Recent

- **Merged 2026-06-16**: fix: Harness Engineering Bug 修复 - 全量 eval pass rate 72.8% -> 79.5%
