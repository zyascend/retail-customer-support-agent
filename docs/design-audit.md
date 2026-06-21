# 架构设计审计

> 对照 Prompt、Tool、AgentLoop 三个生产级清单的系统评估。
> 本文件记录每项检查的结论和关键证据，区分"客服场景无需修"和"值得改进"。

---

## 一、Prompt 设计清单

### 1.1 身份/规则/工具/输出是否分开组织

| 现状 | 评估 |
|------|------|
| 6 个 prompt 文件，5 个是 Phase 1-4 的幽灵文件（已清理） | ✅ 已修复 |
| 实际运行时只使用 `llm_agent_system_v001.md` 一个巨石 prompt | ⚠️ 单块，但暂不需要拆分 |
| `prompts.py` 现在只追踪一个 prompt 的 SHA-256 | ✅ 清理后干净 |

**证据：** `prompts.py` 现在只有 `AGENT_SYSTEM_PROMPT` + `prompt_metadata()`。

### 1.2 是否明确 prompt 的优先级来源

| 现状 | 评估 |
|------|------|
| `core_contract_v001.md` 中提过「policy 优先于 general knowledge」 | ⚠️ 有提及但无分层体系 |
| 没有 default / project / custom / per-agent 的优先级标注 | ❌ 缺失 |

**影响：** 低。客服 agent 的 prompt 来源单一（一个文件），没有多层叠加的需求。

### 1.3 危险动作是否写成明确规则

| 现状 | 评估 |
|------|------|
| 「Never Refuse Without Calling the Write Tool」有 ⚠️ 标记 + WRONG/RIGHT 对比 | ✅ 非常充分 |
| 「Confirmation via guard, not via text」三次强调 | ✅ 非常充分 |
| `policy_reasoner_v001.md` 同等规则（已删除但主体仍在 `llm_agent_system` 中） | ✅ 已整合 |

**证据：**
```markdown
## ⚠️ CRITICAL: Never Refuse Without Calling the Write Tool
**This is the most important rule.**
```

### 1.4 是否避免 prompt 负担 runtime 职责

| 现状 | 评估 |
|------|------|
| Guard 层检查的事（ownership/status/items）prompt 不重复决策 | ✅ 正确 |
| `_maybe_correct_*` 系列 15+ 个修正函数是危险信号 | ⚠️ prompt 没说清楚→runtime 补锅 |

**建议：** 将 `_maybe_correct_*` 的逻辑提炼回 prompt 或统一到 `ContextBuilder` 中，减少运行时修正代码。

### 1.5 是否允许团队稳定维护

| 现状 | 评估 |
|------|------|
| 已清理 5 个幽灵文件 | ✅ 大幅改善 |
| 改一个操作只需改 `action_specs.py` + `llm_agent_system_v001.md` | ✅ 单一事实来源成立 |
| 仍有 `_maybe_correct_*` 代码在补偿 prompt 没说清的地方 | ⚠️ 长期应收敛 |

---

## 二、Tool 与 Permission 设计清单

### 2.1 工具调用是否经过统一调度

| 现状 | 评估 |
|------|------|
| `ToolGateway.execute()` 是唯一入口 | ✅ 非常明确 |
| LLM 不直接调用任何工具函数 | ✅ |
| pre-flight、auto-load、premature refusal 都走 Gateway | ✅ |

**证据：** `gateway.py` 第 23 行 `class ToolGateway` → `def execute()` → 所有 AgentLoop 中的 `_gateway.execute()` 调用。

### 2.2 并发是否需要显式证明安全

| 现状 | 评估 |
|------|------|
| 完全同步串行执行，不存在并发问题 | ✅ 天然安全 |
| Guard 第 6 层资源锁为并发做了预备但从未被触发 | ⚠️ 死代码级保护 |

**结论：** 客服场景不需要并发工具执行。**不需改。**

### 2.3 是否存在 allow / deny / ask 语义分叉

| 层次 | 语义 | 状态 |
|------|------|------|
| `WriteActionGuardResult.allowed` | `True` / `False` + 47+ 种 `block_reason` | ✅ |
| `PolicyDecision.decision` | `allow` / `ask_clarification` / `deny` / `transfer` | ✅ |
| `ToolCallRecord.status` | `success` / `blocked` / `error` | ✅ |
| `ConfirmationResolver` | `confirmed` / `denied` / `changed` / `unknown` | ✅ |

**证据：** 每条阻断携带结构化上下文如 `{"policy_area": "order_status", "allowed_values": ["pending"]}`。

### 2.4 高风险工具是否被当成特例治理

| 工具类型 | Guard 处理 | 状态 |
|---------|-----------|------|
| Read（`get_*` / `find_*` / `list_*`） | 不经 Guard，直接执行 | ✅ |
| Generic（`calculate` / `transfer_to_human`） | 不经 Guard，直接执行 | ✅ |
| Write（`cancel_*` / `modify_*` / `return_*` / `exchange_*`） | 7 层 Guard 全过 | ✅ |

**默认安全：** 所有未显式标注的工具被默认分类为 `write`。

### 2.5 是否能对中断/fallback/sibling failure 生成收尾语义

| 场景 | 当前行为 | 评估 |
|------|---------|------|
| 全部成功 | `termination = "final_response"` | ✅ |
| 全部失败 | `termination = "consecutive_failures"` | ✅ |
| 部分成功（N/M 个工具成功） | 无明确报告 | ❌ |
| 资源锁泄漏 | 锁留在 `session.write_locks` 中无人清理 | ❌ |

**建议修复：** 在 `AgentTurnResult` 中增加 `partial_success` 字段，记录已成功/失败/未执行的工具。非正常终止时清理该 turn 产生的 write locks。

### 2.6 能否记录工具执行因果链

| 记录内容 | 状态 |
|---------|------|
| 每个工具的 `ToolCallRecord`（名称、参数、状态、观察、DB 哈希、幂等键、资源锁） | ✅ |
| 工具之间的因果关系（A 的结果→LLM→调用了 B） | ❌ 平的列表 |
| 触发 auto-load 的父工具 | ❌ 仅 step log 有 `auto_load_order` 节点 |

**建议修复：** 在 `ToolCallRecord` 中增加 `triggered_by_call_id` 字段，将同一 turn 内的工具链关联起来。对客服场景影响较小，但有利于调试和 trace 分析。

---

## 三、AgentLoop / Runtime 设计清单

### 3.1 是否存在明确的 query loop

| 现状 | 评估 |
|------|------|
| `AgentLoop.run_turn()` 的 `while turn.loop_iterations < max_iterations` | ✅ |
| 硬编码 `max_iterations=14` | ✅ 客服场景足够 |
| 无自适应退出/预算感知 | ✅ 不需要 |

### 3.2 是否有跨轮状态对象

| 现状 | 评估 |
|------|------|
| `SessionState` 含 session_id、messages、loaded_context、tool_results 等 | ✅ |
| 缺少 `compression_count` / `budget_remaining` | ⚠️ 客服场景轻量 |
| 缺少 `serialize()` / `deserialize()` / checkpoint | ⚠️ 但 DB 本身就是持久化 |
| 缺少 `PendingAction` 崩溃恢复 | ⚠️ 概率极低 |

### 3.3 是否把模型输出当事件流处理

| 现状 | 评估 |
|------|------|
| 完全同步请求-响应 | ✅ 客服场景正确选择 |
| 不支持 streaming / SSE / 并行工具 | ✅ 不需要 |

**理由：** 客服 agent 没有 "streaming 代码"、"渐进式填充" 的需求。强行 streaming 反而在 guard 检查完成前就暴露了执行意图。

### 3.4 是否能在中断时补齐未完成的 tool result

| 现状 | 评估 |
|------|------|
| 有终止检测（consecutive_failures / max_iterations / provider_timeout） | ✅ |
| 无部分执行回滚 / 补偿事务 | ⚠️ 客服场景风险低 |
| 资源锁泄漏是唯一真问题 | ❌ |

### 3.5 是否区分完成/失败/恢复/继续

| 终止语义 | 存在？ | 使用场景 |
|---------|--------|---------|
| `final_response` | ✅ | 正常完成 |
| `pending_confirmation` | ✅ | 等待用户确认 |
| `consecutive_failures` | ✅ | 转人工 |
| `max_iterations` | ✅ | 转人工 |
| `provider_timeout` | ✅ | 重试 |
| `escalated`（已升级给人类） | ❌ | 与 `final_response` 混在一起 |

### 3.6 是否为长会话设计了 context budget

| 现状 | 评估 |
|------|------|
| `ContextBuilder` 目标 1200 tokens | ✅ 对有明确终点的客服对话足够 |
| `messages[-6:]` 硬编码截断 | ⚠️ 可优化为 token 感知 |
| 无分代压缩 / 自适应窗口 | ✅ 客服场景不需要 |

---

## 四、综合健康度

### 4.1 各维度评分

| 领域 | 评分 | 关键强项 | 关键弱项 |
|------|------|---------|---------|
| **Prompt** | ⚠️ 3.5/5 | 危险规则明确、已清理幽灵文件 | `_maybe_correct_*` 修正函数膨胀 |
| **Tool & Permission** | ✅ 4.5/5 | Gateway 统一调度、7 层守卫、高风险特例治理 | 中断收尾语义、因果链缺失 |
| **AgentLoop / Runtime** | ⚠️ 3.5/5 | Query loop 有明确的终止边界 | 资源锁泄漏、无 escalated 语义 |

### 4.2 值得做的改进（按优先级）

| 优先级 | 改进项 | 领域 | 工作量 |
|--------|-------|------|--------|
| 1 | 非正常终止时清理 `write_locks` | Runtime | ~5 行 |
| 2 | `AgentTurnResult` 加 `partial_success` 记录 | Tool | ~10 行 |
| 3 | `ToolCallRecord` 加 `triggered_by_call_id` | Tool | ~10 行 |
| 4 | 将 `_maybe_correct_*` 规则提炼回 prompt | Prompt | 需设计评审 |
| 5 | `messages[-6:]` 改为 token 感知截断 | Runtime | ~15 行 |

### 4.3 客服场景的战略优势

这个项目的安全决策从 LLM 剥离到了 Guard 层。Prompt 说「调用工具就好，让 Guard 决定」，AgentLoop 说「调用了工具就循环，阻塞了就走确认」，Gateway 说「write 走 Guard，其余直接执行」，Guard 说「7 层检查，过就放行，不过给原因」。所有安全边界由代码定义，而不是靠 prompt 约束 LLM 自觉遵守。

---

*文档版本: 1.0 · 审计日期: 2026-06-15 · 对应 commit: acc411f*
