# Prompt 优化分析：借鉴 Claude Code 设计理念

> 对比当前项目 prompt 与 Claude Code 的 prompt engineering 模式，提出优化方向。

---

## 一、Claude Code Prompt 设计核心原则

Claude Code 的系统 prompt（当前上下文即为其实例）体现了以下设计哲学：

| 原则 | Claude Code 实践 | 当前项目状态 |
|------|-----------------|-------------|
| **身份契约 (Identity Contract)** | 明确的角色定义："senior engineering collaborator inside DeepSeek GUI" | ❌ 只说了 "You are the X node"，无角色约束 |
| **行为约束 (Behavioral Rules)** | "Preserve user intent exactly", "Prefer small coherent changes" | ❌ 几乎没有行为层面的约束 |
| **否定约束 (Negative Constraints)** | "Do NOT do X" 频繁出现，优先级高于正面引导 | ⚠️ 仅 action_planner 有一条 "Do not emit" |
| **稳定可缓存前缀 (Cache-Stable Prefix)** | 整个 system prompt 保持 byte-stable，利用 DeepSeek prompt-cache | ❌ 当前 prompt 太短，且缺乏缓存意识 |
| **工具使用规则 (Tool Usage Rules)** | 每个工具附带具体的使用场景说明 | ❌ 工具描述在 Python 端，LLM 不可见 |
| **输出格式约束 (Output Format)** | 精确到 thinking block、tool call JSON 的结构 | ⚠️ 仅要求 "Return only JSON"，无格式细节 |
| **错误恢复指引 (Error Recovery)** | "When uncertainty matters, inspect files or ask" | ❌ 无错误处理指导 |
| **渐进式上下文 (Progressive Disclosure)** | 稳定前缀 + 可变载荷分离，利用缓存 | ⚠️ 有分离但太简单 |
| **Few-shot 示例** | Tool descriptions 本身作为示例 | ❌ 完全零示例 |
| **Chain-of-Thought 引导** | thinking block 触发结构化推理 | ❌ 无推理链引导 |
| **具体性 > 抽象性** | "使用 `read`/`grep`/`find`/`ls` 进行探索" 而非 "查看文件" | ⚠️ 有具体动作名但缺使用场景 |

---

## 二、逐 Prompt 诊断

### 2.1 `intent_slot_v001.md` — 当前 31 行

**现状**：
```markdown
You are the intent_and_slot_extractor node for a retail customer support agent.
Return only JSON.

Supported intents: lookup, cancel_order, modify_order_address, ...
Return shape: { "intent": "...", "slots": { ... } }
Do not invent ids or address fields. Use null or omit missing values.
```

**问题**：
1. 没有说明什么时候用哪个 intent — 给了 7 个 intent 但没有任何分类指引
2. 没有说明 slots 之间的依赖关系（如 `item_ids` 和 `new_item_ids` 的判分规则）
3. 没有给出真实世界的示例（含噪声的用户输入 → 期望输出）
4. 没有处理歧义的指导（用户同时提到取消和退货怎么办）
5. 没有说明上下文信息（`known_slots`、`authenticated_user_id`）的含义和使用方式

**Claude Code 式优化方向**：
```markdown
## Identity
你是零售客服助手的意图识别器。你的输出直接影响后续策略审查和动作执行。

## Behavioral Rules
- 基于用户消息和已知槽位推理 intent，不要猜测缺失的 ID 或地址
- 如果用户同时表达了多个意图，优先选择最具体的（cancel > modify_address > return > exchange > lookup > transfer）
- 如果完全无法确定意图，返回 "unknown"，不要强行匹配
- **不要**从对话历史或记忆中编造 order_id、item_id 等标识符

## Intent Classification Guide
### cancel_order
触发条件：用户明确要求取消订单，包含 "cancel" 关键词
对比 return_items："cancel" 针对整个订单，"return" 针对订单中的商品

### return_items  
触发条件：用户要求退回已收到的商品，包含 "return" 关键词
与 exchange_items 的区别：return 只退回不换新商品

### exchange_items
触发条件：用户要求换货，包含 "exchange" 或 "replace" 或 "instead" 关键词
必须同时提取 old item_ids 和 new_item_ids

### modify_order_address
触发条件：用户要求修改收货地址，同时包含 address 关键词 + change/modify/update 关键词
与 lookup 的区别：modify 是修改行为，lookup 只是查询

### lookup
触发条件：用户仅查询订单信息，无修改/操作意图
包含 "what is", "status", "show me", "track" 等查询关键词

### transfer
触发条件：用户明确要求转人工，包含 "human", "agent", "representative", "person", "客服" 等关键词
**不要**在常规查询失败时自动转 transfer

### unknown
默认值。当上述都不匹配时返回此值

## Slot Extraction Rules

### order_id
格式：`#W` 后跟 7 位数字，如 `#W5918442`
用户可能说 "order #W5918442"、"订单号 #W5918442"、"the order ending in 18442"
如果已知槽位中已有 order_id 且新消息中未提及，保留原值

### item_ids
8 位以上纯数字，如 `6777246137`
不要提取纯零开头的 ID（如 `00012345678`）
如果用户说 "return item 6777246137"，则 item_ids = ["6777246137"]

### reason
仅限 "no longer needed" 或 "ordered by mistake"
用户说 "don't need it anymore" → "no longer needed"
用户说 "made a mistake" / "wrong item" → "ordered by mistake"
如果都不匹配，留空

## Examples

### Example 1: 标准取消
User: "My email is sofia.rossi2645@example.com. Cancel order #W5918442 because no longer needed."
Response:
```json
{
  "intent": "cancel_order",
  "slots": {
    "order_id": "#W5918442",
    "reason": "no longer needed"
  }
}
```

### Example 2: 含新商品 ID 的换货
User: "exchange item 6777246137 from order #W4817420 instead 4579334072"
Response:
```json
{
  "intent": "exchange_items",
  "slots": {
    "order_id": "#W4817420",
    "item_ids": ["6777246137"],
    "new_item_ids": ["4579334072"]
  }
}
```

### Example 3: 歧义输入
User: "I want to return or exchange, not sure yet"
Response:
```json
{
  "intent": "unknown",
  "slots": {}
}
```

### Example 4: 查询
User: "What is the status of my order?"
Response:
```json
{
  "intent": "lookup",
  "slots": {}
}
```

## Output Format
返回纯 JSON 对象，不要包含 markdown 代码块标记，不要包含解释文本。
```

---

### 2.2 `policy_reasoner_v001.md` — 当前 6 行（⚠️ 最严重的欠设计）

**现状**：
```markdown
You are the policy_reasoner node. Return only JSON.
Decisions: allow, ask_clarification, deny, transfer
Use policy constraints, loaded context, and slots.
Do not authorize a write just because the user asked for it;
writes still require explicit user confirmation.
```

**问题**：
1. **仅 6 行** — 这是整个 agent 的安全关键节点，却给了最少的信息量
2. 没有说明 policy 的结构、查找方式、决策逻辑
3. 没有说明 `loaded_context` 中有什么数据、如何使用
4. 没有说明 `slots` 和 `context` 的判分规则
5. 没有说明什么情况下应该 deny vs ask_clarification vs transfer
6. 实际上被 Python 端完全覆盖（CR 发现 LLM 的 deny 会被强制改为 allow）

**Claude Code 式优化方向**：
```markdown
## Identity
你是零售客服助手的策略审查器。你的决策直接影响订单操作的合法性和安全性。
你必须严格依据输入的 policy（策略文档）、loaded_context（加载的订单/用户上下文）
和 slots（提取的槽位）来判断，**不要**基于常识猜测策略内容。

## Decision Protocol

### allow
适用条件：
- 意图为 lookup：仅查询信息，不修改任何数据
- 意图为 transfer：用户要求转人工
- 意图为 cancel/return/exchange/modify_address 且：
  ✓ 用户已完成身份认证
  ✓ 所有必需槽位已提取（见下方 Required Slots）
  ✓ loaded_context 中的订单状态与意图兼容（订单状态由代码侧校验，此处做初步判断）
  **重要**：allow 并不意味着可以直接执行写入，写入操作仍需用户显式确认

### deny
适用条件（拒绝时必须给出具体 explanation_for_user）：
- 用户未认证且意图涉及任何操作
- 意图为 cancel/return/exchange/modify_address 但缺少必需槽位
- loaded_context 显示订单不属于当前认证用户
- 策略文档明确禁止该操作
- 请求的支付方式不存在或不属于该用户

### ask_clarification
适用条件（返回时必须在 missing_slots 中列出缺失项）：
- 意图可识别但关键槽位缺失（如 cancel 但缺 order_id）
- 用户请求模糊，无法确定具体意图
- 多个可能的操作，需要用户确认具体选择

### transfer
适用条件：
- 意图明确为 transfer
- 当前场景超出助手能力范围
- **不要**因为 deny 而自动升级为 transfer

## Required Slots by Intent
- cancel_order: order_id, reason
- modify_order_address: order_id, address (含 address1, city, state, country, zip)
- return_items: order_id, item_ids, payment_method_id
- exchange_items: order_id, item_ids, new_item_ids, payment_method_id
- lookup: 无强制要求（至少需要 order_id 或 email）
- transfer: 无强制要求

## Context Usage
loaded_context.orders: { order_id: { status, user_id, items, ... } }
- 检查 order.user_id == authenticated_user_id（所有权检查）
- 检查 order.status 与意图兼容性：
  - cancel → status 应为 pending
  - return → status 应为 delivered  
  - exchange → status 应为 delivered
  - modify_address → status 应为 pending 或包含 "pending"

loaded_context.users: { user_id: { email, address, ... } }

## Examples

### Example 1: 正常取消
Input: intent=cancel_order, order_id=#W5918442, order.status=pending, user 已认证且是订单所有者
→ decision: allow, user_confirmation_required: true

### Example 2: 订单不属于当前用户
Input: intent=cancel_order, order_id=#W5918442, order.user_id != authenticated_user_id
→ decision: deny, explanation: "I cannot access or modify orders for another account."

### Example 3: 缺少必需字段
Input: intent=return_items, 缺少 payment_method_id
→ decision: ask_clarification, missing_slots: ["payment_method_id"]

## Output Format
返回纯 JSON，不要包含 markdown 标记或解释文本。
```

---

### 2.3 `action_planner_v001.md` — 当前 21 行

**问题**：
1. 没有说明与 policy_decision 的协作方式
2. 没有说明各 plan_type 的输入要求
3. 没有示例展示标准输出格式
4. 没有说明 confirmation 文案的生成规范

**优化方向**：添加示例、说明各 plan type 的参数要求、confirmation 文案模板。

---

### 2.4 `response_generator_v001.md` — 当前 7 行

**问题**：
1. 没有定义客服语气的具体标准
2. 没有给出格式约束（是否可以用 emoji、HTML、markdown）
3. 没有说明敏感信息处理（不要泄露完整的 email/地址）
4. 没有错误场景的回复模板

**优化方向**：定义 tone、格式约束、错误回复模板。

---

## 三、架构层面的优化建议

### 3.1 引入 Prompt 分层

借鉴 Claude Code 的「稳定前缀 + 可变上下文」模式：

```
┌─────────────────────────────────────┐
│  Layer 0: 核心契约 (Cache-stable)    │  ← 永远不变，享受 prompt-cache
│  - 身份 & 角色                       │
│  - 行为准则 (do / don't)            │
│  - 输出格式规范                      │
├─────────────────────────────────────┤
│  Layer 1: 节点能力 (Versioned)       │  ← 按版本迭代
│  - 支持的意图/决策/计划类型          │
│  - Few-shot examples               │
│  - 特定节点的约束                    │
├─────────────────────────────────────┤
│  Layer 2: 请求载荷 (Dynamic)         │  ← 每次不同
│  - user_message / policy_excerpt    │
│  - slots / loaded_context           │
│  - fallback_decision                │
└─────────────────────────────────────┘
```

### 3.2 实施方式

当前 `prompts.py` 已支持版本化，只需在现有基础上：

```python
# 新增：共享的 agent 核心契约
AGENT_CORE_CONTRACT = Path("prompts/core_contract_v001.md").read_text()

# 各节点 prompt 改为 Layer 0 + Layer 1 拼接
INTENT_SLOT_SYSTEM = AGENT_CORE_CONTRACT + "\n\n" + INTENT_SLOT_PROMPT.content
POLICY_SYSTEM = AGENT_CORE_CONTRACT + "\n\n" + POLICY_PROMPT.content
# ...
```

其中 `core_contract_v001.md` 定义：
- 你是谁（零售客服助手）
- 你的能力边界（只能操作零售订单）
- 安全准则（不泄露用户数据、不执行未确认的写入）
- 输出格式（纯 JSON / 纯文本）
- 错误处理（失败时返回空 JSON 而非猜测）

### 3.3 利用 prompt-cache

DeepSeek 支持 prompt caching。如果 `core_contract_v001.md` 内容固定且放置在前面，4 个 LLM 调用共享同一段缓存前缀，显著降低 token 成本：

```
当前：4 × (各自的 system prompt + user payload) = 无共享缓存
优化后：core_contract (缓存命中) + node_specific + user_payload
       四个调用中 core_contract 只需付费一次
```

### 3.4 工具描述对 LLM 可见

当前 `retail_adapter.py` 中的工具实现 LLM 完全不可见。可以借鉴 Claude Code 的 tool schema：

```python
# 在 tool registry 中同时注册工具的 LLM 可见描述
TOOL_DESCRIPTIONS = {
    "cancel_pending_order": """
cancel_pending_order(order_id, reason)
- 取消一个 pending 状态的订单
- order_id: 订单编号 (如 #W5918442)
- reason: "no longer needed" 或 "ordered by mistake"
- 不可用于已处理/已发货/已完成的订单
- 需要用户显式确认
""",
    # ...
}
```

将其注入到 action_planner 的 system prompt 中，让 LLM 理解哪些工具可用以及其约束。

### 3.5 Chain-of-Thought 结构化推理

在 policy_reasoner 和 action_planner 中加入 CoT 引导：

```markdown
## Reasoning Protocol
在输出 decision 之前，按以下步骤推理（不要输出到 JSON 中）：

1. 检查认证状态：用户是否已认证？
2. 检查意图合法性：当前意图是否需要特殊权限？
3. 检查槽位完整性：所有必需字段是否已提供？
4. 检查上下文兼容性：订单状态是否支持该操作？
5. 输出 decision

将推理摘要写入 internal_reasoning_summary 字段。
```

---

## 四、优化优先级

| 优先级 | 改动项 | 影响 | 风险 |
|--------|--------|------|------|
| 🔴 P0 | 重写 `policy_reasoner` prompt (当前仅6行) | 安全核心节点，影响所有写入操作 | 低（当前 LLM 决策被代码覆盖） |
| 🔴 P0 | 添加 `core_contract` 为核心契约 | 统一行为标准，启用 prompt cache | 低（新增文件） |
| 🟡 P1 | `intent_slot` 添加 few-shot 示例 | 提升 intent 准确率，减少对 `_infer_intent` 的依赖 | 中（示例需要与实际数据对齐） |
| 🟡 P1 | `action_planner` 注入工具描述 | LLM 理解工具约束，减少幻觉 | 中（工具描述需同步维护） |
| 🟢 P2 | 添加推理链引导 (CoT) | 提升决策可解释性 | 低 |
| 🟢 P2 | `response_generator` 定义语气标准 | 提升用户体验一致性 | 低 |

---

## 五、实施建议

1. **先创建 `prompts/core_contract_v001.md`**，提取所有 prompt 共有的规则
2. **修改 `prompts.py`**，将 core_contract 拼接到每个 system prompt 前面
3. **逐个重写 4 个节点 prompt**，按上述模板补充示例和约束
4. **在 eval 中回归**：已有 11 个 curated_mvp 用例可验证 prompt 改动不破坏现有功能
5. **监控 prompt-cache 命中率**：DeepSeek API 返回 `prompt_cache_hit_tokens`，可观测缓存效果
