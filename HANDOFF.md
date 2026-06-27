# HANDOFF — 2026-06-27

## 项目一句话

LLM tool-calling 零售客服 agent。Python FastAPI + React Workbench，核心是 7 层写安全 Guard、Skill 资产化、Bad Case 数据飞轮 + Golden 回归，以及 DeepSeek KV Cache 优化和 AgentOps 可视化。Phase 1a 已落地交互真实化（screen pop + 指代消解 + 打断 fallback），agent 在真实多轮对话里表现得像真人客服。

## 整体架构（Phase 1a 后，分层 + 时序）

**分层**（单向向下依赖，写操作绝不绕过 L3 Guard）：

```
L0 入口与生命周期    phase1-chat --customer / workbench / eval runner
                     会话建立 → ScreenPop (身份即设 + 主动查一次订单)
L1 编排层            AgentRuntime: preflight(identity/confirmation/transfer) + AgentLoop(LLM↔tool)
L2 上下文与确认      context_builder(state summary: 客户卡/订单商品名/pending参数)
                     confirmation(resolver + has_competing_signal)
L3 工具执行与写安全  ToolGateway(唯一入口) → WriteActionGuard(7层) + list_user_orders越权校验
L4 领域适配          RetailAdapter: read(list_user_orders/...) + write(8个) | tau3-bench/local db
L5 Skills 与 Prompt  8× SkillSpec(诉求→工作流) + system prompt(指代启发式+打断处理段)
L6 评测飞轮(横切)    realistic_conversation/curated/generalized/golden + evaluate_behaviors(行为rubric)
```

**时序**（一次真实对话）：
1. 会话建立 → ScreenPop：身份即设(渠道带入) + `get_user_details` 客户卡 + `list_user_orders` 预查订单 → agent 已"认识"客户
2. 用户消息 → preflight(identity? confirmation pending? transfer?) → AgentLoop
3. context_builder 算 state summary → LLM 推理(指代消解) → 调 tool
4. ToolGateway：read 直接执行 / write 经 Guard 7 层
5. Guard 要求确认 → pending_action → 等用户确认
6. 用户确认 → `_preflight_confirmation` 路由：干净→短路执行(`confirmed=True`) / mixed→LLM fallback(pending保持) / changed→丢弃(独立分支) / unknown→放行LLM
7. 执行/回复 → 循环

**路由不变量**：`confirmed=True` 永远只在干净确认 fast-path 传入；LLM fallback 不调 `gateway.execute`，Guard 确认层从不被绕过；changed 分支逐字节不动护基线。

## 最近合并（PR #50–#55）

### Phase 1a：交互真实化核心（分支 `phase1a-interaction-realism`，就绪待合并）

震撼三件套，让 agent 在真实多轮对话里像真人客服。spec: `docs/superpowers/specs/2026-06-27-phase1a-interaction-realism-design.md`，plan: `docs/superpowers/plans/2026-06-27-phase1a-interaction-realism.md`。

| commit | 内容 |
|--------|------|
| 97dc341 | `list_user_orders` read tool（LocalRetailTools） |
| 9de4b58 | list_user_orders 越权校验 + LLM schema 描述 |
| d04afb1 | `has_competing_signal` + `_has_question` |
| e3ddf4b | `_preflight_confirmation` 路由修正（changed 独立分支 + competing fallback） |
| e488d13 | context_builder 订单含商品名 + pending 含参数 |
| 1ee3a5f | ScreenPop helper（身份进线即设 + 主动查一次订单） |
| 5fd12a8 | screen pop 接入 run_script/chat --customer/workbench demo |
| 8819ea3 | prompt 指代消解启发式 + 打断处理段（generalized_mvp 30/30 不回归） |
| 23e8583 | realistic_conversation eval 子集 + 行为 rubric（3/3 pass） |

**基线 0 回归**：curated 11/11、generalized 30/30、golden 2/2、realistic_conversation 3/3。路由改动可由构造证明不回归（changed 逐字节不动，25 条确认消息逐分支 identical）；context_builder/prompt 改动经 eval 验证不回归。

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
| realistic_conversation (3) | **100%** (Phase 1a 新增，三件套行为验证) |
| synthetic_seeded_v1 (7) | **57%** (4/7，baseline 一致，无回归) |

命令：`uv run phase2-eval --subset <name> --live --max-workers 50`

Golden 回归（2 case）：
```bash
uv run flywheel check --no-progress --json   # modify_pending_order_address / modify_pending_order_payment_success
```

## 项目现状总结

**核心能力栈**:
- 7 层写安全 Guard（auth → confirmation → ownership → read-before-write → policy → locks → idempotency）
- 8 个写操作工具（cancel / return / exchange / modify items / payment / address / shipping / user address）
- **交互真实化（Phase 1a）**：ScreenPop 进线预查、list_user_orders 指代消解、has_competing_signal 打断 fallback（changed 独立分支护基线）
- 14 种失败标签分类体系 + 行为 rubric（screen_pop_preloaded / reference_resolved / interruption_handled / no_stale_pending）
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

1. **Phase 1b** — 多意图编排 / 跑题情绪降级 / 脏输入鲁棒性 / **CLOSING 工单+评价闭环** / step-up 敏感写验证
2. **Skill 文档化（独立小改）** — 8 个 SkillSpec 从 `registry.py` Python 迁到 `skills/*.md`（frontmatter + guidance），loader 启动时解析。降低维护门槛到"改 Markdown"，契合 demo"可维护客服系统"故事。演进方向 A 路径（动态按需加载）留待 skill 涨到 15+
3. **§2.2 Think 实验 A/B** — `ENABLE_THINK_TOOL=true` 跑 generalized_mvp / synthetic_seeded_v1，对比 pass rate / wrong_tool / avg_loop_iters / token_cost
4. **§1.1 提示词精简压缩** — 18 条规则 → 8-10 条，CRITICAL 段 35 行 → 5 行
5. **Golden 回归积累** — 从 bad case 中 promote 关键 case

### 中期

6. **Phase 2 真实聊天界面** — chat-first UI + 流式 + 会话持久感 + 订单上下文侧栏 + 生命周期可视化（工单状态条）；落地后视价值上 SessionOrchestrator 显式编排 4 阶段
7. **KV Cache 策略上卷** — 基于 AgentOps stats 做 system prompt 进一步稳定化
8. **Skill 评测面板** — Workbench AgentOps 中展示 per-skill pass rate 趋势
9. **§5.1 Guard 检查顺序调整** — 硬性 policy block 优先于 confirmation
10. **新增能力** — gift card apply / split shipment 等 tau 覆盖

### 长期

11. **Phase 3** — 真实场景库 + 行为 rubric 评测体系重建（realistic_conversation 扩到 12-15 case，覆盖属性指代/多订单消歧/脏输入）
12. Phase 12 Capability Expansion 后续
13. 跨 provider 兼容方案（OpenAI / Anthropic）

## 关键文件速查

- 入口：`app/agent/runtime.py`（`run_script` 含 `screen_pop_user_id`）
- Screen pop：`app/agent/screen_pop.py`（身份进线即设 + 主动查一次订单）
- Agent loop：`app/agent/llm_agent.py`（`_build_messages`、`_truncate_history`、`_maybe_correct_*`）
- 确认路由：`app/agent/confirmation.py`（`ConfirmationResolver`、`has_competing_signal`、`_has_question`）
- Guard：`app/agent/guard.py`（`_canonical_order_id`、`_validate_read_before_write`）
- 上下文：`app/agent/context_builder.py`（订单含商品名、pending 含参数、语义化去重）
- 工具网关：`app/tools/gateway.py`（`list_user_orders` 越权校验、`_guard_block_observation`）
- 工具注册表：`app/tools/registry.py`（`_raw_description`、`_property_schema`、think 注入）
- Skill 注册表：`app/skills/registry.py`
- 数据飞轮：`app/eval/flywheel.py`、`app/eval/bad_case_store.py`、`app/eval/golden_set.py`
- Eval runner：`app/eval/runner.py`（`classify_failure`、`evaluate_behaviors` 行为 rubric）
- 合成数据：`app/synthetic/generator.py`、`app/synthetic/families.py`
- 系统 prompt：`prompts/llm_agent_system_v001.md`（指代消解启发式 + 打断处理段第 12 条）
- 设计复盘：`docs/optimize/skill-assetization-retrospective.md`、`docs/optimize/deepseek-kv-cache-optimization-retrospective.md`
- Eval 案例：`app/eval/cases.py`（含 `REALISTIC_CONVERSATION_CASES`）
- AgentOps：`app/workbench/agentops.py`、`app/workbench/agentops_models.py`
