# LLM Agent Tool-Calling 架构讨论记录

日期：2026-06-13
参与者：用户 + Claude
产出：`docs/design-llm-agent-tool-calling.md`

## 背景

项目完成了 Phase 9（Full Tau Ingestion），进行了整体现状梳理。当前架构是 12-node 线性 pipeline，code 正则提取 intent/slot 后硬编码路由到 plan handler，LLM 只在 4 个环节做语义补充且不改变 code 决策。

在讨论架构时，用户提出了期望的架构方向：LLM tool-calling 为主，code 硬编码作为安全兜底。用户希望的效果是——告诉 LLM 有哪些 tools，把上下文喂给 LLM，让 LLM 自己决定调哪个工具、传什么参数。

## 讨论规则

用户首先设定了一条公约：

> 在改架构的过程中，如果原来的架构不符合现在的要求，直接可以完全摧毁重建。不必为了改的不多而放弃最佳实践。

这条公约影响了后续所有讨论——不再受"兼容现有 12-node pipeline"的约束，每个决策都从新架构的最佳实践出发。

## 问题 1：Pipeline 形态 — 还要不要 12 节点管线？

### 背景

当前架构是严格的线性 12 节点 pipeline（LangGraph StateGraph），每个节点有独立职责，节点间靠 state 传递信号。但 LLM tool-calling 模式下，决策过程是 LLM 内部的推理 + 工具反馈循环，不是分步骤的确定性逻辑。

### Claude 观点

不要 12 节点了。LLM tool-calling 本质是一个循环——LLM 推理 → 调工具 → 结果反馈 → 再推理。强行拆节点是给 LLM 套不合适的框架。建议简化为 3 阶段：pre_process → agent_loop → post_process。

### 讨论过程

用户追问：LangGraph 可以做这个循环吗？还是简单 while 就行？

Claude 分析后认为不需要 LangGraph——while 循环就够。LangGraph 提供的价值（节点编排、checkpoint、interrupt、streaming）在当前场景找不到必须的理由，反而增加框架依赖和调试复杂度。

但用户提出一个关键动机：这个项目的另一个目的是**学习 LangGraph 等 AGI 框架**。用户希望先用纯 while 循环实现第一版，但保留后续可以切换到 LangGraph 的口子。

### 最终决策

**纯 while 循环实现第一版。但循环体内的核心逻辑拆成 `step_*` 独立函数**：

- `step_llm_reason()` — 调用 LLM，处理响应
- `step_tool_execute()` — 通过 gateway 执行工具
- `step_finalize()` — LLM 结束对话
- `step_pending()` — guard 要求确认，设置 pending

每个 `step_*` 函数对应未来 LangGraph 的一个节点。后续切换到 LangGraph 就是把这几个函数注册到 StateGraph，加条件边，删除 while 循环——逻辑一行不改。

## 问题 2：State 模型 — 拆还是不拆？

### 背景

当前 `ConversationState` 有 20+ 字段，同时承载跨轮持久数据（session_id、messages、loaded_context）和单轮临时数据（current_intent、slots、policy_decision）。

### Claude 观点

应该拆成两层：

- **SessionState**：跨轮长生命周期。session_id、authenticated_user_id、messages、loaded_context、write_locks、audit_logs、pending_action。这些是事实记录 + 缓存，可以序列化。
- **TurnContext**：单轮短生命周期。steps、step_durations、llm_calls、termination。随单轮创建和销毁，只在内存中存在，不需要序列化。

拆的理由：
- 新架构中 `current_intent`、`slots`、`policy_decision` 三个字段不需要了——LLM 内部推理，不暴露为 state
- 单轮临时数据不污染持久状态
- SessionState 序列化为 trace artifact 更清晰

不拆的理由也给了（字段少一半，多一层心智负担），但用户选择了拆。

### 最终决策

**拆成 `SessionState` + `TurnContext`**。去掉 `current_intent`、`slots`、`policy_decision`、`confirmation_status`、`risk_level` 五个字段。

## 问题 3：Pre-flight 边界

### 背景

Code 的两项职责之一是 Token 优化——能为 LLM 省 token 的地方就做预处理。但怎么定义边界？哪些归 code 预处理，哪些归 LLM 自主决策？

### Claude 观点

只放三种场景进 pre-flight：

1. **确认短路**：`pending_action` 存在 + 用户消息是明确的 yes/no/change（`ConfirmationResolver` 能确定判定）→ code 直接执行或取消，完全不走 LLM
2. **认证快速通路**：消息中有明确的 email 或含 zipcode 的 name+zip → code 直接调 `find_user_id_by_*`
3. **信息注入**：构建 state_summary 告诉 LLM 已认证用户、已加载订单摘要等，LLM 不用自己再查

不放 pre-flight：
- intent 推断（交给 LLM）
- slot 提取（交给 LLM）
- 策略判断（交给 LLM，反正 guard 兜底）

有一个边界 case：取消原因（reason）。当前 code 用关键词映射 `"no longer needed"` / `"ordered by mistake"`。用户决定这个也交给 LLM——LLM 完全能理解"不太想要了"等于 "no longer needed"。

### 最终决策

**严格 3 种短路，没有例外**。intent、slot、reason、策略全部交给 LLM。

## 问题 4：System Prompt 维护方式

### 背景

当前 prompt 是 5 个版本化 Markdown 文件，code 在运行时加载拼接。新架构下 prompt 整合为一个，包含角色定义、工具目录、策略规则、状态摘要。

### Claude 观点

两个方案：

- A：一个大文件 + 模板变量。prompt 作为整体可读、可审查，策略规则变化时手动同步
- B：拆开多个文件拼接。策略变更自动更新，但多文件间逻辑连贯性不易验证

Claude 倾向 A，理由是 system prompt 各部分之间（如行为指南和工具描述）有依赖关系，拆开后难以验证自洽性。策略规则变化频率不高，手动同步不是大负担。

### 最终决策

**A：一个大文件 `prompts/llm_agent_system_v001.md`**，code 做模板变量替换（`{tool_catalog}`、`{policy}`、`{state_summary}`）。

## 问题 5：Eval 兼容性

### 背景

当前 EvalCase 有 `expected_intent`、`expected_tool_names`、`expected_assistant_contains` 等断言。LLM 模式下，intent 不输出了，工具调用顺序可能不同，回复文案不可精确预测。

### Claude 观点

- **保留**所有 DB 相关断言（status、write_lock、no_write、db_assertions）——不改
- **放宽**工具调用断言：`expected_tool_names`（精确序列）→ `required_tools`（必需工具集合）
- **放宽**回复断言：`expected_assistant_contains`（精确包含）→ 关键词包含
- **新增**LLM 专属指标：token 消耗、tool call 次数、LLM 延迟
- `expected_intent`、`expected_tool_sequence` 废弃

现有 93 个 deterministic case 不做破坏性修改。LLM 模式下 tau_retail_supported 的目标：32/69 → 55+/69。

### 最终决策

**保留 DB 断言，放宽工具和回复断言，废弃 intent 和 sequence 断言**。新增 LLM 专属指标。

## 讨论后的架构全景

```
用户消息
  │
  ├─ Pre-Flight (code)
  │   ├─ pending_action? → 确认短路（不走 LLM）
  │   ├─ 匹配到 email/name+zip? → 认证短路（减少 LLM 往返）
  │   └─ 构建 state_summary 注入 LLM
  │
  ├─ Agent Loop (LLM)
  │   ├─ step_llm_reason()     ─→ LLM.chat_with_tools()
  │   ├─ step_tool_execute()   ─→ gateway.execute()
  │   ├─ step_pending()        ─→ guard 要求确认
  │   └─ step_finalize()       ─→ LLM 输出文本回复
  │
  └─ Post-Processing (code)
      ├─ step 记录 + 计时
      ├─ audit_log 写入
      └─ trace artifact 输出
```

## Code 的两项职责

| 职责 | 具体内容 |
|------|---------|
| **安全兜底** | guard 不可绕过、工具白名单校验、迭代上限、连续失败保护、LLM 故障降级 |
| **Token 优化** | pre-flight 确定性短路、state_summary 压缩、对话历史裁剪、读工具结果摘要化 |
| **工程管道** | 日志记录、trace 写入、case 回放、eval report、Workbench snapshot（全部 code 负责） |

## 要删除的模块

| 模块 | 行数 | 原因 |
|------|------|------|
| `app/agent/pipeline.py` | 445 | 12 节点逻辑由 LLM loop 替代 |
| `app/agent/plan_handlers.py` | 277 | 8 个 intent 的 plan handler 由 LLM 替代 |
| `app/agent/graph.py` | 63 | LangGraph 编排不再需要（留迁移口子） |

## 要精简的模块

| 模块 | 保留 | 删除 |
|------|------|------|
| `app/agent/parsers.py` | `EMAIL_RE`、`NAME_ZIP_RE`、`ConfirmationResolver`、`clean_llm_*` | `infer_intent`、`parse_address`、`parse_item_replacement_pairs`、`parse_shipping_method`、`code_missing_slots`、`merge_policy_decisions` |
| `app/agent/builders.py` | 如果需要保留部分工具函数 | `merge_slots`、`pending_action_has_required_args`、`normalize_llm_action_arguments` |

## 新增模块

| 模块 | 职责 |
|------|------|
| `app/agent/llm_agent.py` | while 循环 + `step_*` 独立函数 |
| `app/agent/context_builder.py` | state_summary 构建 + 上下文压缩 |
| `prompts/llm_agent_system_v001.md` | 单一 system prompt 文件 |

## 实施路径

5 步逐步推进，每步独立可验证，不破坏现有 eval 绿色：

```
Step 1: Provider + Registry 扩展（不改 pipeline）
Step 2: State 拆分 + llm_agent 模块（独立于现有 pipeline）
Step 3: AgentRuntime 双模式调度
Step 4: Guard 结构化 context + 清理旧代码
Step 5: Token 优化 + Eval 适配
```
