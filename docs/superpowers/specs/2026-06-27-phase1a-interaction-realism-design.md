# Phase 1a：交互真实化核心——震撼三件套

> 2026-06-27 · brainstorming 产出 · 目标：高质感 demo

## 背景与动机

项目当前偏测评态：`app/` 下 62 个 Python 文件中 34% 是 eval/synthetic/flywheel 相关；4 个 CLI 入口里 3 个是测评工具，唯一的"真实使用"入口 `phase1-chat --interactive` 只是裸 REPL。eval case 的典型形态是用户第一句话主动报完整邮箱、订单号带 `#W` 前缀明给、确认就是光秃秃的 "yes"——真实用户从不这样说话。

终极目标是做**高质感 demo**（不是真上线）。三个真实化轴（交互真实化 / 生产可部署化 / 评测真实化）分阶段推进，排期方案 A：先大脑后身体。本轮 spec 覆盖 Phase 1a = **震撼三件套**，在现有 harness/workbench 上迭代，不碰 UI。

### 客服生命周期框架（指导思想，渐进落地）

来自真实客服从业经验：客户进坐席 → ① screen pop 客户+订单 → ② 明确诉求 → ③ 诉求→工作流（框架同、细节异）→ ④ 建工单 + 提交评价。本轮用此 4 步模型**指导设计**，但**渐进落地**——不重写编排器，additive 加入 OPENING（screen pop）与 WORKING（intent→SkillSpec 工作流）阶段；CLOSING（工单+评价）放 Phase 1b。架构路径选渐进而非大动编排器重写：保护 100% 基线，用大架构思想指导、用增量方式落地。

## 目标

让 agent 在真实多轮对话里表现得像真人客服，用三件套打破"脚本化单次对话"的测评感：

1. **Screen pop：身份进线即有 + 订单进线预查**——客户进线即带入身份（渠道认证），agent 主动查一次订单（模拟客服进线先扫一眼），第一轮就"认识"客户与其订单（而非撞 Guard block 才反应、或让用户自报邮箱）
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

三件套的改动分布在已有层 + 一个新 helper，不新增子系统。生命周期 4 步模型（screen pop → 意图 → 工作流 → 工单）渐进落地：本轮实现 ①screen pop（OPENING）+ ②指代 + ③打断（WORKING 内），CLOSING 放 Phase 1b。

```
[会话建立]  ← OPENING 阶段
   ScreenPop.apply(customer_id)      ← 新 helper
      步骤1: 设置 session.authenticated_user_id = customer_id   (身份进线即有)
      步骤2: get_user_details → loaded_context.users             (客户卡)
      步骤3: list_user_orders → loaded_context.orders            (进线预查一次订单,
             ← 模仿客服进线后习惯性先扫一眼订单, 是显式查单动作, 不是自动 pop)
              │
              ▼
user msg → AgentRuntime.handle_user_message
              │
    ┌─────────┴──────────────────┐
    ▼                            ▼
 ③preflight                  ② LLM AgentLoop
 (confirmation)                │
    │                          ▼
 关键词fast-path            ToolGateway
 clean? → 短路            ──→ WriteActionGuard (7层，不改)
 mixed? → 放行LLM              │
    │                          ▼
    ▼                     RetailAdapter
  LLM fallback            + list_user_orders (可重复调用: 用户后续补查)
  (pending保持)                │
    │                          ▼
    └────→ context_builder (丰富: 客户卡恒可见 + 订单商品名 + pending详情)
                    │
                    ▼
              system prompt (扩展: 指代消解启发式 + 打断处理)
```

### 改动清单

| 文件 | 改动 | 风险 |
|------|------|------|
| `app/agent/screen_pop.py`（新） | `ScreenPop` helper：身份进线即设 + 主动调 `list_user_orders` 预查一次订单 + `get_user_details` 客户卡 | 低 |
| `app/agent/runtime.py` | `run_script` 支持 screen pop 预载（realistic 子集）；`_preflight_confirmation` 加 fallback 放行逻辑（§3） | 中（核心路径） |
| `app/workbench/session.py` + `app/cli/chat.py` | 会话创建时调用 ScreenPop（demo 模式预载客户卡） | 低 |
| `app/agent/context_builder.py` | 订单含商品名；pending 含参数详情（screen pop 后身份恒可见，无需 NOT AUTHENTICATED 分支） | 低 |
| `app/agent/confirmation.py` | 新增 `has_competing_signal()` + `_has_question()` | 低 |
| `app/tools/retail_adapter.py` + `app/tools/registry.py` | 新增 `list_user_orders` read tool（screen pop 复用 + 用户后续查询） | 低 |
| `prompts/llm_agent_system_v001.md` | 指代消解启发式 + 打断处理段（身份核验引导移除——screen pop 已认证） | 低 |
| `app/eval/cases.py` | 新增 `realistic_conversation` 子集 + `expected_behaviors` 字段 + `screen_pop_user_id` 字段 | 低 |
| `app/eval/runner.py` | screen pop 预载（按 `screen_pop_user_id`）+ 行为 rubric 断言 | 低 |

### 保护的不变量

- Guard 7 层裁决逻辑不动
- `confirmed=True` 仍只在关键词 fast-path 明确确认时传入——LLM fallback 不绕过确认层
- LLM 绝不拒绝写操作——先调 write tool 让 Guard 决定
- 关键词确认器不退役——干净确认仍秒级短路

---

## §1 Screen pop：身份进线即有 + 订单进线预查

### 问题与心智模型校正（两轮）

**第一轮校正**：原设计"对话式身份核验"（agent 问"请报邮箱"）是电话客服里客户未登录、需自报家门的场景。真实坐席相反：客户进坐席那一刻，客服屏幕已 pop 出客户**身份**——身份是渠道带进来的（电商即"客户已登录网站，点客服按钮"，坐席立刻看到账户），不是聊出来的。

**第二轮校正（精确化）**：身份进线即有，但**订单等信息不是自动 pop 出来的**——客服需要**主动查一下**才拉出订单列表。对应到 agent：会话建立只设身份，订单是进线后**主动调 `list_user_orders` 查一次**的显式动作（模仿客服进线后习惯性先扫一眼订单）。`list_user_orders` 既是这个预查步骤，也是后续可重复调用的工具。

正确模型：**身份 = 进线即有（渠道带入）；订单 = 进线后主动查一次（显式 tool 调用）**。step-up 敏感写验证是例外，本轮不做（放 Phase 1b）。

### 设计

**a) 新增 `app/agent/screen_pop.py` — ScreenPop helper**

```python
class ScreenPop:
    """会话建立时模拟真实坐席进线：身份即设 + 主动查一次订单。"""
    def __init__(self, gateway: ToolGateway): ...
    def apply(self, session: SessionState, customer_id: str) -> None:
        # 步骤1（身份进线即有）: 设置 authenticated_user_id + auth_method="screen_pop"
        # 步骤2（客户卡）: get_user_details → loaded_context.users[customer_id]
        # 步骤3（进线预查订单——显式 tool 调用，非自动 pop）:
        #        list_user_orders → loaded_context.orders (近期订单)
        # 步骤4: session.add_step("screen_pop", user_id=..., order_count=...)
```

- 输入：`customer_id`（模拟渠道已认证的登录用户）
- **身份是会话建立时直接设置的**（渠道带入，无需 tool）——Guard auth 层直接放行
- **订单是主动调 `list_user_orders` 查出来的**——这是工作流里的显式查单动作，不是预载副作用
- `list_user_orders` 既是 ScreenPop 步骤3 复用，也是后续 LLM 可重复调用的工具（用户问"我还有别的单"可再查）

**b) 注入点：会话创建**

- `app/workbench/session.py` `_create_runtime_and_state_for`：demo 模式（无 case 或 realistic case 带 `screen_pop_user_id`）创建 state 后调用 `ScreenPop.apply`
- `app/cli/chat.py` `_interactive`：新增 `--customer <user_id>` 参数，会话建立时 screen pop；未传则保持现有空状态（兼容）
- `app/agent/runtime.py` `run_script`：realistic 子集按 case 的 `screen_pop_user_id` 预载

**c) `context_builder.py` — 客户卡恒可见**

screen pop 后 `authenticated_user_id` 恒存在，现有 `User: user_id=xxx (screen_pop)` 行自然显示。订单行含商品名（见 §2b）。无需 NOT AUTHENTICATED 分支——demo 默认已认证。

**d) `_preflight_identity` — 保留正则 fast-path 作为兜底**

screen pop 是主路径；正则抽取保留为兜底（用户在会话中后续报邮箱查别的账户等边缘场景）。Guard auth 层仍是最终裁决——screen pop 设置的 `authenticated_user_id` 与 Guard 检查的是同一字段，不变量不破。

### 交互流（demo 效果）

```
[会话建立]
  → 身份即设: authenticated_user_id = sofia_rossi_8776 (渠道带入)
  → 主动查单: list_user_orders → #W5918442=pending, #W4817420=delivered (预查一次)
User: 帮我取消那个没发货的订单
  → agent 已预查到订单，从上下文解析"没发货的" = #W5918442
  → LLM: 好的 Sofia，您有一个 pending 的 #W5918442（Water Bottle、T-Shirt），
         要取消这个吗？原因是什么？
```

对比现状：用户不报 `#W` 订单号且不报邮箱，agent 完全无法定位、且会先撞 `authentication_required`。

### 不做的事

- 不做真实 auth 后端（screen pop 模拟渠道认证，demo 足够）
- 不做 step-up 敏感写验证（放 Phase 1b）
- 不改 Guard auth 层（screen pop 只填 `authenticated_user_id`，裁决逻辑不动）

---

## §2 鲁棒指代消解

### 缺口

当前 read tools 无 `list_user_orders`——agent 无法发现用户订单列表。state summary 只显示 `#W5918442=pending (3 items)`，无商品名，无法做属性指代。screen pop（§1）预载了近期订单，但用户后续问"我还有一个单呢"等仍需 `list_user_orders` 补载。

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
- **双重用途**：① ScreenPop（§1）复用它预载近期订单；② 用户后续查询/补载时 LLM 主动调用
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

elif resolution == "confirmed":  # confirmed + competing（NEW）
    return None                  # NEW: 放行 LLM, pending 保持

elif resolution == "denied":
    # 干净否认 → 丢弃 pending（现有路径不变）
    session.pending_action = None
    if has_competing_signal(content):
        return None              # NEW: denied+提问 → 丢弃后放行 LLM 答问题
    return "No changes were made."

elif resolution == "changed":
    # changed 独立分支,逐字节不动（保护 generalized_mvp 2 个 changed case 不回归）
    session.pending_action = None
    return "I discarded the previous request. Please provide updated details."

else:  # unknown
    return None                  # 现有路径不变
```

**关键：`changed` 路径逐字节不动。** generalized_mvp 有 2 个 `changed` case（`'No, use item 1234567890 instead.'`），期望 pending 被丢弃 + `confirmation_status='changed'`。原路由把 changed 折进 `else` 会丢不掉 pending → 回归。修正后 changed 单列分支，路由层面 25 条确认消息逐分支核验全部 identical，回归由构造消除。

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
| `ScreenPop.apply` | 预载 user_details + 订单到 loaded_context；设置 authenticated_user_id + auth_method=screen_pop |
| `context_builder` | 订单含商品名；pending 含参数；screen pop 后客户卡恒可见 |

### 第 2 层：新 eval 子集 `realistic_conversation`（live）

多轮 case 验收三件套。screen pop 预载后用户**不再自报邮箱**。示例：

```python
EvalCase(
    case_id="rc_screen_pop_cancel",
    category="realistic_cancel",
    screen_pop_user_id="sofia_rossi_8776",   # 会话建立时预载
    messages=[
        {"role": "user", "content": "帮我取消那个没发货的订单"},   # 无身份、无订单号
        {"role": "user", "content": "对，不想要了"},               # 模糊确认意图
        {"role": "user", "content": "确认"},                       # 干净确认
    ],
    expected_user_id="sofia_rossi_8776",
    expected_intent="cancel_order",
    order_id="#W5918442",
    expected_order_status="cancelled",
    expected_confirmation_status="confirmed",
    required_tools={"cancel_pending_order"},
    expected_behaviors={"screen_pop_preloaded", "reference_resolved"},
)
```

case 覆盖矩阵（~12-15 case）：

| 维度 | case |
|------|------|
| ①screen pop | screen pop 预载后直接提诉求（无需报邮箱）/ 预载后多订单场景 / screen pop 兜底正则（边缘场景） |
| ②指代 | 状态指代("没到的") / 属性指代("蓝衬衫") / 多订单消歧 / list_user_orders 补载 |
| ③打断 | 确认+改细节 / 确认+穿插提问 / 否认+提问 / 穿插新意图 / 模糊回应 |

### 第 3 层：行为 rubric 断言

`EvalCase` 新增 `expected_behaviors: set[str]` + `screen_pop_user_id`，eval runner 验证：

| rubric key | 判定逻辑 |
|------------|----------|
| `screen_pop_preloaded` | 会话首条消息前 `authenticated_user_id` 已设置 + `loaded_context` 含该 user 的 user_details + 订单（trace 出现 `screen_pop` step） |
| `reference_resolved` | write tool 的 order_id 来自 screen pop 预载 / list_user_orders / loaded context，非用户原话明给 |
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

- **Skill 文档化（独立小改，B 路径）**：现有 8 个 `SkillSpec` 从 `app/skills/registry.py` Python 代码迁移到 `skills/*.md` 文档（frontmatter 结构化字段 + 正文 guidance/example）。`loader.py` 启动时读文档解析成 SkillSpec，注入逻辑不变 → 行为字节级等价。价值：维护门槛从"改 Python + 测试 + 发版"降到"改 Markdown"，契合 demo"可维护客服系统"故事；运营/业务人员可直接调整话术。**独立于三件套，单独 spec + 单独验证基线，避免改动叠加难定位回归。** 演进方向 A 路径（意图识别后动态按需加载单 skill）留待 skill 涨到 15+ 时再上。
- **Phase 1b**：多意图编排 / 跑题情绪降级 / 脏输入鲁棒性 / **CLOSING 工单+评价闭环** / **step-up 敏感写验证**
- **Phase 2**：真实聊天界面（chat-first UI + 流式 + 会话持久感 + 订单上下文侧栏 + 生命周期可视化如工单状态条）
- **Phase 3**：真实场景库 + 行为 rubric 评测体系重建
- **演进方向（Phase 2+ 视价值落地）**：SessionOrchestrator 显式编排 4 阶段生命周期（OPENING/WORKING/CLOSING/CLOSED），AgentLoop 退为 WORKING 引擎——待真实 UI 需要生命周期可视化时兑现
