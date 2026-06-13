# Phase 4: Runtime 切换与旧 Runtime 删除 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `AgentRuntime.handle_user_message()` 从 12-node pipeline 切换为 pre-flight → AgentLoop → post-process，删除 pipeline.py / plan_handlers.py / graph.py，精简 parsers.py。

**Architecture:** runtime.py 重写为 pre-flight confirmation shortcut + identity shortcut + AgentLoop + safe fallback。SessionState 补 5 个兼容字段让 eval runner 不崩溃。DisabledLLMProvider 实现 chat_with_tools()。

**Tech Stack:** Python 3.14、Pydantic v2、pytest、项目现有 AgentLoop / ContextBuilder / ConfirmationResolver / ScriptedToolCallingProvider

---

## 文件结构

```
删除:
  app/agent/pipeline.py       (445 lines) — 12 节点 pipeline 函数
  app/agent/plan_handlers.py   (276 lines) — 8 个 intent handler
  app/agent/graph.py          (63 lines)  — LangGraph 编排

修改:
  app/agent/models.py         — SessionState 补 5 个兼容字段
  app/agent/providers.py      — DisabledLLMProvider.chat_with_tools()
  app/agent/runtime.py        — 重写为 pre-flight + AgentLoop + post-process
  app/agent/parsers.py        — 删除 infer_intent/parse_shipping_method 及其依赖
  tests/test_agent_core.py    — 删除 ShippingIntentParserTests / ShippingSlotParserTests

新增:
  tests/test_runtime_phase4.py — pre-flight + safe fallback 测试
```

---

### Task 1: SessionState 兼容字段 + DisabledLLMProvider.chat_with_tools

**Files:**
- Modify: `app/agent/models.py`
- Modify: `app/agent/providers.py`

**Background:** 两个独立的小改动，为后续 runtime 重写做准备。SessionState 需要 eval runner 引用的废弃字段；DisabledLLMProvider 需要 chat_with_tools() 让 AgentLoop 不崩溃。

- [ ] **Step 1: 在 SessionState 中追加兼容字段**

Read `app/agent/models.py`。在 `SessionState` 类的 `termination_reason` 字段后追加：

```python
    # ── Phase 4 temporary compat (Phase 5 removes these) ──
    current_intent: str = "unknown"
    slots: Dict[str, Any] = Field(default_factory=dict)
    confirmation_status: str = "not_required"
    policy_decision: Optional[PolicyDecision] = None
    risk_level: str = "low"
```

`slots` 是额外补充的——`test_agent_core.py:636` 引用 `result.state.slots["reason"]`。

- [ ] **Step 2: DisabledLLMProvider 添加 chat_with_tools**

Read `app/agent/providers.py`。在 `DisabledLLMProvider` 类中追加方法：

```python
    def chat_with_tools(
        self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> ToolCallResponse:
        return ToolCallResponse(
            assistant_content=(
                "I'm sorry, the agent is running in offline mode. "
                "Please configure an LLM provider to handle your request."
            ),
            finish_reason="stop",
        )
```

需要在文件顶部确认 `ToolCallResponse` 已 import，`List` 和 `Dict` 已从 typing import。

- [ ] **Step 3: 运行测试确认不破坏现有功能**

```bash
uv run python -m pytest tests/test_session_state.py tests/test_tool_calling_provider.py -v
uv run python -m pytest tests/ -q
```

预期：278 测试通过，DisableLLMProvider 新方法不引起任何回归。

- [ ] **Step 4: Lint + 提交**

```bash
uv run ruff check app/agent/models.py app/agent/providers.py
git add app/agent/models.py app/agent/providers.py
git commit -m "feat: add SessionState compat fields and DisabledLLMProvider.chat_with_tools"
```

---

### Task 2: 删除旧 pipeline / plan_handlers / graph

**Files:**
- Delete: `app/agent/pipeline.py`
- Delete: `app/agent/plan_handlers.py`
- Delete: `app/agent/graph.py`

**Background:** 三个模块共 784 行，被 AgentLoop 完全替代。删除前确认无隐式依赖。

- [ ] **Step 1: 确认当前测试基线**

```bash
uv run python -m pytest tests/ -q
```

预期：278 通过（但 runtime.py 仍在 import 这些模块）。

- [ ] **Step 2: 删除三个文件**

```bash
rm app/agent/pipeline.py
rm app/agent/plan_handlers.py
rm app/agent/graph.py
```

- [ ] **Step 3: 运行测试确认 runtime.py crash（预期行为）**

```bash
uv run python -m pytest tests/test_agent_core.py::RuntimeSmokeTests -v 2>&1 | head -20
```

预期：FAIL，ModuleNotFoundError — runtime.py 还在 import 这些模块。

- [ ] **Step 4: 提交删除**

```bash
git add -u app/agent/pipeline.py app/agent/plan_handlers.py app/agent/graph.py
git commit -m "refactor: delete old pipeline, plan_handlers, and graph modules"
```

---

### Task 3: Runtime 重写 — pre-flight + AgentLoop + post-process

**Files:**
- Modify: `app/agent/runtime.py`

**Background:** 这是 Phase 4 最核心的变更。runtime.py 从 541 行精简到 ~200 行，删除所有旧 pipeline import 和 12-node 调用链，改为 pre-flight → AgentLoop → post-process。

- [ ] **Step 1: 编写 runtime test**

创建 `tests/test_runtime_phase4.py`：

```python
from __future__ import annotations

import tempfile

from app.agent.models import Message, SessionState
from app.agent.providers import DisabledLLMProvider, ScriptedToolCallingProvider, ToolCallResponse
from app.agent.runtime import AgentRuntime
from app.config import resolve_config


def _runtime_with_disabled_provider(tmp: str) -> AgentRuntime:
    return AgentRuntime(
        resolve_config(artifact_dir=tmp),
        provider=DisabledLLMProvider(),
    )


class TestRuntimeSafeFallback:
    """Tests: provider=None returns safe fallback message."""

    def test_safe_fallback_when_no_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime_with_disabled_provider(tmp)
            result = runtime.run_script(
                messages=[{"role": "user", "content": "Help me with my order"}],
                session_id="test-fallback",
            )

        assert "offline" in result.state.messages[-1].content.lower()
        assert result.state.termination_reason == "script_completed"


class TestRuntimePreflightConfirmation:
    """Tests: pending confirmation handled in pre-flight."""

    def test_confirm_executes_pending_action(self) -> None:
        # Uses ScriptedToolCallingProvider
        from app.agent.models import PendingAction
        from app.tools.retail_adapter import get_order_from_db

        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            runtime = AgentRuntime(config, provider=DisabledLLMProvider())

            # Manually set up a session with pending action
            session = SessionState(session_id="test-confirm")
            db = runtime.retail_runtime.db
            db_orders = db.get("orders", {})
            pending_order = next(
                (oid for oid, o in db_orders.items() if o.get("status") == "pending"),
                None,
            )
            assert pending_order is not None
            order = get_order_from_db(db, pending_order)
            user_id = order["user_id"]
            session.authenticated_user_id = user_id
            session.loaded_context.orders[pending_order] = order
            session.pending_action = PendingAction(
                action_name="cancel_pending_order",
                arguments={"order_id": pending_order, "reason": "no longer needed"},
                user_facing_summary=f"Cancel order {pending_order}",
            )

            msg = runtime.handle_user_message(session, "yes confirm")
            assert "completed" in msg.lower() or "Done" in msg

    def test_deny_clears_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            runtime = AgentRuntime(config, provider=DisabledLLMProvider())
            session = SessionState(session_id="test-deny")
            session.pending_action = PendingAction(
                action_name="cancel_pending_order",
                arguments={"order_id": "#W1234567", "reason": "no longer needed"},
                user_facing_summary="Cancel order",
            )
            msg = runtime.handle_user_message(session, "no don't do it")
            assert "No changes" in msg or "no changes" in msg.lower()
            assert session.pending_action is None


class TestRuntimeIntegration:
    """Tests: end-to-end script execution."""

    def test_run_script_uses_session_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime_with_disabled_provider(tmp)
            result = runtime.run_script(
                messages=[{"role": "user", "content": "Hello"}],
                session_id="test-ss",
            )
        assert result.state.session_id == "test-ss"
        assert isinstance(result.state, SessionState)
        assert len(result.state.messages) >= 2  # user + assistant
```

- [ ] **Step 2: 运行新测试确认失败**

```bash
uv run python -m pytest tests/test_runtime_phase4.py -v
```

预期：部分 FAIL — runtime.py 尚未重写，仍在 import 已删除的模块。

- [ ] **Step 3: 重写 runtime.py**

**策略**：先备份当前 runtime.py 到 git（已有历史），然后逐步替换内容。

新 `app/agent/runtime.py` 结构：

```python
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from app.agent.confirmation import ConfirmationResolver
from app.agent.context_builder import ContextBuilder
from app.agent.llm_agent import AgentLoop
from app.agent.models import (
    Message,
    SessionState,
)
from app.agent.parsers import EMAIL_RE, NAME_ZIP_RE, clean_llm_list, clean_llm_scalar
from app.agent.prompts import prompt_metadata
from app.agent.providers import DisabledLLMProvider, LLMProvider, build_default_provider
from app.config import AppConfig
from app.ops.tracing import TraceWriter, final_state_summary
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter, RetailRuntime, get_order_from_db


GUARD_USER_MESSAGES = {
    "replacement_item_product_mismatch": "I can only replace an item with another available option from the same product.",
    "replacement_item_unavailable": "That replacement item is not available.",
    "replacement_item_count_mismatch": "The number of replacement items must match the number of items being replaced.",
    "replacement_item_not_found": "That replacement item could not be found in the catalog.",
    "order_item_not_found": "The item you want to replace is not in that order.",
    "payment_method_not_owned": "I can only use payment methods saved on your account.",
    "gift_card_balance_insufficient": "That gift card does not have enough balance for this order.",
    "same_payment_method": "The new payment method must be different from the current one.",
    "non_pending_order_cannot_be_modified": "I can only modify orders that are still pending.",
    "non_pending_order_cannot_be_cancelled": "I can only cancel orders that are still pending.",
    "non_delivered_order_cannot_be_returned": "I can only create returns for delivered orders.",
    "non_delivered_order_cannot_be_exchanged": "I can only create exchanges for delivered orders.",
    "exchange_item_count_mismatch": "The number of new items must match the number of items being exchanged.",
    "ownership_violation": "I cannot access or modify orders for another account.",
    "read_before_write_required": "I need to review the order details before making changes. Please ask me to look up the order first.",
    "authentication_required": "Please verify your identity before making changes.",
    "user_not_found": "I could not verify your account. Please provide different credentials.",
    "invalid_cancel_reason": "Please provide a valid cancellation reason: no longer needed or ordered by mistake.",
    "duplicate_write_lock": "A similar change is already in progress for this order.",
    "order_already_cancelled_or_locked": "This order has already been cancelled.",
    "order_items_already_modified": "The items in this order have already been modified.",
    "item_already_returned_or_exchanged": "One or more of these items has already been returned or exchanged.",
    "unsupported_in_mvp": "That write operation is not yet supported.",
    "unknown_write_action": "That update type is not recognised.",
    "explicit_confirmation_required": "Please confirm the requested update before proceeding.",
    "same_shipping_method": "That is already the current shipping method for this order.",
    "unknown_shipping_method": "That shipping method is not available. We offer standard, express, and overnight.",
    "payment_method_required_for_upgrade": "Upgrading to a faster shipping method requires a payment method. Please provide one.",
    "order_not_found": "That order could not be found.",
}


def _map_guard_error_to_user_message(error: str) -> str:
    return GUARD_USER_MESSAGES.get(
        str(error),
        "I could not complete that update. Please try again or contact support.",
    )


@dataclass
class AgentRunResult:
    run_id: str
    state: SessionState
    trace_artifact_path: Path

    def as_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "termination_reason": self.state.termination_reason,
            "final_state": final_state_summary(self.state),
            "trace_artifact_path": str(self.trace_artifact_path),
        }


class AgentRuntime:
    def __init__(
        self,
        config: AppConfig,
        provider: Optional[LLMProvider] = None,
        require_llm: bool = False,
        runtime: Optional[RetailRuntime] = None,
    ) -> None:
        self.config = config
        if runtime is not None:
            self.retail_runtime = runtime
        else:
            self.retail_runtime = RetailAdapter(config).create_runtime()
        self.registry = ToolRegistry(self.retail_runtime.tools)
        self.gateway = ToolGateway(registry=self.registry, runtime=self.retail_runtime)
        self._resolver = ConfirmationResolver()

        if isinstance(provider, DisabledLLMProvider):
            self.provider = None
        else:
            self.provider = provider or build_default_provider(
                api_key=config.deepseek_api_key,
                base_url=config.deepseek_base_url,
                model=config.default_agent_model,
                timeout=config.agent_llm_timeout_seconds,
                max_retries=config.agent_llm_max_retries,
                require_llm=require_llm,
            )

        # Context builder
        policy_path = config.retail_policy_path
        policy_text = policy_path.read_text()[:500] if policy_path.exists() else ""
        self._context_builder = ContextBuilder(policy_text=policy_text)

    def run_script(
        self,
        *,
        messages: Iterable[Dict[str, str]],
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        max_turns: int = 20,
        user_simulator_callback: Optional[Callable[[str], Optional[str]]] = None,
    ) -> AgentRunResult:
        run_id = session_id or f"agent-{uuid.uuid4().hex[:12]}"
        session = SessionState(session_id=run_id, task_id=task_id)
        initial_db_hash = self.retail_runtime.db_hash()
        turn = 0
        message_list = list(messages)
        message_index = 0
        while message_index < len(message_list) and turn < max_turns:
            message = message_list[message_index]
            message_index += 1
            turn += 1
            if message.get("role") != "user":
                continue
            assistant_msg = self.handle_user_message(session, message.get("content", ""))
            if user_simulator_callback and assistant_msg and not session.termination_reason:
                next_user_msg = user_simulator_callback(assistant_msg)
                if next_user_msg:
                    message_list.append({"role": "user", "content": next_user_msg})
        if not session.termination_reason:
            session.termination_reason = "script_completed"
        trace_path = TraceWriter(self.config.run_artifact_dir).write(
            run_id=run_id,
            state=session,
            metadata={
                "runtime_source": self.retail_runtime.source,
                "model": self.config.default_agent_model,
                "llm_enabled": self.provider is not None,
                "llm_timeout_seconds": self.config.agent_llm_timeout_seconds,
                "llm_max_retries": self.config.agent_llm_max_retries,
                "initial_db_hash": initial_db_hash,
                "final_db_hash": self.retail_runtime.db_hash(),
                "tau2_bench_root": str(self.config.tau2_bench_root),
                "tau3_retail_root": str(self.config.tau3_retail_root),
                "retail_db_path": str(self.config.retail_db_path),
                "prompts": prompt_metadata(),
            },
        )
        return AgentRunResult(
            run_id=run_id,
            state=session,
            trace_artifact_path=trace_path,
        )

    def handle_user_message(self, session: SessionState, content: str) -> str:
        t0 = time.perf_counter()
        session.messages.append(Message(role="user", content=content))

        # ── 1. Pre-flight: pending confirmation short-circuit ──
        if session.pending_action:
            result = self._preflight_confirmation(session, content)
            if result is not None:
                return result

        # ── 2. Pre-flight: identity shortcut ──
        if not session.authenticated_user_id:
            self._preflight_identity(session, content)

        # ── 3. LLM agent loop (or safe fallback) ──
        if self.provider is None:
            msg = (
                "I'm sorry, the agent is running in offline mode. "
                "Please configure an LLM provider to handle your request."
            )
            session.messages.append(Message(role="assistant", content=msg))
            session.add_step("safe_fallback", reason="no_provider")
            return msg

        loop = AgentLoop(
            provider=self.provider,
            gateway=self.gateway,
            registry=self.registry,
            context_builder=self._context_builder,
        )
        result = loop.run_turn(session, content)

        # ── 4. Post-process ──
        session.messages.append(Message(role="assistant", content=result.assistant_message))

        # Phase 4 compat: populate deprecated fields for eval runner
        if result.pending_action_set:
            session.confirmation_status = "required"
        elif not session.pending_action:
            session.confirmation_status = "not_required"

        session.step_durations["handle_user_message"] = round(
            (time.perf_counter() - t0) * 1000, 1
        )
        return result.assistant_message

    # ── Pre-flight helpers ──

    def _preflight_confirmation(
        self, session: SessionState, content: str
    ) -> Optional[str]:
        resolution = self._resolver.resolve(content)
        if resolution == "unknown":
            return None  # not a confirmation message, let AgentLoop handle

        session.confirmation_status = resolution
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
            session.slots = {}  # Phase 4 compat
            msg = "I discarded the previous request. Please provide updated details."
            session.messages.append(Message(role="assistant", content=msg))
            return None  # continue to AgentLoop

        return None

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
                    "first_name": first_name,
                    "last_name": last_name,
                    "zip": zip_code,
                    "user_id": user_id,
                }
                user_record = self.gateway.execute(
                    state=session,
                    tool_name="get_user_details",
                    arguments={"user_id": user_id},
                )
                if user_record.status == "success":
                    session.loaded_context.users[user_id] = user_record.observation
                session.add_step(
                    "preflight_identity", method="name_zip", user_id=user_id
                )
```

- [ ] **Step 4: 运行新 runtime 测试**

```bash
uv run python -m pytest tests/test_runtime_phase4.py -v
```

预期：至少部分通过。`TestRuntimeSafeFallback` 应该通过；`TestRuntimePreflightConfirmation` 可能需要调整（依赖 DB 中的 pending order）。

- [ ] **Step 5: 运行全部测试**

```bash
uv run python -m pytest tests/ -q
```

预期：部分 RuntimeSmokeTests 会失败（例如 `test_scripted_authentication_and_order_lookup` 在 safe fallback 下无法返回 "currently pending"）。这是预期行为——Phase 4 不保证 eval 功能性，只保证不崩溃。

- [ ] **Step 6: Lint + 提交**

```bash
uv run ruff check app/agent/runtime.py tests/test_runtime_phase4.py
git add app/agent/runtime.py tests/test_runtime_phase4.py
git commit -m "feat: rewrite runtime to pre-flight + AgentLoop + post-process"
```

---

### Task 4: 精简 parsers.py + 清理旧测试

**Files:**
- Modify: `app/agent/parsers.py`
- Modify: `tests/test_agent_core.py`

**Background:** 删除 `infer_intent`、`parse_shipping_method` 及其依赖的 regex/mappings。同时删除测试这些函数的 test classes。

- [ ] **Step 1: 检查 parsers.py 保留函数的使用方**

```bash
grep -rn "EMAIL_RE\|NAME_ZIP_RE\|clean_llm_scalar\|clean_llm_list\|SUPPORTED_INTENTS" app/ tests/ | grep -v "parsers.py"
```

确认只有 runtime.py（pre-flight identity）和 llm_client.py 引用保留的函数。

- [ ] **Step 2: 精简 parsers.py**

Read `app/agent/parsers.py`。删除以下内容：
- `infer_intent` 函数及其 `_INTENT_MAP`、`_INTENT_PATTERNS`
- `parse_shipping_method` 函数
- `parse_address` 函数
- `parse_item_replacement_pairs` 函数
- `code_missing_slots` 函数
- `merge_policy_decisions` 函数（注意：runtime.py 的 `__init_subclass__` wrapper 引用了它——已随 pipeline 删除移除）
- `has_assistant_response` 函数
- `last_assistant_message` 函数
- `ITEM_RE`、`ORDER_RE`、`PAYMENT_RE` regex

保留：
- `EMAIL_RE`
- `NAME_ZIP_RE`
- `clean_llm_scalar`
- `clean_llm_list`
- `SUPPORTED_INTENTS`（被 llm_client.py 引用）

- [ ] **Step 3: 从 test_agent_core.py 删除旧 parser 测试**

删除两个完整的 test class：
- `ShippingIntentParserTests`（约 80 行，测试 `infer_intent`）
- `ShippingSlotParserTests`（约 30 行，测试 `parse_shipping_method`）

- [ ] **Step 4: 运行测试**

```bash
uv run python -m pytest tests/ -q
```

预期：删除旧测试后测试总数减少约 10-12 个，剩余测试通过（除 RuntimeSmokeTests 中因 safe fallback 无法通过的）。

- [ ] **Step 5: Lint + 提交**

```bash
uv run ruff check app/agent/parsers.py tests/test_agent_core.py
git add app/agent/parsers.py tests/test_agent_core.py
git commit -m "refactor: trim parsers.py — remove intent/slot parsing functions"
```

---

### Task 5: 评估并清理 builders.py

**Files:**
- Modify: `app/agent/builders.py`

**Background:** builders.py 的函数服务于旧 pipeline 的 slot merging 和 pending action 构建，现在全部由 AgentLoop/gateway 处理。

- [ ] **Step 1: 检查 builders.py 的引用方**

```bash
grep -rn "from app.agent.builders import\|from app.agent.builders\." app/ tests/
```

- [ ] **Step 2: 如果无引用，删除文件**

```bash
rm app/agent/builders.py
```

如果有残留引用（比如 llm_client.py），评估是否可替换。

- [ ] **Step 3: 运行测试确认**

```bash
uv run python -m pytest tests/ -q
```

- [ ] **Step 4: Lint + 提交**

```bash
uv run ruff check .
git add -u app/agent/builders.py  # 删除
git commit -m "refactor: remove builders.py — functions replaced by AgentLoop/gateway"
```

---

### Task 6: 清理 runtime.py 中的残存引用

**Files:**
- Modify: `app/agent/runtime.py`
- Modify: `app/agent/llm_client.py`（如需要）

**Background:** 确保所有对 pipeline/plan_handlers/graph 的 import 都已移除。检查 llm_client.py 是否仍然被使用。

- [ ] **Step 1: 检查残留 import**

```bash
grep -rn "pipeline\|plan_handlers\|graph\|builders\." app/agent/runtime.py app/agent/llm_client.py 2>/dev/null
```

预期：无匹配（runtime.py 已在 Task 3 重写）。

- [ ] **Step 2: 检查 llm_client.py 是否仍被 import**

```bash
grep -rn "from app.agent.llm_client\|import llm_client" app/
```

如果有引用，保留文件但可能不再需要所有函数。如果无引用，可以删除（但在不同 PR）。

- [ ] **Step 3: Lint + 提交**

```bash
uv run ruff check .
git add -u  # stage deletions
git commit -m "chore: remove stale imports and dead code references"
```

---

### Task 7: 回归 + smoke test

**Files:** 不修改（除非修复回归）

- [ ] **Step 1: 运行全部单元测试**

```bash
uv run python -m pytest tests/ -q
```

记录通过的测试数和任何失败。对于 RuntimeSmokeTests 中因 safe fallback 导致的失败，确认是预期行为（返回 "offline mode" 文案而非功能响应）。

- [ ] **Step 2: Eval smoke test**

```bash
uv run phase2-eval --subset curated_mvp --trials 1 2>&1 | tail -10
```

预期：不崩溃（no ImportError, no AttributeError）。pass_rate 可能低于之前，但 runner 正常运行。

- [ ] **Step 3: Lint 全部**

```bash
uv run ruff check .
```

预期：通过。

- [ ] **Step 4: 更新阶段状态 + 提交**

在 `docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md` 的 Phase Status 部分追加：

```markdown
- Phase 4：✅ 完成 — runtime 切换到 pre-flight + AgentLoop + post-process，删除 pipeline/plan_handlers/graph，精简 parsers，eval smoke 不崩溃（2026-06-13）。
```

```bash
git add docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md
git commit -m "docs: mark LLM agent tool-calling phase 4 complete"
```

---

## 自审记录

Spec 覆盖：
- SessionState 兼容字段 → Task 1
- DisabledLLMProvider.chat_with_tools() → Task 1
- 删除 pipeline.py → Task 2
- 删除 plan_handlers.py → Task 2
- 删除 graph.py → Task 2
- pre-flight confirmation → Task 3
- pre-flight identity shortcut → Task 3
- AgentLoop integration → Task 3
- safe fallback (provider=None) → Task 3
- run_script() 适配 SessionState → Task 3
- parsers.py 精简 → Task 4
- builders.py 评估/删除 → Task 5
- 死代码清理 → Task 6
- 测试不崩溃 → Task 7
- eval smoke → Task 7
- phase status 更新 → Task 7

退出条件覆盖：
- `uv run python -m pytest tests/ -q` → Task 7
- `uv run ruff check .` → Task 7
- `uv run phase2-eval --subset curated_mvp --trials 1` → Task 7
