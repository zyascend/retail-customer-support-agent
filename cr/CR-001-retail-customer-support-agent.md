# Code Review: retail-customer-support-agent

> **Review Date**: 2025-06-11  
> **Reviewer**: kun  
> **Scope**: 全部源码 (app/, tests/, prompts/, pyproject.toml)  
> **总代码行数**: ~4,383 行 (不含 artifacts)

---

## 一、项目概况

一个基于 LangGraph 的零售客户支持 Agent，实现交易类操作（查单、取消、改地址、退货、换货、转人工）的受控执行。架构分为 12 个线性阶段的 pipeline，通过 WriteActionGuard 实现写操作的多层校验（所有权、先读后写、策略合规、资源锁、幂等）。

### 评分维度

| 维度 | 评分 (1-5) | 说明 |
|------|-----------|------|
| 架构设计 | 4 | 线性 pipeline + Guard 模式清晰，职责分离合理 |
| 代码质量 | 3.5 | 整体可读性好，但部分逻辑重复、硬编码 |
| 安全性 | 3.5 | Guard 层设计到位，但缺少输入清洗和限流 |
| 可测试性 | 4 | 11 个 curated cases 覆盖 MVP 场景，provider 可替换 |
| 可维护性 | 3 | 硬编码路径和重复策略逻辑增加维护成本 |
| 健壮性 | 3 | LLM 返回值处理有防御但不够彻底 |

---

## 二、发现问题清单

### 🔴 Critical

#### C1. `_policy_reasoner` 强制覆盖 LLM 的 deny 决策

**文件**: `app/agent/runtime.py` (L~330-340)

```python
if (
    state.current_intent in write_intents
    and llm_decision.get("decision") == "deny"
):
    llm_decision["decision"] = "allow"
    llm_decision["internal_reasoning_summary"] = (
        "Supported write intent deferred to deterministic write guard."
    )
```

**问题**: 对所有受支持的写意图，LLM 返回 `deny` 时被无条件覆盖为 `allow`。这意味着 LLM 基于 policy 文档做出的拒绝判断**完全被忽略**，仅依赖后续的确定性 Guard。如果 LLM 发现 policy 层面的问题（如 policy 更新后的新规则），会被静默绕过。

**建议**: 保留 LLM 的 deny 作为决策依据之一，在 Guard 中增加对 LLM policy_deny 的检查，或者至少记录 LLM 拒绝原因到 audit_log。

---

#### C2. `_conversation_gate` 确认操作绕过 WriteActionGuard

**文件**: `app/agent/runtime.py` (L~140-185)

```python
if resolution == "confirm":
    action = state.pending_action
    record = self.gateway.execute(
        state=state,
        tool_name=action.action_name,
        arguments=action.arguments,
        confirmed=True,
    )
```

**问题**: 确认后的操作直接在 `_conversation_gate` 中执行（通过 gateway.execute），此时 state 的 `write_locks` 和上下文可能已过期。虽然 gateway 内部调用了 guard.check，但 `_write_action_guard` 节点被跳过（它是为 pending_action 设置的阶段记录的占位节点）。

**实际影响**: 目前在 gateway.execute 中 guard 会被正确调用，因为 confirmed=True 会触发完整校验。但 `_write_action_guard` 节点的 step 记录时机不对——它在设置 pending_action 时就记录了，而不是在实际执行时记录。

**建议**: 
1. 将 `_write_action_guard` node 的 step 记录移到 gateway 实际执行时
2. 或者在 conversation_gate 确认后重新进入 graph 的正常流程

---

### 🟡 High

#### H1. 硬编码用户路径

**文件**: `app/config.py` (L10-14)

```python
DEFAULT_TAU3_RETAIL_ROOT = Path(
    "/Users/theyang/Documents/ai/AgentProject/data_sources/"
    "retail_customer_support_transaction_agent/current_tau3_bench"
)
DEFAULT_TAU2_BENCH_ROOT = Path(
    "/Users/theyang/Documents/ai/AgentProject/data_sources/raw/tau2-bench"
)
```

**问题**: 包含用户名 `theyang` 的绝对路径，无法在其他机器上运行。

**建议**: 
- 使用相对于项目根目录的路径，或 `~/.config/...`
- 如必须保留默认值作为文档，至少使用 `os.path.expanduser("~/...")` 并在路径不存在时给出明确提示

---

#### H2. `_infer_intent` 关键词匹配过于宽泛

**文件**: `app/agent/runtime.py` (L~855-875)

```python
def _infer_intent(self, lowered: str) -> str:
    if "human" in lowered or "agent" in lowered or "representative" in lowered:
        return "transfer"
    if "cancel" in lowered:
        return "cancel_order"
    if "return" in lowered:
        return "return_items"
    ...
```

**问题**:
- `"return"` 匹配所有包含 "return" 的文本，如 "I want to return..." 和 "what is your return policy?"
- `"human"` 匹配 "human error" 等无意转人工的消息
- `"exchange"` 匹配 "exchange rate" 等非操作含义
- intent 优先级（transfer > cancel > return > exchange > modify > lookup）意味着用户说 "cancel my transfer" 会被判定为 transfer 而非 cancel

**建议**:
- 使用更精确的正则或 NLP（如 `\bwant( to)? cancel\b`, `\breturn (this|the|my|item|order)\b`）
- 考虑上下文：如果用户在确认阶段说 "cancel" 应该是 deny 而非新的 cancel 意图
- 增加 ambiguity 处理：当匹配多个 intent 时，不要简单取第一个

---

#### H3. `_validate_policy` substring 匹配问题

**文件**: `app/agent/guard.py` (L~125-130)

```python
if action.tool_name == "modify_pending_order_address":
    if not order or "pending" not in order.get("status", ""):
        return "non_pending_order_cannot_be_modified"
```

**问题**: `"pending" not in "pending_shipment"` 返回 `False`（不会触发拒绝），但 `"pending" not in "processing"` 返回 `True`。虽然当前数据中可能只有 `"pending"` 这个状态值，但如果未来引入 `"pending_shipment"`、`"pending_payment"` 等复合状态，这个检查会错误地放行。

**建议**: 改为精确比较：
```python
if not order or order.get("status") != "pending":
    return "non_pending_order_cannot_be_modified"
```

---

#### H4. LLM JSON 解析无防御性重试

**文件**: `app/agent/providers.py` (L47-51)

```python
def json(self, messages, schema):
    response = self.client.chat.completions.create(
        model=self.model,
        messages=messages,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)
```

**问题**: 
1. `json.loads(content)` 在 LLM 返回非标准 JSON（如 markdown 包裹、尾部逗号、注释）时会直接抛异常
2. 没有 retry 机制
3. 没有对 content 做提取 JSON 块的预处理（如去除 markdown code fences）

**建议**:
```python
def json(self, messages, schema):
    for attempt in range(self.max_retries + 1):
        try:
            response = self.client.chat.completions.create(...)
            content = response.choices[0].message.content or "{}"
            content = self._extract_json(content)
            return json.loads(content)
        except (json.JSONDecodeError, KeyError) as exc:
            if attempt == self.max_retries:
                raise
```

---

#### H5. Guard 中对 item_ids 的类型假设不一致

**文件**: `app/agent/guard.py` (L~115-120)

```python
if action.tool_name == "exchange_delivered_order_items":
    if len(args.get("item_ids", [])) != len(args.get("new_item_ids", [])):
        return "exchange_item_count_mismatch"
```

**问题**: Guard 期望 `item_ids` 为 list 类型，但从 LLM 解析来的 arguments 可能仍是字符串。`runtime.py` 中的 `_normalize_llm_action_arguments` 会将单个字符串转为列表，但它只在 LLM action planner 路径中被调用。如果 `_set_pending` 直接构造参数（不经过 LLM），`item_ids` 可能是字符串。

同样的问题存在于 `_resource_lock` 中对 `args.get("item_ids", [])` 调用 `sorted()`。

**建议**: 在 `guard._normalize_args` 中统一处理 `item_ids` 到 list 的转换。

---

### 🟢 Medium

#### M1. `pydantic_compat.py` 的 BaseModel fallback 与 Pydantic 行为差异

**文件**: `app/pydantic_compat.py`

**问题**:
- 不支持类型验证（Pydantic 会自动 coerce 类型）
- `model_dump` 不会递归嵌套的 BaseModel（使用 `hasattr` 检查而非 `isinstance`）
- 不支持 `model_fields`、`model_config`、validator 等 Pydantic 特性
- 如果有代码依赖 Pydantic 行为（如 `BaseModel.model_validate({"key": 123})` 自动转类型），在 fallback 下会静默表现不同

**建议**: 
- 考虑是否真的需要这个 fallback。如果 Pydantic 是硬依赖（已在 pyproject.toml 中声明 `pydantic>=2.10.0`），移除 fallback 更清晰
- 如必须保留，至少增加 `__repr__` 和 `__eq__` 支持

---

#### M2. 重复的策略校验逻辑

**文件**: `app/agent/guard.py` 与 `app/tools/retail_adapter.py`

这两个文件中存在重复的策略检查：
- `cancel_pending_order` 的 "pending" 状态检查在两处都有
- `return_delivered_order_items` 的 "delivered" 状态检查在两处都有
- `exchange_delivered_order_items` 的 "delivered" 状态检查在两处都有

**问题**: 维护成本双倍，修改策略时需要同步两处。

**建议**: 
- Guard 层保留为 pre-check（决策是否允许执行）
- RetailAdapter 层保留为 post-check（实际 DB 操作层面的最后防线）
- 抽取共享的策略常量/函数

---

#### M3. ConfirmationResolver 的精确匹配限制

**文件**: `app/agent/confirmation.py` (L43-45)

```python
def resolve(self, text: str) -> ConfirmationIntent:
    normalized = " ".join(text.lower().strip().split())
    if normalized in CONFIRM_TERMS:
        return "confirm"
```

**问题**: 
- `"yes please"` → `unknown`（不匹配 "yes" 因为不在集合中）
- `"ok go ahead"` → `unknown`
- 中文 "好的，请继续" → `unknown`
- 用户说 "yes I confirm" → `unknown`

**建议**: 
```python
def resolve(self, text: str) -> ConfirmationIntent:
    normalized = " ".join(text.lower().strip().split())
    for term in CONFIRM_TERMS:
        if normalized.startswith(term) or term in normalized.split():
            return "confirm"
    # 同理处理 deny
```

---

#### M4. 异常信息可能泄露内部状态

**文件**: `app/agent/runtime.py` (L~180)

```python
self._assistant(
    state,
    f"I could not complete that update: {record.error}.",
)
```

**问题**: `record.error` 可能包含内部错误信息（如 DB 路径、stack trace），直接返回给用户存在信息泄露风险。

**建议**: 对 error message 做白名单过滤：只有预定义的 user-facing errors 才展示详细信息，其余用通用错误消息。

---

#### M5. 缺少 `_create_local_runtime` 的实现

**文件**: `app/tools/retail_adapter.py` (L~65)

```python
try:
    return self._create_tau2_runtime(policy)
except Exception:
    return self._create_local_runtime(policy)
```

**问题**: 
1. `_create_local_runtime` 的实现从文件被截断了——`_create_tau2_runtime` 看起来也不完整（中间有孤立的 `raise ValueError(...)` 语句）
2. `except Exception` 过于宽泛，可能吞掉关键的初始化错误
3. fallback 行为未记录日志

**建议**: 
- 至少 `logging.warning` 记录 fallback 原因
- `except Exception` 改为更具体的异常类型
- 确保 `_create_local_runtime` 实现完整

---

#### M6. `_apply_llm_action_plan` 中 arguments 的静默清理可能掩盖问题

**文件**: `app/agent/runtime.py` (L~800)

```python
for key, value in list(normalized.items()):
    if isinstance(value, str):
        cleaned = self._clean_llm_scalar(value)
        if cleaned is None:
            normalized.pop(key)
        else:
            normalized[key] = cleaned
```

**问题**: 如果 LLM 返回了重要参数但值为 "null"/"none"/空字符串，该参数被静默删除，可能导致后续 missing_args 检查无法准确定位问题。

**建议**: 至少记录被删除的参数到 steps 中。

---

#### M7. `ToolRegistry._tool_kind` 的 fallback 默认 write

**文件**: `app/tools/registry.py` (L43-50)

```python
def _tool_kind(self, toolkit: Any, name: str) -> ToolKind:
    ...
    if name.startswith(("get_", "find_", "list_")):
        return "read"
    if name == "transfer_to_human_agents" or name == "calculate":
        return "generic"
    return "write"
```

**问题**: 任何不符合规则的 tool 默认为 "write"，这意味着所有 write guard 检查会应用到它。如果新增了一个不遵循命名规范的 read tool（如 `check_inventory`），它会被错误分类为 write。

**建议**: 默认为 "generic"，需要显式声明才设为 "write"，或通过 `tool_type` 属性/装饰器显式声明。

---

#### M8. `.env` 文件被提交到 Git 的风险

**文件**: `.env` 存在于项目目录中（非 example）

**问题**: `.env` 是实际使用的文件（非 `.env.example`）。虽然 `.gitignore` 包含了 `.env` 和 `.env.*`（`!.env.example`），但需要确认 `.env` 确实未被提交。

**建议**: 运行 `git status` 确认 `.env` 状态；如已提交，需要从 Git 历史中移除。

---

### 🔵 Low / Nice to have

#### L1. `__init__.py` 为空文件
- `app/agent/__init__.py`、`app/cli/__init__.py`、`app/tools/__init__.py`、`app/ops/__init__.py`、`app/eval/__init__.py` 均为空
- 建议：添加 docstring 或移除不需要的文件

#### L2. `AppConfig` frozen dataclass 中有可变默认值风险
- config.py 中 `AgentRuntime.__init__` 传入的可变对象（RetailAdapter 返回值）没问题，但 frozen 语义可能产生误解

#### L3. `_assistant` 方法在 LLM 返回为空时静默使用 draft content
- 这是一个合理的设计选择，但建议记录到 run_metrics 中标记 "llm_polish_skipped"

#### L4. `run_script` 跳过非 user role 的消息
- `if message.get("role") != "user": continue`，但未记录跳过的消息
- 建议添加 warning 日志

#### L5. `_parse_address` 使用逗号分割，不支持引号包裹的地址
- `"123 Main St, Apt 4B"` 会被正确分割为 6 部分
- 但如果地址包含逗号如 `"123 Main St, Suite 100, Boston"` 可能被解析为 6 部分

#### L6. tests 依赖实际数据文件
- 测试中使用了 `PENDING_ORDER = "#W5918442"` 等硬编码订单号，依赖实际数据库
- 建议：测试中使用 mock/fixture 构造数据库

#### L7. ruff 配置中未启用更多规则
- `ruff.lint.select = ["E4", "E7", "E9", "F", "I"]` 启用了较少规则
- 建议逐步启用更多规则如 `N`(pep8-naming), `SIM`(flake8-simplify), `B`(flake8-bugbear)

---

## 三、设计亮点 ✅

1. **WriteActionGuard 多层校验设计**: 所有权验证 → 先读后写 → 策略合规 → 资源锁 → 幂等 key，层次清晰
2. **PendingAction 确认机制**: 写操作必须经过 pending → confirm 流程，用户可见的摘要提示
3. **确定性执行路径**: 无 LLM 时仍可通过关键词匹配 + 确定性 fallback 完成核心流程
4. **LLMProvider 可替换**: 通过 Protocol 定义接口，支持 DeepSeek、Deterministic、Disabled 多种模式
5. **11 个 curated eval cases**: 覆盖正常流程、确认拒绝、确认变更、Guard 拦截、跨用户访问等场景
6. **审计日志**: write 操作记录 before/after DB hash、idempotency_key、resource_lock
7. **Stable hashing**: 用于幂等 key 生成，避免相同操作重复执行
8. **线性 graph 设计**: 12 个命名明确的节点，可独立测试和替换

---

## 四、测试覆盖分析

### 当前测试覆盖

| 测试文件 | 覆盖范围 | 评估 |
|---------|---------|------|
| `test_agent_core.py` | Guard、Gateway、Trace、Runtime smoke test、Confirmation | 良好 |
| `test_eval_runner.py` | Curated cases 分类、failure 分类、summary 输出 | 良好 |
| `test_phase0_checks.py` | 环境检查 | 基础 |
| `test_phase0_results.py` | 结果解析 | 基础 |

### 建议补充的测试

- [ ] LLM action plan 参数归一化边界测试（空值、null、类型错误）
- [ ] 多次 pending_action 的 conversation_gate 行为（用户连续确认两次）
- [ ] 并发写锁的冲突场景
- [ ] `_parse_address` 对各种地址格式的边界测试
- [ ] `_infer_intent` 对各种歧义输入的行为
- [ ] `_load_dotenv` 对各种格式 .env 文件的解析
- [ ] `pydantic_compat` fallback 的行为差异验证

---

## 五、改进优先级建议

| 优先级 | 条目 | 工作量 |
|--------|------|--------|
| P0 | C1: 恢复 LLM deny 决策权重 | 小 |
| P0 | H1: 移除硬编码路径 | 小 |
| P1 | H2: 改进 intent 关键词匹配 | 中 |
| P1 | H3: 修复 order status substring 匹配 | 小 |
| P1 | H4: LLM JSON 解析增加防御性处理 | 小 |
| P1 | H5: Guard 中统一 argument 类型 | 小 |
| P2 | M2: 抽取共享策略校验逻辑 | 中 |
| P2 | M3: 改进 ConfirmationResolver 匹配 | 小 |
| P2 | M5: 完善 RetailAdapter 异常处理 | 中 |
| P3 | M1: 评估是否需要 pydantic_compat | 小 |
| P3 | M4/M6/M7/M8: 其他 Medium 问题 | 小 |
| P3 | L 类改进 | 按需 |

---

## 六、总结

项目整体架构设计合理，Guard + Pending Action + Confirmation 的三层安全机制是亮点。11 个 curated eval cases 覆盖了 MVP 核心场景。主要问题集中在：

1. **LLM 决策被覆盖**（C1）—— 加入 LLM 的意义被削弱
2. **硬编码路径**（H1）—— 即时的可移植性问题  
3. **意图识别粗糙**（H2）—— 对生产环境可能有较多误判
4. **边界情况处理不够细致**—— 多个 Medium 级别问题涉及参数类型、字符串匹配、异常处理等

建议在进入下一阶段开发前，优先处理 P0/P1 问题。
