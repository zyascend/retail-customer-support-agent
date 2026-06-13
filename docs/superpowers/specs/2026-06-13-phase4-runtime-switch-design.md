# Phase 4: Runtime 切换与旧 Runtime 删除 — 设计 Spec

日期：2026-06-13
状态：设计阶段
依赖：Phase 1 ✅、Phase 2 ✅、Phase 3 ✅

## 目标

将 `AgentRuntime.handle_user_message()` 从 12-node deterministic pipeline 切换为 pre-flight → AgentLoop → post-processing 架构。删除旧 pipeline / plan_handlers / graph 模块，精简 parsers/builders。eval runner 和 workbench 继续可用（provider=None 时安全降级）。

## 非目标

- 不修改 eval cases 的字段定义（Phase 5 做）
- 不引入 ScriptedToolCallingProvider 到 eval runner（Phase 5 做）
- 不修改 EvalCaseResult 或 classify_failure 的核心逻辑（Phase 5 做）
- 不删除 ConversationState（Phase 5 做，Phase 4 只补 SessionState 兼容字段）
- 不修改 CLI 入口（`phase1-chat` / `phase2-eval`）

---

## 架构变更

### 旧架构（Phase 1-2）

```
handle_user_message()
  → graph.invoke() 或 sequential 12-node pipeline
    → receive_message → conversation_gate → identity_resolver
    → intent_and_slot_extractor → context_loader → policy_reasoner
    → action_planner → write_action_guard → tool_executor
    → observation_reducer → response_generator → run_logger
```

### 新架构（Phase 4）

```
handle_user_message(session, content)
  │
  ├─ 1. Pre-flight: pending confirmation short-circuit
  │   └─ ConfirmationResolver → confirm/deny/changed
  │      confirm → gateway.execute(confirmed=True) → 回复
  │      deny → 清空 pending → 回复
  │      changed → 清空 pending → 继续到 AgentLoop
  │
  ├─ 2. Pre-flight: identity shortcut
  │   └─ email 或 name+zip 正则 → gateway.execute → 设置 auth
  │
  ├─ 3. Agent loop (provider 不可用时安全降级)
  │   └─ AgentLoop(provider, gateway, registry, context_builder).run_turn(session, content)
  │
  └─ 4. Post-process
      └─ session.messages.append(assistant_message)
```

---

## 文件变更

### 删除（3 个文件，784 行）

| 文件 | 原因 |
|------|------|
| `app/agent/pipeline.py` (445 行) | 12 节点函数，全部被 AgentLoop 替代 |
| `app/agent/plan_handlers.py` (276 行) | 8 个 intent handler，全部被 LLM tool-calling 替代 |
| `app/agent/graph.py` (63 行) | LangGraph 编排，不再需要 |

### 修改

| 文件 | 变更 | 行数变化 |
|------|------|----------|
| `app/agent/runtime.py` | 重写：pre-flight + AgentLoop + post-process；保留 run_script() 多轮循环 | 541 → ~200 |
| `app/agent/models.py` | SessionState 补 4 个兼容字段（Phase 5 移除） | +5 行 |
| `app/agent/providers.py` | DisabledLLMProvider 实现 chat_with_tools() | +10 行 |
| `app/agent/parsers.py` | 精简：只保留 EMAIL_RE、NAME_ZIP_RE、clean_llm_*、ConfirmationResolver 相关 | 276 → ~80 |

### 不改

| 文件 | 原因 |
|------|------|
| `app/agent/llm_agent.py` | Phase 3 成品，直接使用 |
| `app/agent/context_builder.py` | Phase 2 成品，直接使用 |
| `app/agent/guard.py` | Phase 3 已迁移到 SessionState |
| `app/tools/gateway.py` | Phase 3 已迁移到 SessionState |
| `app/eval/runner.py` | Phase 5 适配（Phase 4 通过兼容字段保持可用） |
| `app/eval/cases.py` | Phase 5 适配 |
| `app/workbench/session.py` | Phase 5 适配（Phase 4 通过 DisabledLLMProvider 兼容保持可用） |

---

## 详细设计

### 1. SessionState 兼容字段

```python
class SessionState(BaseModel):
    # ... existing fields unchanged ...
    
    # ── Phase 4 temporary compat (Phase 5 removes these) ──
    current_intent: str = "unknown"
    confirmation_status: str = "not_required"
    policy_decision: Optional[PolicyDecision] = None
    risk_level: str = "low"
```

**理由**：`eval/runner.py` 的 `classify_failure()` 和 `EvalCaseResult` 构造引用了 `state.current_intent`、`state.confirmation_status`、`state.policy_decision`。Phase 4 不修改 eval runner（那是 Phase 5 的工作），所以让 SessionState 携带这些字段作为可空的向后兼容层。Phase 5 从 eval runner 移除引用后删除。

### 2. DisabledLLMProvider 补 chat_with_tools

```python
class DisabledLLMProvider:
    """Sentinel used when no LLM provider is available."""

    def json(self, messages, schema):
        return {}

    def chat(self, messages):
        return ""

    def chat_with_tools(self, messages, tools) -> ToolCallResponse:
        return ToolCallResponse(
            assistant_content=(
                "I'm sorry, the agent is running in offline mode. "
                "Please configure an LLM provider to handle your request."
            ),
            finish_reason="stop",
        )
```

**理由**：eval runner 和 workbench 在无 LLM 时创建 `AgentRuntime(provider=DisabledLLMProvider())`，runtime 将其转为 `self.provider = None`。`handle_user_message()` 检测到 provider=None 时走安全降级路径，直接返回固定文案，不进入 AgentLoop。但如果调用方直接创建 AgentLoop 并传入 DisabledLLMProvider，也能得到安全的文本响应。

### 3. runtime.py 新 handle_user_message

```python
def handle_user_message(self, session: SessionState, content: str) -> str:
    session.messages.append(Message(role="user", content=content))
    
    # ── 1. Pre-flight: pending confirmation ──
    if session.pending_action:
        result = self._preflight_confirmation(session, content)
        if result is not None:
            return result
    
    # ── 2. Pre-flight: identity shortcut ──
    if not session.authenticated_user_id:
        self._preflight_identity(session, content)
    
    # ── 3. LLM agent loop (or safe fallback) ──
    if self.provider is None:
        return self._safe_fallback(session, content)
    
    loop = self._build_agent_loop()
    result = loop.run_turn(session, content)
    
    # ── 4. Post-process ──
    session.messages.append(Message(role="assistant", content=result.assistant_message))
    
    # Phase 4 compat: populate deprecated fields for eval runner
    if result.pending_action_set:
        session.confirmation_status = "required"
    elif not session.pending_action:
        session.confirmation_status = "not_required"
    
    return result.assistant_message
```

### 4. pre-flight confirmation 处理

```python
def _preflight_confirmation(self, session: SessionState, content: str) -> str | None:
    resolution = self._resolver.resolve(content)
    if resolution == "unknown":
        return None  # 不是确认/否认，让 AgentLoop 处理
    
    session.confirmation_status = resolution  # Phase 4 compat
    session.add_step("preflight_confirmation", resolution=resolution)
    
    if resolution == "confirm":
        action = session.pending_action
        record = self.gateway.execute(
            state=session,
            tool_name=action.action_name,
            arguments=action.arguments,
            confirmed=True,
        )
        session.pending_action = None
        if record.status == "success":
            msg = "Done. I have completed the requested update."
        else:
            msg = _map_guard_error_to_user_message(str(record.error))
        session.messages.append(Message(role="assistant", content=msg))
        return msg
    
    elif resolution == "deny":
        session.pending_action = None
        msg = "No changes were made."
        session.messages.append(Message(role="assistant", content=msg))
        return msg
    
    elif resolution == "changed":
        session.pending_action = None
        msg = "I discarded the previous request. Please provide updated details."
        session.messages.append(Message(role="assistant", content=msg))
        return None  # 继续到 AgentLoop 处理新请求
    
    return None
```

### 5. pre-flight identity shortcut

```python
def _preflight_identity(self, session: SessionState, content: str) -> None:
    # Email shortcut
    email_match = EMAIL_RE.search(content)
    if email_match:
        email = email_match.group(0)
        record = self.gateway.execute(
            state=session,
            tool_name="find_user_id_by_email",
            arguments={"email": email},
        )
        if record.status == "success":
            user_id = str(record.observation)
            session.authenticated_user_id = user_id
            session.auth_method = "email"
            session.active_user_identity = {"email": email, "user_id": user_id}
            user_record = self.gateway.execute(
                state=session,
                tool_name="get_user_details",
                arguments={"user_id": user_id},
            )
            if user_record.status == "success":
                session.loaded_context.users[user_id] = user_record.observation
            session.add_step("preflight_identity", method="email", user_id=user_id)
        return
    
    # Name+zip shortcut
    name_zip_match = NAME_ZIP_RE.search(content)
    if name_zip_match:
        first_name, last_name, zip_code = name_zip_match.groups()
        record = self.gateway.execute(
            state=session,
            tool_name="find_user_id_by_name_zip",
            arguments={
                "first_name": first_name,
                "last_name": last_name,
                "zip": zip_code,
            },
        )
        if record.status == "success":
            user_id = str(record.observation)
            session.authenticated_user_id = user_id
            session.auth_method = "name_zip"
            session.active_user_identity = {
                "first_name": first_name, "last_name": last_name,
                "zip": zip_code, "user_id": user_id,
            }
            user_record = self.gateway.execute(
                state=session,
                tool_name="get_user_details",
                arguments={"user_id": user_id},
            )
            if user_record.status == "success":
                session.loaded_context.users[user_id] = user_record.observation
            session.add_step("preflight_identity", method="name_zip", user_id=user_id)
```

### 6. 安全降级（provider=None）

```python
def _safe_fallback(self, session: SessionState, content: str) -> str:
    msg = (
        "I'm sorry, the agent is running in offline mode. "
        "Please configure an LLM provider to handle your request."
    )
    session.messages.append(Message(role="assistant", content=msg))
    session.add_step("safe_fallback", reason="no_provider")
    return msg
```

### 7. run_script() 适配

```python
def run_script(self, *, messages, session_id=None, task_id=None, 
               max_turns=20, user_simulator_callback=None) -> AgentRunResult:
    run_id = session_id or f"agent-{uuid.uuid4().hex[:12]}"
    session = SessionState(session_id=run_id, task_id=task_id)  # ← 改为 SessionState
    # ... 多轮循环不变，handle_user_message 现在走新路径 ...
```

关键变化：`ConversationState(run_id, task_id)` → `SessionState(run_id, task_id)`。

### 8. parsers.py 精简

保留：
- `EMAIL_RE` — pre-flight identity shortcut
- `NAME_ZIP_RE` — pre-flight identity shortcut
- `clean_llm_scalar`、`clean_llm_list` — 可能仍被 runtime 引用

删除：
- `infer_intent` — LLM 替代
- `parse_address` — LLM 替代
- `parse_item_replacement_pairs` — LLM 替代
- `parse_shipping_method` — LLM 替代
- `code_missing_slots` — LLM 替代
- `merge_policy_decisions` — LLM 替代
- `has_assistant_response` — AgentLoop 替代
- `last_assistant_message` — AgentLoop 替代
- `ITEM_RE`、`ORDER_RE`、`PAYMENT_RE` — LLM 自己做提取

### 9. builders.py 评估

| 函数 | 决策 | 原因 |
|------|------|------|
| `merge_slots` | 删除 | LLM 自行合并参数 |
| `pending_action_has_required_args` | 删除 | AgentLoop pre-validation 处理 |
| `normalize_llm_action_arguments` | 删除 | Gateway/guard 处理 |
| `pending_prompt` | 删除 | AgentLoop step_pending 生成确认消息 |

如果 builders.py 删空，则删除整个文件。如果有残留函数被其他地方引用，保留文件。

---

## 评估 runner 兼容性

Phase 4 不修改 `eval/runner.py`。通过以下措施保持可用：

| 依赖项 | Phase 4 如何处理 |
|--------|-----------------|
| `state.current_intent` | SessionState 兼容字段，默认 "unknown" |
| `state.confirmation_status` | SessionState 兼容字段，pre-flight 设置 |
| `state.policy_decision` | SessionState 兼容字段，默认 None |
| `DisabledLLMProvider()` | 实现 chat_with_tools()，runtime 进安全降级 |
| `runtime.run_script()` | 保留，内部改用 SessionState + 新 handle_user_message |
| `AgentRunResult.state` | 返回 SessionState（有全部兼容字段） |

预期行为：
- `require_llm=False`（默认）：provider=None，安全降级，eval 中所有 case 会返回固定文案，pass_rate 会下降但**不会崩溃**
- `require_llm=True`：正常 LLM tool-calling 路径
- Phase 5 引入 ScriptedToolCallingProvider 后恢复确定性 eval

---

## workbench 兼容性

workbench/session.py 硬编码 `mode="deterministic"` + `DisabledLLMProvider()`。

Phase 4：workbench 创建 `AgentRuntime(provider=DisabledLLMProvider())`，runtime 走安全降级路径，返回固定文案。功能降级但可用。

Phase 5：workbench 切换到 ScriptedToolCallingProvider 或移除 deterministic mode。

---

## 测试计划

Phase 4 主要测试类型变更（pipeline 删除 → AgentLoop 接管）：

| # | 测试 | 覆盖 |
|---|------|------|
| 1 | 现有 test_agent_core.py | 确认 ConfirmationResolver、guard、gateway 测试不受影响 |
| 2 | 现有 test_llm_agent.py | 确认 16 个 AgentLoop 测试通过 |
| 3 | 现有 test_context_builder.py | 确认不受影响 |
| 4 | 现有 test_session_state.py | 确认新增兼容字段 |
| 5 | 新增: test_runtime_preflight.py | Pre-flight confirmation + identity shortcut |
| 6 | 新增: test_runtime_safe_fallback.py | Provider=None → 安全降级文案 |
| 7 | 新增: test_runtime_run_script.py | run_script() 多轮循环使用新 handle_user_message |
| 8 | eval smoke: `uv run phase2-eval --subset curated_mvp --trials 1` | 确认不崩溃（pass_rate 可能下降，但无 crash） |

---

## 验收标准

- [ ] `pipeline.py`、`plan_handlers.py`、`graph.py` 已删除
- [ ] `parsers.py` 已精简（只保留 EMAIL_RE、NAME_ZIP_RE、clean_llm_*）
- [ ] `builders.py` 已评估（删除 LLM 替代的函数）
- [ ] `runtime.py` 不再 import 被删除模块
- [ ] `handle_user_message()` 走 pre-flight → AgentLoop → post-process 路径
- [ ] provider=None 时安全降级，不执行写操作
- [ ] pending confirmation 跨轮可执行
- [ ] `uv run python -m pytest tests/ -q` 通过（不含被删模块的 import）
- [ ] `uv run ruff check .` 通过
- [ ] `uv run phase2-eval --subset curated_mvp --trials 1` 不崩溃
