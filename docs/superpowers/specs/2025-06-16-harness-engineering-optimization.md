# Harness Engineering 优化分析报告

> 分析日期：2025-06-16
> 范围：全栈 harness 审查 — 提示词工程、工具定义、Agent Loop、上下文管理、Guard、Provider、确认流程、错误恢复、Eval 基础设施

---

## 一、提示词工程

### 1.1 系统提示词冗余 🔴 高优先级

**现状**: `prompts/llm_agent_system_v001.md` 共 ~215 行，包含 18 条规则 + CRITICAL 段（35 行）+ 8 个示例。规则 #4、#5 与 CRITICAL 段存在大量语义重叠。

**问题**:
- 18 条规则中有 7 条（#4, #5, #7, #8, #11, #14, #18）内容已隐含在工具描述中，形成双向冗余
- CRITICAL 段本质上是对规则 #4 的展开重复
- 规则 #12「用 loaded orders 推测最近订单」和规则 #17「避免穷举回退」属于高频场景的 micro-optimization，增大 prompt 复杂度

**建议**: 将 18 条规则压缩为 8–10 条核心原则；CRITICAL 段精简到 5 行禁令 + 1 个正例/反例对比。

### 1.2 缺少复杂场景 few-shot 🟡 中优先级

**现状**: 8 个示例全是单步操作（查状态 → 写操作 → guard 响应）。缺少多步骤组合示例。

**缺失场景**: 退货 + 计算退款金额；换货 + 差价计算 + gift card 余额；取消 + 报告最贵商品；多商品同时退货。

**建议**: 新增 3–4 个多步骤示例，覆盖「写操作成功后继续完成剩余子任务」路径。

### 1.3 缺少明确的停止条件 🔴 高优先级

**现状**: Agent Loop 依赖 LLM 自己判断何时结束。规则 #9 提到「complete multi-part requests」，但没有反向定义何时应停止。

**建议**: 在 prompt 中增加显式停止条件：
```
Stop and provide a final response when:
(a) all user-requested actions are complete, OR
(b) a guard block prevents progress and no alternative can help, OR
(c) you have exhausted available tools.
```

---

## 二、工具定义设计

### 2.1 工具描述与代码分离，存在漂移风险 🟡 中优先级

**现状**: `ToolRegistry._TOOL_DESCRIPTIONS` 和 `_ARG_DESCRIPTIONS` 是硬编码字典，与工具函数行为无耦合。修改函数签名后描述可能滞后。

**建议**: 从函数 docstring 自动提取描述（fallback 到硬编码字典）；或将描述作为 `__tool_description__` 属性挂在函数上。

### 2.2 缺少 `think` 工具 🔴 高优先级

**现状**: LLM 无结构化的「先思考再行动」空间，有时会跳过必要的读操作直接调写工具。

**建议**: 添加 `think(reasoning: str) → "ok"` 工具，类型为 `generic`。用于写操作前的显式推理。

### 2.3 参数 schema 约束可更严格 🟡 中优先级

**现状**: 只对 `order_id`、`item_ids`、`payment_method_id` 和极少数 enum 做了约束。

**缺失约束**: `state`（美国 50 州 `enum`）、`zip`（`^\d{5}$`）、`country`（`"enum": ["USA"]`）、`email`（`^[^@]+@[^@]+$`）。

**建议**: 补全所有参数级约束，减少 LLM 生成无效参数。

---

## 三、Agent Loop 设计

### 3.1 Response Correction 管道脆弱 🔴 高优先级

**现状**: 5 个 `_maybe_correct_*` 方法通过正则 + 状态检查修正 LLM 计算错误。每个新场景需要新增方法，维护成本线性增长。

**建议（方案 A，推荐）**: 用一个轻量验证 prompt（~200 tokens）做最终检查：「Given the tool results and the response below, does it contain calculation errors? If yes, output corrected response.」

**备选（方案 B）**: 将计算逻辑完全移出 LLM，在 tool observation 中注入预计算金额字段。

### 3.2 Premature Refusal 检测覆盖不全 🔴 高优先级

**现状**: `_REFUSAL_PATTERNS` 只匹配 ownership 相关 refusal。`_WRITE_INTENT_MAP` 只覆盖 4/8 个写工具。不检测 status-based refusal（如 "this order is processed, I cannot..."）。

**建议**:
- 扩展 `_WRITE_INTENT_MAP` 覆盖全部 8 个写工具
- 添加 status-based refusal pattern
- 长期：用小型 LLM 调用做 refusal 分类

### 3.3 Guard Block 不应计入 Consecutive Failure 🔴 高优先级

**现状** (`llm_agent.py:186-200`): `consecutive_tool_failures` 在 `all_failed=True` 时递增，包含 guard block。连续 3 次正常 guard block 会触发 `max_consecutive_failures` 错误终止。

**建议**: 区分「预期 block」和「非预期 failure」：
```python
if record.status == "blocked":
    pass  # guard blocks are expected behavior
elif record.status != "success":
    all_failed_technical = True
```

### 3.4 缺少 Multi-Provider 支持 🟡 中优先级

**现状**: `LLMProvider` 协议存在但只有 `DeepSeekProvider` 一个实现。协议未被用于多态。

**建议**: 实现 `AnthropicProvider`，启用模型对比 eval，同时验证协议设计的通用性。

---

## 四、上下文管理

### 4.1 固定 6 条消息窗口导致上下文丢失 🔴 高优先级

**现状**: `_build_messages` 只取 `session.messages[-6:]`。复杂换货场景（查订单→查产品→换货→确认→差价计算）可能超 6 轮，首轮用户请求被丢弃。

**建议**: 保留从最近一次成功写入以来的所有消息 + 早期对话摘要。或用 tiktoken 动态调整窗口。

### 4.2 ContextBuilder 暴露内部细节 🟡 中优先级

**现状**: State summary 包含 `Locks: order:#W1234567:cancel` 等技术细节，可能误导 LLM。

**建议**: 改用语义化描述：「Previous actions: cancellation was blocked (order belongs to another account)」。

### 4.3 LoadedContext 的 ID 重复存储 🟢 低优先级

**现状**: order ID 以 `clean_id`、`#clean_id`、原始格式三种形式存储。workaround 源于 ID 格式不统一。

**建议**: 在入口处统一 normalize 为 `#W\d+` 格式，消除重复存储。

---

## 五、Guard 机制

### 5.1 确认检查在策略检查之前 🟡 中优先级

**现状**: Guard 检查顺序为 auth → **confirmation** → ownership → read-before-write → **policy**。用户可能被要求确认一个最终会被 policy 拒绝的操作。

**建议**: 调整为 `auth → ownership → read-before-write → policy → confirmation → locks → idempotency`。

### 5.2 Guard 错误消息缺乏替代建议 🟡 中优先级

**现状**: Block 消息只告知原因，LLM 需自行推断替代方案。

**建议**: 在 `block_context` 中增加 `alternatives` 字段。例如 `ownership_violation` 的替代：「verify account identity」「transfer to human agent」。

### 5.3 Policy 验证是单体 if-else 链 🟢 低优先级

**现状**: `_validate_policy` 是长 if-else 链。新增写操作需新增分支。

**建议**: 长期考虑用 `action_specs.py` 的 `WriteActionSpec` 扩展声明式 policy rules。当前 8 个操作规模尚可管理。

---

## 六、Provider 抽象

### 6.1 无 Streaming 支持 🟡 中优先级

**现状**: 等待完整响应后解析才处理。用户感知延迟 = 网络 + LLM 推理 + 工具执行。

**建议**: 使用 OpenAI SDK `stream=True` + 增量 tool call 累积。前端通过 SSE 推送中间状态。

### 6.2 无 Token Budget 管理 🔴 高优先级

**现状**: 无 token 计数，上下文可能悄悄超出模型限制。

**建议**: 集成 `tiktoken`，在 `_build_messages` 中估算 token 数，超阈值时触发摘要或截断，并在 trace 中记录警告。

### 6.3 无指数退避重试 🟡 中优先级

**现状**: `max_retries=2`，固定间隔。

**建议**: 实现指数退避 + jitter，对 `RateLimitError` 和 `APITimeoutError` 分别处理。

---

## 七、确认流程

### 7.1 关键词评分边界不精确 🔴 高优先级

**现状**: `ConfirmationResolver` 用加权评分。`"yes, change it to X"` → confirm=3, change=3 → `change > confirm` → 误判为 `changed`。

**建议**: 当 confirm 和 change 评分接近（差值 ≤ 1）时，优先 confirm。
```python
if confirm >= change and confirm >= 2:
    return "confirmed"
```

### 7.2 缺少上下文感知 🟢 低优先级

**现状**: Resolver 不知道正在确认什么操作。

**建议**: 传入 `session.pending_action.user_facing_summary`，根据 risk 级别动态调整阈值。

### 7.3 Pending Action 无超时 🟢 低优先级

**现状**: 用户放弃会话后 pending action 永久存在。

**建议**: 增加 `created_at` 字段，超时（如 30 min）自动丢弃。

---

## 八、错误恢复与健壮性

### 8.1 JSON 解析失败无修复 🔴 高优先级

**现状**: `normalize_tool_calling_message` 中 `JSONDecodeError` 静默捕获，arguments 变为空 dict，浪费一次 loop iteration。

**建议**: 使用 `json-repair` 库修复常见 JSON 错误（尾部逗号、未转义引号、单引号）后再解析。

### 8.2 无 Rate Limit 处理 🟡 中优先级

**现状**: DeepSeek 429 被 SDK 抛异常，最终进入 `TimeoutError` 分支（分类错误）。

**建议**: 在 provider 层捕获 `RateLimitError`，读取 `Retry-After` header，等待后重试。

---

## 九、Eval & 测试 Harness

### 9.1 缺少回归测试基础设施 🟡 中优先级

**现状**: `phase2-eval` 可手动运行，不在 CI 中。修改 prompt 后无法自动检测退化。

**建议**: 建立 Golden Test Set（5–10 个 must-pass case）；添加 pre-commit hook；eval 结果包含与 baseline 的 diff。

### 9.2 Failure Classification 后置 🟢 低优先级

**现状**: `classify_failure()` 在 eval 完成后做分类，信息不与 trace 集成。

**建议**: 在 Agent Loop 执行中实时记录分类标签到 trace artifact。

---

## 十、整体架构

### 10.1 Prompt 版本管理可加强 🟢 低优先级

**现状**: 只有 template hash，注入后的 assembled prompt 无版本。

**建议**: trace 中同时记录 `prompt_template_hash` 和 `prompt_assembled_hash`。

### 10.2「永不拒绝」策略的边界讨论 🟢 低优先级

**现状**: CRITICAL 段强制 LLM 在所有情况下调用写工具。代价是多余的 tool call round-trip。

**建议**: 当前设计对安全场景正确。可考虑增加规则：若 loaded_context 中已有同 order 被 guard 以相同原因拒绝的记录，本次 turn 可直接告知用户。

---

## 优先级汇总

### 🔴 高优先级（建议优先实施）

| # | 优化项 | 影响面 | 改动量 |
|---|--------|--------|--------|
| 3.3 | 区分 Guard Block 和 Failure 计数 | Loop 健壮性 | 小（~5 行） |
| 7.1 | 确认解析 confirm/change 边界修正 | 用户体验 | 小（~3 行） |
| 8.1 | JSON Repair 容错 | 容错性 | 小 |
| 1.1 | 提示词精简压缩 | Token 效率 | 中 |
| 1.3 | 添加停止条件 | Loop 效率 | 小 |
| 2.2 | 添加 Think 工具 | 推理质量 | 中 |
| 3.1 | Response Correction → LLM 验证 | 维护性 | 中 |
| 3.2 | 扩展 Refusal 检测覆盖 | 安全兜底 | 中 |
| 4.1 | 自适应消息窗口 | 复杂场景 | 中 |
| 6.2 | Token Budget 管理 | 稳定性 | 中 |

### 🟡 中优先级

| # | 优化项 | 影响面 | 改动量 |
|---|--------|--------|--------|
| 1.2 | 复杂场景 few-shot | 准确度 | 中 |
| 2.1 | 工具描述自动生成 | 维护性 | 中 |
| 2.3 | 参数 Schema 补全 | 参数质量 | 小 |
| 3.4 | Multi-Provider 支持 | 可扩展性 | 大 |
| 4.2 | ContextBuilder 语义化 | 提示词质量 | 小 |
| 5.1 | 调整 Guard 检查顺序 | 用户体验 | 中 |
| 5.2 | Guard 替代建议 | 用户体验 | 小 |
| 6.1 | Streaming 支持 | 感知性能 | 大 |
| 6.3 | Provider 指数退避 | 稳定性 | 小 |
| 8.2 | Rate Limit 处理 | 稳定性 | 小 |
| 9.1 | Golden Test Set | 质量保障 | 中 |

### 🟢 低优先级

| # | 优化项 | 影响面 | 改动量 |
|---|--------|--------|--------|
| 4.3 | LoadedContext 去重 | 代码整洁 | 小 |
| 5.3 | Policy 声明式配置 | 可维护性 | 大 |
| 7.2 | Context-aware 确认 | 精度 | 中 |
| 7.3 | Pending Action 超时 | 边界情况 | 小 |
| 9.2 | Trace 集成分类 | 调试体验 | 中 |
| 10.1 | Assembled Prompt Hash | 可追溯性 | 小 |
| 10.2 | 重复 block 短路 | Token 效率 | 中 |
