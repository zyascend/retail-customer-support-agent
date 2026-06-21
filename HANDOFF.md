# HANDOFF — 2026-06-20

## 项目一句话

LLM tool-calling 零售客服 agent。Python FastAPI + React Workbench，核心是 7 层写安全 Guard、Skill 资产化、Bad Case 数据飞轮 + Golden 回归，以及 DeepSeek KV Cache 优化和 AgentOps 可视化。

## 最近合并（PR #50–#55）

| PR | 内容 | 状态 |
|----|------|------|
| #55 | **Skill 资产化与评测维度接入** — 8 个写操作行为知识收敛到 `app/skills/registry.py` 的 `SkillSpec`；per-skill eval hash 追踪；prompt 注入 `{skill_guidance}` | ✅ |
| #54 | 补充 flywheel 与 golden 使用 SOP 到 README | ✅ |
| #53 | **修复确认后重复触发待执行写操作** — continuation prompt 添加 "Do NOT repeat" 守卫 | ✅ |
| #52 | **落地 Bad Case 数据飞轮与 Golden 回归链路** — `flywheel collect/generate/promote/check` CLI | ✅ |
| #51 | Bad Case 数据飞轮设计与实施计划文档 | ✅ |
| #50 | **打通 DeepSeek KV Cache 命中观测链路** — AgentOps KV cache stats + `@cache_hit_tokens` / `@cache_miss_tokens` | ✅ |
| #49 | Provider JSON 容错与限流重试 | ✅ |
| #46 | 工具定义三项优化: 参数 schema 补全 / 描述单一事实源 / 实验性 think 工具 | ✅ |
| #44 | 上下文管理三项优化: token 预算截断 / Guard 语义化 / 订单 ID 去重 | ✅ |

### Phase 10–12 的前期规划文档已产出

- Phase 10: Prompt/Tool Schema 优化 (`docs/superpowers/plans/2026-06-15-phase10-prompt-tool-schema-optimization.md`)
- Phase 11: Workbench AgentOps (`docs/superpowers/specs/2026-06-15-phase11-workbench-agentops-design.md`)
- Phase 12: Capability Expansion & τ Coverage (`docs/superpowers/plans/2026-06-15-phase12-capability-expansion-tau-coverage.md`)
- Prompt 优化 Part 1 Design (`docs/superpowers/specs/2026-06-17-prompt-optimization-part1-design.md`)
- Bad Case Flywheel Design (`docs/superpowers/specs/2026-06-19-bad-case-flywheel-design.md`)

## 当前 Eval 基线

| 子集 | Pass |
|------|------|
| curated_mvp (11) | **100%** |
| generalized_mvp (30) | **100%** |
| synthetic_seeded_v1 (7) | **57%** (4/7，baseline 一致，无回归) |

命令：`uv run phase2-eval --subset <name> --live --max-workers 50`

Golden 回归（当前为空集）：
```bash
uv run flywheel check --no-progress --json
```

## 项目现状总结

**核心能力栈**:
- 7 层写安全 Guard（auth → confirmation → ownership → read-before-write → policy → locks → idempotency）
- 8 个写操作工具（cancel / return / exchange / modify items / payment / address / shipping / user address）
- 14 种失败标签分类体系
- Token-aware 上下文预算（8000 token L4，超限摘要）
- Think 实验工具（`ENABLE_THINK_TOOL=true`，默认 off）
- Provider JSON 容错 + 限流重试（最多 2 次）
- KV Cache 命中观测（AgentOps 面板链路已打通）

**数据飞轮链路已落地**:
1. `--live` eval 失败 → `flywheel collect` → `cases/bad_cases/<date>.yaml`
2. 种子 case → `flywheel generate` → 扩展变体
3. 关键 case → `flywheel golden promote --confirm` → `cases/golden.yaml`
4. `flywheel check` → 回归检测

**Skill 资产化已就绪**:
- `app/skills/registry.py`: 8 个 SkillSpec，含 intent_pattern / entry_tools / guard_constraints / prompt_guidance / few_shot_examples
- `SKILL_BY_ACTION` 字典将 eval case 映射到 skill_id
- `skill_hashes()` 在 baseline 中记录 per-skill 变更 hash

## 下一步

### 短期（高优先级）

1. **§2.2 Think 实验 A/B** — `ENABLE_THINK_TOOL=true` 跑 generalized_mvp / synthetic_seeded_v1，对比 pass rate / wrong_tool / avg_loop_iters / token_cost
2. **§1.1 提示词精简压缩** — 18 条规则 → 8-10 条，CRITICAL 段 35 行 → 5 行
3. **§1.3 显式停止条件** — 添加 LLM loop 提前停止逻辑
4. **Golden 回归积累** — 从 bad case 中 promote 关键 case

### 中期

5. **KV Cache 策略上卷** — 基于 AgentOps stats 做 system prompt 进一步稳定化
6. **Skill 评测面板** — Workbench AgentOps 中展示 per-skill pass rate 趋势
7. **§5.1 Guard 检查顺序调整** — 硬性 policy block 优先于 confirmation
8. **新增能力** — gift card apply / split shipment 等 tau 覆盖

### 长期

9. Phase 12 Capability Expansion 后续
10. 跨 provider 兼容方案（OpenAI / Anthropic）

## 关键文件速查

- 入口：`app/agent/runtime.py`
- Agent loop：`app/agent/llm_agent.py`（`_build_messages`、`_truncate_history`、`_maybe_correct_*`）
- Guard：`app/agent/guard.py`（`_canonical_order_id`、`_validate_read_before_write`）
- 上下文：`app/agent/context_builder.py`（`_describe_lock`、语义化、去重）
- 工具网关：`app/tools/gateway.py`（`_guard_block_observation`、`_update_loaded_context`）
- 工具注册表：`app/tools/registry.py`（`_raw_description`、`_property_schema`、think 注入）
- Skill 注册表：`app/skills/registry.py`
- 数据飞轮：`app/eval/flywheel.py`、`app/eval/bad_case_store.py`、`app/eval/golden_set.py`
- 合成数据：`app/synthetic/generator.py`、`app/synthetic/families.py`
- 系统 prompt：`prompts/llm_agent_system_v001.md`
- 设计复盘：`docs/optimize/skill-assetization-retrospective.md`、`docs/optimize/deepseek-kv-cache-optimization-retrospective.md`
- Eval 案例：`app/eval/cases.py`
- AgentOps：`app/workbench/agentops.py`、`app/workbench/agentops_models.py`
