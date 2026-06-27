# Phase 1a：交互真实化核心——震撼三件套

> 2026-06-27 · brainstorming 产出 · 目标：高质感 demo

## 背景与动机

项目当前偏测评态：`app/` 下 62 个 Python 文件中 34% 是 eval/synthetic/flywheel 相关；4 个 CLI 入口里 3 个是测评工具，唯一的"真实使用"入口 `phase1-chat --interactive` 只是裸 REPL。eval case 的典型形态是用户第一句话主动报完整邮箱、订单号带 `#W` 前缀明给、确认就是光秃秃的 "yes"——真实用户从不这样说话。

终极目标是做**高质感 demo**（不是真上线）。三个真实化轴（交互真实化 / 生产可部署化 / 评测真实化）分阶段推进，排期方案 A：先大脑后身体。本轮 spec 覆盖 Phase 1a = **震撼三件套**，在现有 harness/workbench 上迭代，不碰 UI。

## 目标

让 agent 在真实多轮对话里表现得像真人客服，用三件套打破"脚本化单次对话"的测评感：

1. **对话式身份核验**——agent 主动索要验证信息，而非撞 Guard block 才反应
2. **鲁棒指代消解**——解析"没到的那个""蓝衬衫"等模糊/照应指代
3. **中途打断 & 意图穿插**——确认中可改细节、穿插提问、加新请求，不丢 pending 不误触发

## 不做（YAGNI）

- 不做真实 auth 后端 / 真 OMS / 真渠道（demo 目标，可信 mock 足够）
- 不做流式 / 聊天 UI（Phase 2）
- 不做全量评测体系重建（Phase 3）
- 不动 7 层 Guard 的裁决逻辑
- 不做 embedding / 语义相似度指代匹配（关键词 + LLM 足够）
- 不追踪"最近引用订单"为结构化字段（先靠 LLM 从对话历史推断）

## 架构总览

三件套的改动分布在三个已有层，不新增子系统：

```
user msg → AgentRuntime.handle_user_message
              │
    ┌─────────┼──────────────────┐
    ▼         ▼                  ▼
 ①preflight  ③preflight       ② LLM AgentLoop
 (identity)  (confirmation)      │
    │         │                  ▼
    │    关键词fast-path      ToolGateway
    │    clean? → 短路       ──→ WriteActionGuard (7层，不改)
    │    mixed? → 放行LLM         │
    │         │                  ▼
    ▼         ▼             RetailAdapter
  regex提取   LLM fallback   + 新工具 list_user_orders
  (不改)    (pending保持)         │
    │         │                  ▼
    └────→ context_builder (丰富: auth状态 + 订单商品名 + pending详情)
                    │
                    ▼
              system prompt (扩展: 身份核验引导 + 指代消解启发式 + 打断处理)
```

### 改动清单

| 文件 | 改动 | 风险 |
|------|------|------|
| `app/agent/context_builder.py` | 显示 auth 状态；订单含商品名；pending 含参数详情 | 低 |
| `app/agent/confirmation.py` | 新增 `has_competing_signal()` + `_has_question()` | 低 |
| `app/agent/runtime.py` | `_preflight_confirmation` 加 fallback 放行逻辑 | 中（核心路径） |
| `app/tools/retail_adapter.py` + `app/tools/registry.py` | 新增 `list_user_orders` read tool | 低 |
| `prompts/llm_agent_system_v001.md` | 身份核验引导 + 指代消解启发式 + 打断处理段 | 低 |
| `app/eval/cases.py` | 新增 `realistic_conversation` 子集 + `expected_behaviors` 字段 | 低 |
| `app/eval/runner.py` | 行为 rubric 断言（`expected_behaviors` 校验） | 低 |

### 保护的不变量

- Guard 7 层裁决逻辑不动
- `confirmed=True` 仍只在关键词 fast-path 明确确认时传入——LLM fallback 不绕过确认层
- LLM 绝不拒绝写操作——先调 write tool 让 Guard 决定
- 关键词确认器不退役——干净确认仍秒级短路

---

## §1 对话式身份核验

### 问题

`_preflight_identity`（`runtime.py:453`）纯正则抽取：用户消息里出现 email 或 name+zip 格式才提取。`context_builder.build` 只在 `authenticated_user_id` 存在时显示 User 行——未认证时 state summary 无身份信号，LLM 不知道该先验证身份。

用户说"帮我取消订单"（不报邮箱）→ LLM 直接尝试写 → Guard block `authentication_required` → 用户收到冷冰冰的 "Please verify your identity before making changes."。没有对话感。

### 设计

**a) `context_builder.py` — 显式 auth 状态**

未认证时 state summary 首行：
```
User: NOT AUTHENTICATED — identity verification required for any order changes
```
已认证时保持现状。LLM 每轮都能看到认证状态。

**b) `prompts/llm_agent_system_v001.md` — 身份核验引导**

Core Contract 新增第 12 条：
> **Verify identity before writes** — if the session is not authenticated and the user requests an order lookup or change, ask for their email address or their name and zip code to verify identity first. Do not attempt a write tool until identity is verified; the guard will block it regardless. Once verified, proceed with the request.

Heuristics 段补充：
> **Identity first** — for write requests from unauthenticated users, your first response should ask for verification, not attempt the write.

**c) `_preflight_identity` — 保留正则 fast-path，不改**

用户在任何消息报了 email/name+zip，正则照旧秒级提取并设置 `authenticated_user_id`。LLM 引导用户报身份 → 用户报了 → fast-path 捕获 → 下一轮 LLM 见已认证 → 继续。

### 交互流

```
User: 帮我取消那个还没发货的订单
  → state: NOT AUTHENTICATED
  → LLM: 没问题，请先告诉我您的注册邮箱，或姓名和邮编。
User: sofia.rossi2645@example.com
  → preflight regex 命中 → authenticated
  → LLM: 谢谢 Sofia。我查到您有一个 pending 订单 #W5918442，要取消吗？
```

---

## §2 鲁棒指代消解

### 缺口

当前 read tools 无 `list_user_orders`——agent 无法发现用户订单列表。state summary 只显示 `#W5918442=pending (3 items)`，无商品名，无法做属性指代。

| 指代类型 | 例子 | 当前 |
|----------|------|------|
| 状态指代 | "没到的那个" | ❌ 无列表工具 |
| 时间指代 | "我上次的单" | △ 仅 prompt 启发式 |
| 属性指代 | "蓝衬衫那件" | ❌ summary 无商品名 |
| 篇章照应 | "我刚问的那个" | ❌ |
| 多订单消歧 | "我有两个 pending" | ❌ |

### 设计

**a) 新增 read tool `list_user_orders(user_id)`**

```
输入: user_id（认证用户）
输出: 该用户所有订单摘要列表
  [{order_id, status, order_date, items: [{name, item_id, price}]}]
```

- `LocalRetailTools`：过滤 `db["orders"]` by `user_id`，返回摘要（不含 payment_history 等重字段，控 token）
- tau2 runtime：RetailDB 的 order 有 `user_id` 字段，用薄 wrapper 在 adapter 层实现（不改 tau2 源码）
- 注册进 `READ_TOOLS`，Guard 不拦截
- **前置约束**：`user_id` 必须等于 `session.authenticated_user_id`——gateway 层校验，防越权枚举

**b) `context_builder.py` — 订单含商品名**

当前：`Orders: #W5918442=pending (3 items)`
改为：`Orders: #W5918442=pending [Water Bottle, T-Shirt, Mug]`

商品名截断前 3 个，超长省略号。让 LLM 从 summary 直接做属性匹配。

**c) `prompts/llm_agent_system_v001.md` — 指代消解启发式**

扩展现有 Heuristics：
> - **Recent order inference** — if the user says recent, latest, or just placed, use `list_user_orders` to find their orders. If exactly one plausible order matches, use it.
> - **Status reference** — "没到的"/"the one that hasn't arrived" → match by status (pending). "退了的"/"returned" → match by return history.
> - **Attribute reference** — "蓝衬衫"/"the blue shirt" → match by item name in loaded orders.
> - **Discourse anaphora** — "刚说的那个"/"that one" → use the most recently referenced order.
> - **Disambiguate when ambiguous** — if multiple orders could match, list them briefly and ask the user which one. Never guess when more than one order fits.

### 交互流

```
User: sofia.rossi2645@example.com — 我那个没发货的能取消吗
  → 认证 → LLM 调 list_user_orders → 2 单: #W5918442=pending, #W4817420=delivered
  → LLM: 只有一个 pending #W5918442（Water Bottle、T-Shirt），要取消吗？
```

---

## §3 中途打断 & 意图穿插

### 核心机制：路由逻辑变更

`runtime.py:_preflight_confirmation` 当前是"pending 期间一律短路关键词器"。改为只有干净信号才短路，否则放行 LLM：

```python
# _preflight_confirmation 新路由（伪码）
resolution = self._resolver.resolve(content)

if resolution == "confirmed" and not has_competing_signal(content):
    # 干净确认 → 秒级短路执行（现有路径不变）
    gateway.execute(..., confirmed=True)

elif resolution == "denied":
    # 干净否认 → 丢弃 pending（现有路径）
    session.pending_action = None
    if has_competing_signal(content):
        return None  # deny + 穿插提问 → 丢弃后放行 LLM 答问题
    return "No changes were made."

else:
    # unknown / changed / confirmed+mixed → 放行 LLM，pending 保持不动
    return None
```

**确认层不绕过**：LLM fallback 路径里 LLM 调 write tool 时 `confirmed` 默认 False → Guard block `explicit_confirmation_required` → 设置新 pending（替换旧）。用户下一条干净 "yes" 走 fast-path 确认。`confirmed=True` 仍只在干净确认 fast-path 传入。

### `confirmation.py` — 竞争信号检测

```python
_QUESTION_RE = re.compile(
    r'[?？]|多少|怎么|为什么|何时|what|how|why|when|where|'
    r'can you|能不能|是不是|有没有|退多少|多少钱'
)

def _has_question(text_lower: str) -> bool:
    return bool(_QUESTION_RE.search(text_lower))

def has_competing_signal(text: str) -> bool:
    """检测混合/竞争信号——需要 LLM 介入消歧的场景。"""
    text_lower = text.lower().strip()
    confirm = _score(text_lower, _CONFIRM_KEYWORDS)
    deny = _score(text_lower, _DENY_KEYWORDS)
    change = _score(text_lower, _CHANGE_KEYWORDS)
    if confirm >= 2 and change >= 2:
        return True
    if confirm >= 2 and deny >= 2:
        return True
    if _has_question(text_lower) and (confirm >= 2 or deny >= 2 or change >= 2):
        return True
    return False
```

新写意图（"另外一个单也取消"）不需在此检测——关键词器返回 `unknown`（无 confirm/deny/change 词），自动走 `else` 放行 LLM。

### LLM fallback 行为（prompt 引导 + context 支撑）

| 场景 | 用户说 | LLM 应做 |
|------|--------|----------|
| 确认+改细节 | "嗯行吧，不过原因改成 no longer needed" | 调 write tool 用新参数 → Guard 设新 pending → "确认用 no longer needed 取消吗？" |
| 确认+穿插提问 | "确认，退款多少？" | 调 write tool（Guard 确认）+ calculate 算退款 → 回答金额 + "确认取消吗？" |
| 否认+提问 | "算了别取消了，退款多少？" | denied 已清 pending → LLM 算退款 → 回答金额 |
| 穿插新意图 | "等等，我另一个单 #W999 也能取消吗" | LLM 处理新请求 → 旧 pending 保持，最后回来问旧确认 |
| 纯模糊 | "嗯" | "您是确认取消吗？请明确回复确认或取消" |

### `context_builder.py` — pending 详情

当前：`Pending: cancel_pending_order — waiting for user confirmation`
改为：`Pending: cancel_pending_order(order_id=#W5918442, reason=no longer needed) — waiting for user confirmation`

### `prompts/llm_agent_system_v001.md` — 打断处理引导

Core Contract 新增第 13 条：
> **Handle interruptions during pending confirmation** — if a write action is pending confirmation and the user's response is mixed (e.g., confirms but also asks a question, or wants to change a detail), address both parts: handle the question or modification, then re-ask for clean confirmation. Do not discard the pending action unless the user clearly denies it.

### 风险与缓解

| 风险 | 缓解 |
|------|------|
| LLM fallback 误判意图 | Guard 确认层兜底——LLM 无法直接执行写，须用户干净确认 |
| fallback 增加延迟 | 仅混合/打断触发，干净确认仍秒级 |
| 旧 pending 被新 pending 替换后用户困惑 | prompt 引导 LLM 明确说明"已更新为 X，确认吗？" |
| `has_competing_signal` 误报 | 保守阈值 `>= 2`，误报只多走一次 LLM，无安全影响 |

---

## §4 测试策略

### 原则

现有基线（curated_mvp 100%、generalized_mvp 100%）不回归。新增能力用新 eval 子集 + 行为 rubric 覆盖。

### 第 1 层：单元测试（确定、快、无 LLM）

| 测试对象 | 覆盖点 |
|----------|--------|
| `confirmation.has_competing_signal` | 混合 confirm+change / confirm+deny / 信号+提问 → True；干净 → False |
| `confirmation._has_question` | 中英文问句命中 |
| `list_user_orders` | 按 user_id 过滤；越权拒绝；空订单 []；含商品名摘要 |
| `context_builder` | 未认证 NOT AUTHENTICATED；订单含商品名；pending 含参数 |

### 第 2 层：新 eval 子集 `realistic_conversation`（live）

多轮 case 验收三件套。示例：

```python
EvalCase(
    case_id="rc_conversational_auth",
    category="realistic_auth",
    messages=[
        {"role": "user", "content": "帮我取消那个没发货的订单"},
        {"role": "user", "content": "sofia.rossi2645@example.com"},
        {"role": "user", "content": "对，不想要了"},
        {"role": "user", "content": "确认"},
    ],
    expected_user_id="sofia_rossi_8776",
    expected_intent="cancel_order",
    order_id="#W5918442",
    expected_order_status="cancelled",
    expected_confirmation_status="confirmed",
    required_tools={"list_user_orders", "cancel_pending_order"},
    expected_behaviors={"identity_before_write", "reference_resolved"},
)
```

case 覆盖矩阵（~12-15 case）：

| 维度 | case |
|------|------|
| ①身份 | 对话式报邮箱 / 报姓名邮编 / 报错再纠正 |
| ②指代 | 状态指代 / 属性指代 / 多订单消歧 / list_user_orders 路径 |
| ③打断 | 确认+改细节 / 确认+穿插提问 / 否认+提问 / 穿插新意图 / 模糊回应 |

### 第 3 层：行为 rubric 断言

`EvalCase` 新增 `expected_behaviors: set[str]`，eval runner 验证：

| rubric key | 判定逻辑 |
|------------|----------|
| `identity_before_write` | 第一个 write tool call 前 `authenticated_user_id` 已设置 |
| `reference_resolved` | write tool 的 order_id 来自 list_user_orders 或 loaded context，非用户原话明给 |
| `interruption_handled` | pending 期间 fallback 后 trace 出现 fallback step，最终 confirmation 正确 |
| `no_stale_pending` | 会话结束时无遗留 pending_action |

### 验收标准

| 项 | 标准 |
|----|------|
| 旧基线 | curated_mvp / generalized_mvp **0 回归** |
| 新子集 | realistic_conversation **≥ 70%**（初始基线） |
| 单元测试 | 新函数 100% 覆盖 |
| 手动 demo | 三件套在 `phase1-chat --interactive` 跑通 |

---

## 后续阶段（本轮不做）

- **Phase 1b**：多意图编排 / 跑题情绪降级 / 脏输入鲁棒性
- **Phase 2**：真实聊天界面（chat-first UI + 流式 + 会话持久感 + 订单上下文侧栏）
- **Phase 3**：真实场景库 + 行为 rubric 评测体系重建
