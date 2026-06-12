# Phase 4 Hybrid Ops Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local single-session Hybrid Ops Workbench for scripted and manual retail support agent demos.

**Architecture:** Add a Python workbench API around the existing `AgentRuntime`, with in-memory sessions and snapshot responses. Add a Vite + React frontend that renders an operations dashboard with run controls, business state, conversation, timeline, tool details, and audit state.

**Tech Stack:** Python 3.12, existing `unittest`, FastAPI, Uvicorn, Vite, React, TypeScript, CSS modules/plain CSS.

---

## Scope Check

The approved spec covers one working slice: a single-session local workbench. It includes backend API, session control, snapshot shaping, frontend dashboard, and verification. It deliberately excludes login, persistent run history, SQLite, WebSockets, deployment, and full CR backlog remediation. This is large but coherent because every subsystem supports the same local workbench loop.

## File Structure

Create backend files:

- `app/workbench/__init__.py`: package marker and exported app factory.
- `app/workbench/cases.py`: demo shortlist and curated case catalog serialization.
- `app/workbench/errors.py`: typed API error payloads and HTTP exception helper.
- `app/workbench/snapshot.py`: converts `ConversationState` and runtime DB state into frontend snapshots.
- `app/workbench/session.py`: in-memory `WorkbenchSession` and `WorkbenchSessionManager`.
- `app/workbench/api.py`: FastAPI app factory and route handlers.
- `app/workbench/cli.py`: `phase4-workbench` command that starts the API and points users to the frontend.

Modify backend files:

- `pyproject.toml`: add `fastapi`, `uvicorn`, and `phase4-workbench` script.
- `README.md`: add Phase 4 local run instructions after Phase 3.
- `.gitignore`: ignore frontend install/build artifacts.
- `uv.lock`: update after adding backend dependencies.

Create backend tests:

- `tests/test_workbench_cases.py`: case catalog and shortlist behavior.
- `tests/test_workbench_session.py`: session controller, Step, Run all, manual messages, trace updates.
- `tests/test_workbench_api.py`: API route behavior and structured errors.

Create frontend files:

- `workbench/package.json`: Vite/React scripts and dependencies.
- `workbench/index.html`: root HTML shell.
- `workbench/tsconfig.json`: TypeScript config.
- `workbench/tsconfig.node.json`: Vite node config.
- `workbench/vite.config.ts`: dev proxy to Python API.
- `workbench/src/main.tsx`: React entrypoint.
- `workbench/src/App.tsx`: application state and layout composition.
- `workbench/src/api.ts`: API client.
- `workbench/src/types.ts`: snapshot and case TypeScript types.
- `workbench/src/styles.css`: operations dashboard styling.
- `workbench/src/components/RunControl.tsx`: mode/case/step/run/manual controls.
- `workbench/src/components/BusinessState.tsx`: user/order/intent/slots/pending summary.
- `workbench/src/components/Conversation.tsx`: transcript.
- `workbench/src/components/Timeline.tsx`: events list and selection.
- `workbench/src/components/Inspector.tsx`: selected event/tool/audit details.
- `workbench/src/components/StatusBadge.tsx`: shared compact badges.

---

### Task 1: Add Backend Dependencies And Workbench Package Skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `app/workbench/__init__.py`
- Create: `app/workbench/errors.py`
- Modify: `uv.lock`
- Test: `tests/test_workbench_errors.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workbench_errors.py`:

```python
import unittest

from app.workbench.errors import WorkbenchAPIError, error_payload


class WorkbenchErrorTests(unittest.TestCase):
    def test_error_payload_is_stable(self):
        error = WorkbenchAPIError(
            code="session_not_found",
            message="Session was not found.",
            recoverable=True,
            details={"session_id": "missing"},
        )

        self.assertEqual(
            error_payload(error),
            {
                "error": {
                    "code": "session_not_found",
                    "message": "Session was not found.",
                    "recoverable": True,
                    "details": {"session_id": "missing"},
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_workbench_errors -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.workbench'`.

- [ ] **Step 3: Add dependencies and script entry**

Modify `pyproject.toml`:

```toml
dependencies = [
    "fastapi>=0.115.0",
    "langgraph>=0.2.70",
    "openai>=1.60.0",
    "pydantic>=2.10.0",
    "python-dotenv>=1.0.0",
    "uvicorn>=0.34.0",
]

[project.scripts]
phase0-check = "app.phase0.cli:check_main"
phase0-report = "app.phase0.cli:report_main"
phase0-smoke = "app.phase0.cli:smoke_main"
phase1-chat = "app.cli.chat:chat_main"
phase2-eval = "app.cli.eval:eval_main"
phase3-dashboard = "app.dashboard.cli:dashboard_main"
phase4-workbench = "app.workbench.cli:workbench_main"
```

- [ ] **Step 4: Add the workbench package and error helpers**

Create `app/workbench/__init__.py`:

```python
from __future__ import annotations

__all__: list[str] = []
```

Create `app/workbench/errors.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class WorkbenchAPIError(Exception):
    code: str
    message: str
    recoverable: bool = True
    details: Dict[str, Any] = field(default_factory=dict)
    status_code: int = 400


def error_payload(error: WorkbenchAPIError) -> Dict[str, Any]:
    return {
        "error": {
            "code": error.code,
            "message": error.message,
            "recoverable": error.recoverable,
            "details": error.details,
        }
    }
```

Task 5 will export `create_app` from `app/workbench/__init__.py` after `app/workbench/api.py` exists.

- [ ] **Step 5: Update the lockfile**

Run:

```bash
uv lock
```

Expected: exit 0 and `uv.lock` updated for `fastapi` and `uvicorn`.

- [ ] **Step 6: Run the focused test and verify it passes**

Run:

```bash
python3 -m unittest tests.test_workbench_errors -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock app/workbench/__init__.py app/workbench/errors.py tests/test_workbench_errors.py
git commit -m "feat: add workbench backend skeleton"
```

---

### Task 2: Build Case Catalog And Demo Shortlist

**Files:**
- Create: `app/workbench/cases.py`
- Test: `tests/test_workbench_cases.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workbench_cases.py`:

```python
import unittest

from app.workbench.cases import DEMO_CASE_IDS, build_case_catalog, get_case_by_id


class WorkbenchCaseCatalogTests(unittest.TestCase):
    def test_catalog_contains_demo_shortlist_and_all_cases(self):
        catalog = build_case_catalog()
        all_ids = {case["case_id"] for case in catalog["all_cases"]}
        demo_ids = [case["case_id"] for case in catalog["demo_cases"]]

        self.assertEqual(demo_ids, DEMO_CASE_IDS)
        self.assertTrue(set(DEMO_CASE_IDS).issubset(all_ids))
        self.assertEqual(catalog["subset"], "curated_mvp")
        self.assertGreaterEqual(len(catalog["all_cases"]), 11)

    def test_case_serialization_has_script_metadata(self):
        catalog = build_case_catalog()
        case = next(item for item in catalog["all_cases"] if item["case_id"] == "cancel_pending_order")

        self.assertEqual(case["category"], "cancel")
        self.assertEqual(case["message_count"], 2)
        self.assertEqual(case["expected_intent"], "cancel_order")
        self.assertEqual(case["expected_order_status"], "cancelled")
        self.assertIn("Cancel", case["title"])

    def test_get_case_by_id_returns_eval_case(self):
        case = get_case_by_id("transfer_to_human")

        self.assertEqual(case.case_id, "transfer_to_human")
        self.assertEqual(case.category, "transfer")

    def test_get_case_by_id_rejects_unknown_case(self):
        with self.assertRaisesRegex(ValueError, "unknown case"):
            get_case_by_id("missing-case")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_workbench_cases -v
```

Expected: FAIL with `ModuleNotFoundError` or missing `app.workbench.cases`.

- [ ] **Step 3: Implement the case catalog**

Create `app/workbench/cases.py`:

```python
from __future__ import annotations

from typing import Any, Dict, List

from app.eval.cases import EvalCase, get_cases

DEMO_CASE_IDS = [
    "cancel_pending_order",
    "return_delivered_order_item",
    "block_wrong_user_order_access",
    "transfer_to_human",
    "deny_cancel_confirmation",
]

CASE_TITLES = {
    "lookup_pending_order": "Lookup pending order",
    "cancel_pending_order": "Cancel pending order",
    "modify_pending_order_address": "Modify pending order address",
    "return_delivered_order_item": "Return delivered item",
    "exchange_delivered_order_item": "Exchange delivered item",
    "transfer_to_human": "Transfer to human",
    "deny_cancel_confirmation": "Deny cancellation confirmation",
    "changed_confirmation_discards_pending_action": "Changed confirmation discards pending action",
    "block_cancel_processed_order": "Guard blocks processed cancellation",
    "block_return_pending_order": "Guard blocks pending return",
    "block_wrong_user_order_access": "Guard blocks wrong-user access",
}


def build_case_catalog(subset: str = "curated_mvp") -> Dict[str, Any]:
    cases = get_cases(subset)
    serialized = [_serialize_case(case) for case in cases]
    by_id = {case["case_id"]: case for case in serialized}
    demo_cases = [by_id[case_id] for case_id in DEMO_CASE_IDS if case_id in by_id]
    return {
        "subset": subset,
        "demo_case_ids": list(DEMO_CASE_IDS),
        "demo_cases": demo_cases,
        "all_cases": serialized,
    }


def get_case_by_id(case_id: str, subset: str = "curated_mvp") -> EvalCase:
    for case in get_cases(subset):
        if case.case_id == case_id:
            return case
    raise ValueError(f"unknown case: {case_id}")


def _serialize_case(case: EvalCase) -> Dict[str, Any]:
    return {
        "case_id": case.case_id,
        "title": CASE_TITLES.get(case.case_id, case.case_id.replace("_", " ").title()),
        "category": case.category,
        "message_count": len(case.messages),
        "messages": [dict(message) for message in case.messages],
        "expected_user_id": case.expected_user_id,
        "expected_intent": case.expected_intent,
        "expected_order_status": case.expected_order_status,
        "expected_confirmation_status": case.expected_confirmation_status,
        "expected_guard_block_reason": case.expected_guard_block_reason,
        "expected_no_write": case.expected_no_write,
        "expected_tool_names": list(case.expected_tool_names),
        "expected_assistant_contains": case.expected_assistant_contains,
    }
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
python3 -m unittest tests.test_workbench_cases -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/workbench/cases.py tests/test_workbench_cases.py
git commit -m "feat: add workbench case catalog"
```

---

### Task 3: Build Snapshot Serialization

**Files:**
- Create: `app/workbench/snapshot.py`
- Test: `tests/test_workbench_snapshot.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workbench_snapshot.py`:

```python
import unittest

from app.agent.models import ConversationState, Message, PendingAction, ToolCallRecord
from app.workbench.snapshot import build_timeline, redact_value, snapshot_from_state


class WorkbenchSnapshotTests(unittest.TestCase):
    def test_redacts_sensitive_strings_and_keys(self):
        payload = {
            "email": "alex@example.com",
            "phone": "555-123-4567",
            "address": "123 Main St",
            "order_id": "#W1234567",
        }

        redacted = redact_value(payload)

        self.assertEqual(redacted["email"], "[redacted-email]")
        self.assertEqual(redacted["phone"], "[redacted-phone]")
        self.assertEqual(redacted["address"], "[redacted-address]")
        self.assertEqual(redacted["order_id"], "#W1234567")

    def test_timeline_combines_messages_steps_tools_and_audit(self):
        state = ConversationState(session_id="session-1")
        state.messages.append(Message(role="user", content="hello"))
        state.add_step("receive_message", status="seen")
        state.tool_results.append(
            ToolCallRecord(
                tool_name="cancel_pending_order",
                arguments={"order_id": "#W5918442"},
                tool_kind="write",
                status="blocked",
                error="explicit_confirmation_required",
            )
        )
        state.audit_logs.append({"tool_name": "cancel_pending_order"})

        timeline = build_timeline(state)

        self.assertEqual([event["kind"] for event in timeline], ["message", "step", "tool_call", "write_audit"])
        self.assertEqual(timeline[2]["status"], "blocked")
        self.assertEqual(timeline[2]["label"], "cancel_pending_order")

    def test_snapshot_includes_pending_action_and_business_summary(self):
        state = ConversationState(session_id="session-1", authenticated_user_id="user-1")
        state.current_intent = "cancel_order"
        state.slots["order_id"] = "#W5918442"
        state.pending_action = PendingAction(
            action_name="cancel_pending_order",
            arguments={"order_id": "#W5918442", "reason": "no longer needed"},
            user_facing_summary="Cancel order #W5918442 because no longer needed.",
        )
        state.confirmation_status = "required"

        snapshot = snapshot_from_state(
            session_id="session-1",
            mode="deterministic",
            llm_available=False,
            state=state,
            initial_db_hash="before",
            current_db_hash="after",
            trace_artifact_path="/tmp/session-1.json",
            selected_case_id="cancel_pending_order",
            script_cursor=1,
            script_message_count=2,
        )

        self.assertEqual(snapshot["session_id"], "session-1")
        self.assertEqual(snapshot["business"]["authenticated_user_id"], "user-1")
        self.assertEqual(snapshot["business"]["active_order_id"], "#W5918442")
        self.assertEqual(snapshot["pending_action"]["action_name"], "cancel_pending_order")
        self.assertTrue(snapshot["run_controls"]["can_step"])
        self.assertTrue(snapshot["run_controls"]["can_run_all"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_workbench_snapshot -v
```

Expected: FAIL because `app.workbench.snapshot` does not exist.

- [ ] **Step 3: Implement snapshot serialization**

Create `app/workbench/snapshot.py`:

```python
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.agent.models import ConversationState
from app.ops.serialization import to_plain_data

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
SENSITIVE_KEYS = {"address", "email", "payment", "payment_method", "phone", "street", "zip", "zipcode"}


def snapshot_from_state(
    *,
    session_id: str,
    mode: str,
    llm_available: bool,
    state: ConversationState,
    initial_db_hash: str,
    current_db_hash: str,
    trace_artifact_path: str,
    selected_case_id: Optional[str],
    script_cursor: int,
    script_message_count: int,
    last_error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    pending_action = (
        redact_value(state.pending_action.model_dump()) if state.pending_action else None
    )
    policy_decision = (
        redact_value(state.policy_decision.model_dump()) if state.policy_decision else None
    )
    return {
        "session_id": session_id,
        "mode": mode,
        "llm_available": llm_available,
        "selected_case_id": selected_case_id,
        "script_cursor": script_cursor,
        "script_message_count": script_message_count,
        "run_controls": {
            "can_step": bool(selected_case_id and script_cursor < script_message_count),
            "can_run_all": bool(selected_case_id and script_cursor < script_message_count),
            "can_reset": True,
        },
        "messages": redact_value([message.model_dump() for message in state.messages]),
        "business": {
            "authenticated_user_id": state.authenticated_user_id,
            "auth_method": state.auth_method,
            "active_user_identity": redact_value(state.active_user_identity),
            "active_order_id": state.slots.get("order_id"),
            "current_intent": state.current_intent,
            "slots": redact_value(state.slots),
            "confirmation_status": state.confirmation_status,
            "db_changed": initial_db_hash != current_db_hash,
            "initial_db_hash": initial_db_hash,
            "current_db_hash": current_db_hash,
            "write_locks": list(state.write_locks),
        },
        "pending_action": pending_action,
        "policy_decision": policy_decision,
        "tool_results": redact_value([record.model_dump() for record in state.tool_results]),
        "timeline": build_timeline(state),
        "audit_logs": redact_value(state.audit_logs),
        "guard_blocks": [
            redact_value(record.model_dump())
            for record in state.tool_results
            if record.status == "blocked"
        ],
        "trace_artifact_path": trace_artifact_path,
        "last_error": last_error,
    }


def build_timeline(state: ConversationState) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for index, message in enumerate(state.messages):
        events.append(
            {
                "id": f"message-{index}",
                "kind": "message",
                "label": message.role,
                "status": "ok",
                "timestamp": message.created_at,
                "summary": message.content,
                "detail": redact_value(message.model_dump()),
                "source_index": index,
            }
        )
    for index, step in enumerate(state.steps):
        status = step.status
        detail = redact_value(step.detail)
        events.append(
            {
                "id": f"step-{index}",
                "kind": "step",
                "label": step.node,
                "status": status,
                "timestamp": None,
                "summary": _summarize_detail(detail),
                "detail": detail,
                "source_index": index,
            }
        )
    for index, record in enumerate(state.tool_results):
        detail = redact_value(record.model_dump())
        events.append(
            {
                "id": f"tool-{index}",
                "kind": "tool_call",
                "label": record.tool_name,
                "status": record.status,
                "timestamp": None,
                "summary": record.error or record.status,
                "detail": detail,
                "source_index": index,
            }
        )
    for index, entry in enumerate(state.audit_logs):
        detail = redact_value(entry)
        events.append(
            {
                "id": f"audit-{index}",
                "kind": "write_audit",
                "label": str(entry.get("tool_name") or entry.get("action") or "write_audit"),
                "status": "ok",
                "timestamp": None,
                "summary": _summarize_detail(detail),
                "detail": detail,
                "source_index": index,
            }
        )
    return events


def redact_value(value: Any, *, key: str = "") -> Any:
    if _is_sensitive_key(key):
        if value is None:
            return None
        normalized = key.lower().replace("-", "_")
        if "email" in normalized:
            return "[redacted-email]"
        if "phone" in normalized:
            return "[redacted-phone]"
        if "payment" in normalized:
            return "[redacted-payment]"
        if "zip" in normalized:
            return "[redacted-zip]"
        return f"[redacted-{key}]"
    plain = to_plain_data(value)
    if isinstance(plain, dict):
        return {str(item_key): redact_value(item, key=str(item_key)) for item_key, item in plain.items()}
    if isinstance(plain, list):
        return [redact_value(item, key=key) for item in plain]
    if isinstance(plain, str):
        text = EMAIL_RE.sub("[redacted-email]", plain)
        text = PHONE_RE.sub("[redacted-phone]", text)
        return text
    return plain


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEYS)


def _summarize_detail(detail: Any) -> str:
    if isinstance(detail, dict):
        for key in ("status", "decision", "tool_name", "block_reason", "error"):
            if detail.get(key):
                return str(detail[key])
    return ""
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
python3 -m unittest tests.test_workbench_snapshot -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/workbench/snapshot.py tests/test_workbench_snapshot.py
git commit -m "feat: add workbench snapshots"
```

---

### Task 4: Build Interactive Session Controller

**Files:**
- Create: `app/workbench/session.py`
- Test: `tests/test_workbench_session.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workbench_session.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from app.config import resolve_config
from app.workbench.session import WorkbenchSessionManager


class WorkbenchSessionTests(unittest.TestCase):
    def test_step_and_run_all_share_conversation_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(mode="deterministic", case_id="cancel_pending_order")

            first = session.step()
            self.assertEqual(first["script_cursor"], 1)
            self.assertEqual(first["business"]["confirmation_status"], "required")
            self.assertEqual(first["pending_action"]["action_name"], "cancel_pending_order")

            second = session.run_all()
            self.assertEqual(second["script_cursor"], 2)
            self.assertEqual(second["business"]["confirmation_status"], "confirmed")
            self.assertIn("order:#W5918442:cancel", second["business"]["write_locks"])
            self.assertTrue(Path(second["trace_artifact_path"]).exists())

    def test_manual_message_does_not_move_script_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(mode="deterministic", case_id="transfer_to_human")

            snapshot = session.send_message("My email is sofia.rossi2645@example.com. What is the status of order #W5918442?")

            self.assertEqual(snapshot["script_cursor"], 0)
            self.assertEqual(snapshot["business"]["current_intent"], "lookup")
            self.assertGreaterEqual(len(snapshot["messages"]), 2)

    def test_reset_recreates_runtime_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(mode="deterministic", case_id="cancel_pending_order")
            session.step()

            reset_snapshot = session.reset(case_id="return_delivered_order_item")

            self.assertEqual(reset_snapshot["selected_case_id"], "return_delivered_order_item")
            self.assertEqual(reset_snapshot["script_cursor"], 0)
            self.assertEqual(reset_snapshot["messages"], [])
            self.assertEqual(reset_snapshot["business"]["confirmation_status"], "not_required")

    def test_trace_artifact_updates_after_each_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(mode="deterministic", case_id="transfer_to_human")

            snapshot = session.step()
            trace = json.loads(Path(snapshot["trace_artifact_path"]).read_text(encoding="utf-8"))

            self.assertEqual(trace["run_id"], session.session_id)
            self.assertEqual(trace["final_state"]["current_intent"], "transfer")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_workbench_session -v
```

Expected: FAIL because `app.workbench.session` does not exist.

- [ ] **Step 3: Implement the session controller**

Create `app/workbench/session.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from app.agent.models import ConversationState
from app.agent.prompts import prompt_metadata
from app.agent.providers import DisabledLLMProvider
from app.agent.runtime import AgentRuntime
from app.config import AppConfig
from app.eval.cases import EvalCase
from app.ops.tracing import TraceWriter
from app.workbench.cases import get_case_by_id
from app.workbench.errors import WorkbenchAPIError
from app.workbench.snapshot import snapshot_from_state


@dataclass
class WorkbenchSession:
    config: AppConfig
    session_id: str
    mode: str
    selected_case: Optional[EvalCase] = None
    script_cursor: int = 0

    def __post_init__(self) -> None:
        self._create_runtime_and_state()
        self.last_error = None
        self.trace_artifact_path = ""
        self._write_trace()

    @property
    def llm_available(self) -> bool:
        return bool(self.config.deepseek_api_key)

    def reset(self, case_id: Optional[str] = None, mode: Optional[str] = None) -> Dict:
        if mode:
            self.mode = _validate_mode(mode, self.config)
        self.selected_case = get_case_by_id(case_id) if case_id else None
        self.script_cursor = 0
        self.last_error = None
        self._create_runtime_and_state()
        self._write_trace()
        return self.snapshot()

    def select_case(self, case_id: str) -> Dict:
        return self.reset(case_id=case_id)

    def step(self) -> Dict:
        case = self._require_case()
        if self.script_cursor >= len(case.messages):
            raise WorkbenchAPIError(
                code="script_complete",
                message="No scripted messages remain.",
                recoverable=True,
                details={"case_id": case.case_id, "script_cursor": self.script_cursor},
            )
        message = case.messages[self.script_cursor]
        self.script_cursor += 1
        self._send_user_content(message.get("content", ""))
        return self.snapshot()

    def run_all(self) -> Dict:
        case = self._require_case()
        while self.script_cursor < len(case.messages):
            message = case.messages[self.script_cursor]
            self.script_cursor += 1
            self._send_user_content(message.get("content", ""))
        return self.snapshot()

    def send_message(self, content: str) -> Dict:
        if not content.strip():
            raise WorkbenchAPIError(
                code="empty_message",
                message="Message content is required.",
                recoverable=True,
            )
        self._send_user_content(content.strip())
        return self.snapshot()

    def snapshot(self) -> Dict:
        return snapshot_from_state(
            session_id=self.session_id,
            mode=self.mode,
            llm_available=self.llm_available,
            state=self.state,
            initial_db_hash=self.initial_db_hash,
            current_db_hash=self.runtime.retail_runtime.db_hash(),
            trace_artifact_path=self.trace_artifact_path,
            selected_case_id=self.selected_case.case_id if self.selected_case else None,
            script_cursor=self.script_cursor,
            script_message_count=len(self.selected_case.messages) if self.selected_case else 0,
            last_error=self.last_error,
        )

    def _create_runtime_and_state(self) -> None:
        provider = DisabledLLMProvider() if self.mode == "deterministic" else None
        self.runtime = AgentRuntime(
            self.config,
            provider=provider,
            require_llm=self.mode == "llm",
        )
        self.state = ConversationState(
            session_id=self.session_id,
            task_id=self.selected_case.case_id if self.selected_case else None,
        )
        self.initial_db_hash = self.runtime.retail_runtime.db_hash()

    def _send_user_content(self, content: str) -> None:
        try:
            self.runtime.handle_user_message(self.state, content)
            self.last_error = None
        except Exception as exc:
            self.last_error = {
                "code": "runtime_error",
                "message": str(exc),
                "recoverable": True,
                "details": {"type": type(exc).__name__},
            }
            self.state.add_step("workbench_runtime", status="error", error=str(exc))
        finally:
            self._write_trace()

    def _write_trace(self) -> None:
        path = TraceWriter(self.config.run_artifact_dir).write(
            run_id=self.session_id,
            state=self.state,
            metadata={
                "runtime_source": self.runtime.retail_runtime.source,
                "model": self.config.default_agent_model,
                "mode": self.mode,
                "llm_enabled": self.runtime.provider is not None,
                "llm_available": self.llm_available,
                "initial_db_hash": self.initial_db_hash,
                "final_db_hash": self.runtime.retail_runtime.db_hash(),
                "tau2_bench_root": str(self.config.tau2_bench_root),
                "tau3_retail_root": str(self.config.tau3_retail_root),
                "retail_db_path": str(self.config.retail_db_path),
                "prompts": prompt_metadata(),
            },
        )
        self.trace_artifact_path = str(path)

    def _require_case(self) -> EvalCase:
        if self.selected_case is None:
            raise WorkbenchAPIError(
                code="case_required",
                message="Select a scripted case before using Step or Run all.",
                recoverable=True,
            )
        return self.selected_case


class WorkbenchSessionManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.sessions: Dict[str, WorkbenchSession] = {}

    def create_session(
        self,
        *,
        mode: str = "deterministic",
        case_id: Optional[str] = None,
    ) -> WorkbenchSession:
        validated_mode = _validate_mode(mode, self.config)
        session_id = "workbench-" + uuid.uuid4().hex[:12]
        session = WorkbenchSession(
            config=self.config,
            session_id=session_id,
            mode=validated_mode,
            selected_case=get_case_by_id(case_id) if case_id else None,
        )
        self.sessions[session_id] = session
        return session

    def get(self, session_id: str) -> WorkbenchSession:
        try:
            return self.sessions[session_id]
        except KeyError as exc:
            raise WorkbenchAPIError(
                code="session_not_found",
                message="Session was not found.",
                recoverable=True,
                details={"session_id": session_id},
                status_code=404,
            ) from exc


def _validate_mode(mode: str, config: AppConfig) -> str:
    if mode == "deterministic":
        return mode
    if mode == "llm" and config.deepseek_api_key:
        return mode
    if mode == "llm":
        raise WorkbenchAPIError(
            code="llm_unavailable",
            message="LLM mode requires DEEPSEEK_API_KEY.",
            recoverable=True,
            status_code=400,
        )
    raise WorkbenchAPIError(
        code="invalid_mode",
        message="Mode must be deterministic or llm.",
        recoverable=True,
        details={"mode": mode},
        status_code=400,
    )
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
python3 -m unittest tests.test_workbench_session -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/workbench/session.py tests/test_workbench_session.py
git commit -m "feat: add workbench sessions"
```

---

### Task 5: Add FastAPI Routes

**Files:**
- Create: `app/workbench/api.py`
- Test: `tests/test_workbench_api.py`
- Modify: `app/workbench/__init__.py`

- [ ] **Step 1: Write the failing API tests**

Create `tests/test_workbench_api.py`:

```python
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.config import resolve_config
from app.workbench.api import create_app


class WorkbenchAPITests(unittest.TestCase):
    def test_config_returns_cases_and_llm_availability(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.get("/api/workbench/config")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_mode"], "deterministic")
        self.assertFalse(payload["llm_available"])
        self.assertEqual(payload["case_catalog"]["subset"], "curated_mvp")
        self.assertGreaterEqual(len(payload["case_catalog"]["demo_cases"]), 5)

    def test_session_step_and_run_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)
            created = client.post(
                "/api/sessions",
                json={"mode": "deterministic", "case_id": "cancel_pending_order"},
            ).json()
            session_id = created["session_id"]

            first = client.post(f"/api/sessions/{session_id}/step").json()
            second = client.post(f"/api/sessions/{session_id}/run-all").json()

        self.assertEqual(first["script_cursor"], 1)
        self.assertEqual(second["script_cursor"], 2)
        self.assertEqual(second["business"]["confirmation_status"], "confirmed")

    def test_manual_message_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)
            session_id = client.post("/api/sessions", json={"mode": "deterministic"}).json()["session_id"]

            snapshot = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"content": "My email is sofia.rossi2645@example.com. What is the status of order #W5918442?"},
            ).json()

        self.assertEqual(snapshot["business"]["current_intent"], "lookup")
        self.assertEqual(snapshot["script_cursor"], 0)

    def test_errors_are_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.post("/api/sessions/missing/step")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "session_not_found")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_workbench_api -v
```

Expected: FAIL because `app.workbench.api` does not exist or FastAPI is not installed. If FastAPI is missing, run `uv sync` after Task 1 dependency changes.

- [ ] **Step 3: Implement the FastAPI app**

Create `app/workbench/api.py`:

```python
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import AppConfig, resolve_config
from app.workbench.cases import build_case_catalog
from app.workbench.errors import WorkbenchAPIError, error_payload
from app.workbench.session import WorkbenchSessionManager


class CreateSessionRequest(BaseModel):
    mode: str = "deterministic"
    case_id: Optional[str] = None


class SelectCaseRequest(BaseModel):
    case_id: str


class MessageRequest(BaseModel):
    content: str


class ResetRequest(BaseModel):
    case_id: Optional[str] = None
    mode: Optional[str] = None


def create_app(config: Optional[AppConfig] = None) -> FastAPI:
    resolved_config = config or resolve_config(artifact_dir="artifacts/phase4")
    manager = WorkbenchSessionManager(config=resolved_config)
    app = FastAPI(title="Retail Agent Workbench API")
    app.state.manager = manager
    app.state.config = resolved_config
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(WorkbenchAPIError)
    async def handle_workbench_error(
        request: Request, error: WorkbenchAPIError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=error_payload(error),
        )

    @app.get("/api/workbench/config")
    def get_config() -> Dict[str, Any]:
        return {
            "default_mode": "deterministic",
            "llm_available": bool(resolved_config.deepseek_api_key),
            "model": resolved_config.default_agent_model,
            "case_catalog": build_case_catalog(),
        }

    @app.post("/api/sessions")
    def create_session(request: CreateSessionRequest) -> Dict[str, Any]:
        session = manager.create_session(mode=request.mode, case_id=request.case_id)
        return session.snapshot()

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> Dict[str, Any]:
        return manager.get(session_id).snapshot()

    @app.post("/api/sessions/{session_id}/select-case")
    def select_case(session_id: str, request: SelectCaseRequest) -> Dict[str, Any]:
        return manager.get(session_id).select_case(request.case_id)

    @app.post("/api/sessions/{session_id}/step")
    def step(session_id: str) -> Dict[str, Any]:
        return manager.get(session_id).step()

    @app.post("/api/sessions/{session_id}/run-all")
    def run_all(session_id: str) -> Dict[str, Any]:
        return manager.get(session_id).run_all()

    @app.post("/api/sessions/{session_id}/messages")
    def send_message(session_id: str, request: MessageRequest) -> Dict[str, Any]:
        return manager.get(session_id).send_message(request.content)

    @app.post("/api/sessions/{session_id}/reset")
    def reset(session_id: str, request: ResetRequest) -> Dict[str, Any]:
        return manager.get(session_id).reset(case_id=request.case_id, mode=request.mode)

    return app
```

Modify `app/workbench/__init__.py`:

```python
from __future__ import annotations

from app.workbench.api import create_app

__all__ = ["create_app"]
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
python3 -m unittest tests.test_workbench_api -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/workbench/api.py app/workbench/__init__.py tests/test_workbench_api.py
git commit -m "feat: add workbench API"
```

---

### Task 6: Add Workbench CLI

**Files:**
- Create: `app/workbench/cli.py`
- Test: `tests/test_workbench_cli.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workbench_cli.py`:

```python
import unittest
from unittest.mock import patch

from app.workbench.cli import workbench_main


class WorkbenchCLITests(unittest.TestCase):
    def test_print_config_does_not_start_server(self):
        with patch("uvicorn.run") as run:
            exit_code = workbench_main(["--print-config"])

        self.assertEqual(exit_code, 0)
        run.assert_not_called()

    def test_invokes_uvicorn_with_host_and_port(self):
        with patch("uvicorn.run") as run:
            exit_code = workbench_main(["--host", "127.0.0.1", "--port", "8765"])

        self.assertEqual(exit_code, 0)
        run.assert_called_once()
        _, kwargs = run.call_args
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertEqual(kwargs["port"], 8765)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_workbench_cli -v
```

Expected: FAIL because `app.workbench.cli` does not exist.

- [ ] **Step 3: Implement the CLI**

Create `app/workbench/cli.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

import uvicorn

from app.config import resolve_config
from app.workbench.cases import build_case_catalog


def workbench_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Phase 4 local workbench API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--artifact-dir", default="artifacts/phase4")
    parser.add_argument("--tau3-retail-root")
    parser.add_argument("--tau2-bench-root")
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print workbench config JSON and exit.",
    )
    args = parser.parse_args(argv)

    config = resolve_config(
        tau3_retail_root=args.tau3_retail_root,
        tau2_bench_root=args.tau2_bench_root,
        artifact_dir=args.artifact_dir,
    )
    if args.print_config:
        print(
            json.dumps(
                {
                    "api_url": f"http://{args.host}:{args.port}",
                    "frontend_dev_url": "http://localhost:5173",
                    "llm_available": bool(config.deepseek_api_key),
                    "case_catalog": build_case_catalog(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print("Phase 4 workbench API starting", file=sys.stderr)
    print(f"API: http://{args.host}:{args.port}", file=sys.stderr)
    print("Frontend dev server: cd workbench && npm install && npm run dev", file=sys.stderr)
    print("Then open: http://localhost:5173", file=sys.stderr)
    uvicorn.run(
        "app.workbench.api:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(workbench_main())
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
python3 -m unittest tests.test_workbench_cli -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/workbench/cli.py tests/test_workbench_cli.py pyproject.toml
git commit -m "feat: add workbench CLI"
```

---

### Task 7: Scaffold Vite React Workbench

**Files:**
- Create: `workbench/package.json`
- Create: `workbench/index.html`
- Create: `workbench/tsconfig.json`
- Create: `workbench/tsconfig.node.json`
- Create: `workbench/vite.config.ts`
- Create: `workbench/src/main.tsx`
- Create: `workbench/src/types.ts`
- Create: `workbench/src/api.ts`
- Create: `workbench/src/styles.css`
- Create: `workbench/src/App.tsx`
- Modify: `.gitignore`

- [ ] **Step 1: Add frontend ignore rules**

Modify `.gitignore` so it contains:

```gitignore
node_modules/
dist/
build/
.next/
coverage/

workbench/node_modules/
workbench/dist/
```

- [ ] **Step 2: Create package and config files**

Create `workbench/package.json`:

```json
{
  "name": "retail-agent-workbench",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "tsc -b && vite build",
    "preview": "vite preview --host 127.0.0.1"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^5.0.0",
    "vite": "^7.0.0",
    "typescript": "^5.8.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "lucide-react": "^0.468.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0"
  }
}
```

Create `workbench/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Retail Agent Workbench</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `workbench/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2020"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create `workbench/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

Create `workbench/vite.config.ts`:

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
    },
  },
});
```

- [ ] **Step 3: Add TypeScript API types**

Create `workbench/src/types.ts`:

```typescript
export type WorkbenchMode = "deterministic" | "llm";

export interface WorkbenchCase {
  case_id: string;
  title: string;
  category: string;
  message_count: number;
  messages: Array<{ role: string; content: string }>;
  expected_intent: string;
  expected_order_status: string | null;
  expected_confirmation_status: string | null;
  expected_guard_block_reason: string | null;
  expected_no_write: boolean;
}

export interface CaseCatalog {
  subset: string;
  demo_case_ids: string[];
  demo_cases: WorkbenchCase[];
  all_cases: WorkbenchCase[];
}

export interface WorkbenchConfig {
  default_mode: WorkbenchMode;
  llm_available: boolean;
  model: string;
  case_catalog: CaseCatalog;
}

export interface TimelineEvent {
  id: string;
  kind: "message" | "step" | "tool_call" | "write_audit";
  label: string;
  status: string;
  timestamp: string | null;
  summary: string;
  detail: unknown;
  source_index: number;
}

export interface WorkbenchError {
  code: string;
  message: string;
  recoverable: boolean;
  details?: Record<string, unknown>;
}

export interface WorkbenchSnapshot {
  session_id: string;
  mode: WorkbenchMode;
  llm_available: boolean;
  selected_case_id: string | null;
  script_cursor: number;
  script_message_count: number;
  run_controls: {
    can_step: boolean;
    can_run_all: boolean;
    can_reset: boolean;
  };
  messages: Array<{ role: string; content: string; created_at?: string }>;
  business: {
    authenticated_user_id: string | null;
    auth_method: string | null;
    active_order_id: string | null;
    current_intent: string;
    slots: Record<string, unknown>;
    confirmation_status: string;
    db_changed: boolean;
    initial_db_hash: string;
    current_db_hash: string;
    write_locks: string[];
  };
  pending_action: null | {
    action_name: string;
    arguments: Record<string, unknown>;
    user_facing_summary: string;
  };
  policy_decision: unknown;
  tool_results: unknown[];
  timeline: TimelineEvent[];
  audit_logs: unknown[];
  guard_blocks: unknown[];
  trace_artifact_path: string;
  last_error: WorkbenchError | null;
}
```

Create `workbench/src/api.ts`:

```typescript
import type { WorkbenchConfig, WorkbenchMode, WorkbenchSnapshot } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  const payload = await response.json();
  if (!response.ok) {
    const message = payload?.error?.message || `Request failed: ${response.status}`;
    throw new Error(message);
  }
  return payload as T;
}

export function fetchConfig(): Promise<WorkbenchConfig> {
  return request<WorkbenchConfig>("/api/workbench/config");
}

export function createSession(mode: WorkbenchMode, caseId?: string): Promise<WorkbenchSnapshot> {
  return request<WorkbenchSnapshot>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ mode, case_id: caseId || null }),
  });
}

export function selectCase(sessionId: string, caseId: string): Promise<WorkbenchSnapshot> {
  return request<WorkbenchSnapshot>(`/api/sessions/${sessionId}/select-case`, {
    method: "POST",
    body: JSON.stringify({ case_id: caseId }),
  });
}

export function stepSession(sessionId: string): Promise<WorkbenchSnapshot> {
  return request<WorkbenchSnapshot>(`/api/sessions/${sessionId}/step`, { method: "POST" });
}

export function runAll(sessionId: string): Promise<WorkbenchSnapshot> {
  return request<WorkbenchSnapshot>(`/api/sessions/${sessionId}/run-all`, { method: "POST" });
}

export function sendMessage(sessionId: string, content: string): Promise<WorkbenchSnapshot> {
  return request<WorkbenchSnapshot>(`/api/sessions/${sessionId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function resetSession(sessionId: string, caseId?: string, mode?: WorkbenchMode): Promise<WorkbenchSnapshot> {
  return request<WorkbenchSnapshot>(`/api/sessions/${sessionId}/reset`, {
    method: "POST",
    body: JSON.stringify({ case_id: caseId || null, mode: mode || null }),
  });
}
```

- [ ] **Step 4: Add a minimal React shell**

Create `workbench/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

Create `workbench/src/App.tsx`:

```tsx
import { useEffect, useState } from "react";
import { createSession, fetchConfig } from "./api";
import type { WorkbenchConfig, WorkbenchSnapshot } from "./types";

export function App() {
  const [config, setConfig] = useState<WorkbenchConfig | null>(null);
  const [snapshot, setSnapshot] = useState<WorkbenchSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchConfig()
      .then(async (nextConfig) => {
        setConfig(nextConfig);
        const firstCase = nextConfig.case_catalog.demo_cases[0]?.case_id;
        setSnapshot(await createSession(nextConfig.default_mode, firstCase));
      })
      .catch((exc: Error) => setError(exc.message));
  }, []);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Retail Agent Workbench</h1>
          <p>Single-session Phase 4 operations dashboard</p>
        </div>
        <div className="mode-pill">{snapshot?.mode || config?.default_mode || "loading"}</div>
      </header>
      {error ? <div className="error-banner">{error}</div> : null}
      <section className="dashboard-grid">
        <aside className="panel">Run Control loads in Task 8</aside>
        <section className="panel">Business State loads in Task 8</section>
        <section className="panel">Conversation and Timeline load in Task 8</section>
      </section>
    </main>
  );
}
```

Create `workbench/src/styles.css`:

```css
:root {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f5f7fb;
  color: #172033;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

button,
input,
select,
textarea {
  font: inherit;
}

.app-shell {
  min-height: 100vh;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
  border-bottom: 1px solid #d9e1ec;
  background: #ffffff;
}

.topbar h1 {
  margin: 0;
  font-size: 20px;
  line-height: 1.2;
}

.topbar p {
  margin: 4px 0 0;
  color: #5c687a;
}

.mode-pill {
  border: 1px solid #bcc8d8;
  border-radius: 999px;
  padding: 6px 10px;
  background: #eef3f8;
  font-size: 13px;
  font-weight: 700;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 360px;
  gap: 12px;
  padding: 12px;
}

.panel {
  min-height: 180px;
  border: 1px solid #d9e1ec;
  border-radius: 8px;
  background: #ffffff;
  padding: 12px;
}

.error-banner {
  margin: 12px;
  border: 1px solid #f1b7b7;
  border-radius: 8px;
  background: #fff0f0;
  color: #8a1f1f;
  padding: 10px 12px;
}

@media (max-width: 1100px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 5: Install and build the frontend**

Run:

```bash
cd workbench && npm install && npm run build
```

Expected: `vite build` completes and writes `workbench/dist`.

- [ ] **Step 6: Commit**

```bash
git add .gitignore workbench
git commit -m "feat: scaffold React workbench"
```

---

### Task 8: Implement Dashboard Components

**Files:**
- Create: `workbench/src/components/StatusBadge.tsx`
- Create: `workbench/src/components/RunControl.tsx`
- Create: `workbench/src/components/BusinessState.tsx`
- Create: `workbench/src/components/Conversation.tsx`
- Create: `workbench/src/components/Timeline.tsx`
- Create: `workbench/src/components/Inspector.tsx`
- Modify: `workbench/src/App.tsx`
- Modify: `workbench/src/styles.css`

- [ ] **Step 1: Create shared status badge**

Create `workbench/src/components/StatusBadge.tsx`:

```tsx
export function StatusBadge({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "good" | "warn" | "bad" }) {
  return <span className={`status-badge status-${tone}`}>{label}</span>;
}
```

- [ ] **Step 2: Create Run Control component**

Create `workbench/src/components/RunControl.tsx`:

```tsx
import { Play, RotateCcw, Send, StepForward } from "lucide-react";
import { useState } from "react";
import type { CaseCatalog, WorkbenchMode, WorkbenchSnapshot } from "../types";
import { StatusBadge } from "./StatusBadge";

interface Props {
  catalog: CaseCatalog;
  snapshot: WorkbenchSnapshot;
  llmAvailable: boolean;
  busy: boolean;
  onSelectCase: (caseId: string) => void;
  onStep: () => void;
  onRunAll: () => void;
  onReset: () => void;
  onSendMessage: (content: string) => void;
  onModeChange: (mode: WorkbenchMode) => void;
}

export function RunControl(props: Props) {
  const [showAll, setShowAll] = useState(false);
  const [manualMessage, setManualMessage] = useState("");
  const cases = showAll ? props.catalog.all_cases : props.catalog.demo_cases;

  function submitManual() {
    const content = manualMessage.trim();
    if (!content) return;
    props.onSendMessage(content);
    setManualMessage("");
  }

  return (
    <aside className="panel run-control">
      <div className="panel-header">
        <h2>Run Control</h2>
        <StatusBadge label={props.snapshot.mode} tone={props.snapshot.mode === "llm" ? "warn" : "neutral"} />
      </div>
      <label className="field-label" htmlFor="mode">Mode</label>
      <select
        id="mode"
        value={props.snapshot.mode}
        onChange={(event) => props.onModeChange(event.target.value as WorkbenchMode)}
      >
        <option value="deterministic">Deterministic</option>
        {props.llmAvailable ? <option value="llm">LLM</option> : null}
      </select>
      <div className="segmented">
        <button className={!showAll ? "active" : ""} onClick={() => setShowAll(false)}>Demo</button>
        <button className={showAll ? "active" : ""} onClick={() => setShowAll(true)}>All</button>
      </div>
      <label className="field-label" htmlFor="case">Case</label>
      <select
        id="case"
        value={props.snapshot.selected_case_id || ""}
        onChange={(event) => props.onSelectCase(event.target.value)}
      >
        {cases.map((item) => (
          <option key={item.case_id} value={item.case_id}>
            {item.title}
          </option>
        ))}
      </select>
      <div className="button-row">
        <button onClick={props.onStep} disabled={props.busy || !props.snapshot.run_controls.can_step} title="Run next scripted user message">
          <StepForward size={16} /> Step
        </button>
        <button onClick={props.onRunAll} disabled={props.busy || !props.snapshot.run_controls.can_run_all} title="Run remaining scripted messages">
          <Play size={16} /> Run all
        </button>
        <button onClick={props.onReset} disabled={props.busy} title="Reset current session">
          <RotateCcw size={16} /> Reset
        </button>
      </div>
      <label className="field-label" htmlFor="manual">Manual message</label>
      <textarea
        id="manual"
        rows={5}
        value={manualMessage}
        onChange={(event) => setManualMessage(event.target.value)}
        placeholder="Type a user message for the active session"
      />
      <button className="send-button" onClick={submitManual} disabled={props.busy || !manualMessage.trim()}>
        <Send size={16} /> Send message
      </button>
    </aside>
  );
}
```

- [ ] **Step 3: Create Business State component**

Create `workbench/src/components/BusinessState.tsx`:

```tsx
import type { WorkbenchSnapshot } from "../types";
import { StatusBadge } from "./StatusBadge";

export function BusinessState({ snapshot, onConfirm, onDeny, onChange }: {
  snapshot: WorkbenchSnapshot;
  onConfirm: () => void;
  onDeny: () => void;
  onChange: () => void;
}) {
  const pending = snapshot.pending_action;
  return (
    <section className="panel business-state">
      <div className="panel-header">
        <h2>Business State</h2>
        <StatusBadge
          label={snapshot.business.confirmation_status}
          tone={snapshot.business.confirmation_status === "confirmed" ? "good" : snapshot.business.confirmation_status === "required" ? "warn" : "neutral"}
        />
      </div>
      <div className="facts-grid">
        <Fact label="User" value={snapshot.business.authenticated_user_id || "Unauthenticated"} />
        <Fact label="Order" value={snapshot.business.active_order_id || "None"} />
        <Fact label="Intent" value={snapshot.business.current_intent} />
        <Fact label="DB changed" value={snapshot.business.db_changed ? "Yes" : "No"} />
      </div>
      <h3>Slots</h3>
      <pre className="json-block">{JSON.stringify(snapshot.business.slots, null, 2)}</pre>
      {pending ? (
        <div className="pending-action">
          <div className="panel-header">
            <h3>Pending Action</h3>
            <StatusBadge label={pending.action_name} tone="warn" />
          </div>
          <p>{pending.user_facing_summary}</p>
          <pre className="json-block">{JSON.stringify(pending.arguments, null, 2)}</pre>
          <div className="button-row">
            <button onClick={onConfirm}>Confirm</button>
            <button onClick={onDeny}>Deny</button>
            <button onClick={onChange}>Change</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="fact">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
```

- [ ] **Step 4: Create Conversation, Timeline, and Inspector**

Create `workbench/src/components/Conversation.tsx`:

```tsx
import type { WorkbenchSnapshot } from "../types";

export function Conversation({ snapshot }: { snapshot: WorkbenchSnapshot }) {
  return (
    <section className="panel conversation-panel">
      <div className="panel-header">
        <h2>Conversation</h2>
        <span>{snapshot.messages.length} messages</span>
      </div>
      <div className="message-list">
        {snapshot.messages.map((message, index) => (
          <div key={`${message.role}-${index}`} className={`message message-${message.role}`}>
            <span>{message.role}</span>
            <p>{message.content}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
```

Create `workbench/src/components/Timeline.tsx`:

```tsx
import type { TimelineEvent } from "../types";
import { StatusBadge } from "./StatusBadge";

export function Timeline({
  events,
  selectedId,
  onSelect,
}: {
  events: TimelineEvent[];
  selectedId: string | null;
  onSelect: (event: TimelineEvent) => void;
}) {
  return (
    <section className="panel timeline-panel">
      <div className="panel-header">
        <h2>Timeline</h2>
        <span>{events.length} events</span>
      </div>
      <div className="timeline-list">
        {events.map((event) => (
          <button
            key={event.id}
            className={`timeline-row ${selectedId === event.id ? "selected" : ""}`}
            onClick={() => onSelect(event)}
          >
            <span className="timeline-kind">{event.kind}</span>
            <strong>{event.label}</strong>
            <StatusBadge label={event.status} tone={event.status === "success" || event.status === "ok" ? "good" : event.status === "blocked" ? "warn" : event.status === "error" ? "bad" : "neutral"} />
            <small>{event.summary}</small>
          </button>
        ))}
      </div>
    </section>
  );
}
```

Create `workbench/src/components/Inspector.tsx`:

```tsx
import type { TimelineEvent, WorkbenchSnapshot } from "../types";

export function Inspector({ snapshot, selected }: { snapshot: WorkbenchSnapshot; selected: TimelineEvent | null }) {
  return (
    <aside className="panel inspector-panel">
      <div className="panel-header">
        <h2>Inspector</h2>
        <span>{selected?.kind || "none"}</span>
      </div>
      {snapshot.last_error ? (
        <div className="error-banner compact">{snapshot.last_error.message}</div>
      ) : null}
      {selected ? (
        <>
          <h3>{selected.label}</h3>
          <pre className="json-block">{JSON.stringify(selected.detail, null, 2)}</pre>
        </>
      ) : (
        <p className="muted">Select a timeline event to inspect details.</p>
      )}
      <h3>Trace</h3>
      <p className="trace-path">{snapshot.trace_artifact_path}</p>
      <h3>Guard Blocks</h3>
      <pre className="json-block">{JSON.stringify(snapshot.guard_blocks, null, 2)}</pre>
    </aside>
  );
}
```

- [ ] **Step 5: Wire components in App**

Replace `workbench/src/App.tsx` with:

```tsx
import { useEffect, useMemo, useState } from "react";
import {
  createSession,
  fetchConfig,
  resetSession,
  runAll,
  selectCase,
  sendMessage,
  stepSession,
} from "./api";
import { BusinessState } from "./components/BusinessState";
import { Conversation } from "./components/Conversation";
import { Inspector } from "./components/Inspector";
import { RunControl } from "./components/RunControl";
import { Timeline } from "./components/Timeline";
import type { TimelineEvent, WorkbenchConfig, WorkbenchMode, WorkbenchSnapshot } from "./types";

export function App() {
  const [config, setConfig] = useState<WorkbenchConfig | null>(null);
  const [snapshot, setSnapshot] = useState<WorkbenchSnapshot | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<TimelineEvent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchConfig()
      .then(async (nextConfig) => {
        setConfig(nextConfig);
        const firstCase = nextConfig.case_catalog.demo_cases[0]?.case_id;
        setSnapshot(await createSession(nextConfig.default_mode, firstCase));
      })
      .catch((exc: Error) => setError(exc.message));
  }, []);

  useEffect(() => {
    if (snapshot && selectedEvent && !snapshot.timeline.some((event) => event.id === selectedEvent.id)) {
      setSelectedEvent(null);
    }
  }, [snapshot, selectedEvent]);

  const activeEvent = useMemo(() => {
    if (!snapshot) return null;
    return selectedEvent || snapshot.timeline[snapshot.timeline.length - 1] || null;
  }, [selectedEvent, snapshot]);

  async function mutate(action: () => Promise<WorkbenchSnapshot>) {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      setSnapshot(next);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  if (!config || !snapshot) {
    return <main className="app-shell loading">Loading workbench...</main>;
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Retail Agent Workbench</h1>
          <p>Single-session Phase 4 operations dashboard</p>
        </div>
        <div className="mode-pill">{snapshot.mode}</div>
      </header>
      {error ? <div className="error-banner">{error}</div> : null}
      <section className="dashboard-grid">
        <RunControl
          catalog={config.case_catalog}
          snapshot={snapshot}
          llmAvailable={config.llm_available}
          busy={busy}
          onSelectCase={(caseId) => mutate(() => selectCase(snapshot.session_id, caseId))}
          onStep={() => mutate(() => stepSession(snapshot.session_id))}
          onRunAll={() => mutate(() => runAll(snapshot.session_id))}
          onReset={() => mutate(() => resetSession(snapshot.session_id, snapshot.selected_case_id || undefined, snapshot.mode))}
          onSendMessage={(content) => mutate(() => sendMessage(snapshot.session_id, content))}
          onModeChange={(mode: WorkbenchMode) => mutate(() => resetSession(snapshot.session_id, snapshot.selected_case_id || undefined, mode))}
        />
        <div className="main-stack">
          <BusinessState
            snapshot={snapshot}
            onConfirm={() => mutate(() => sendMessage(snapshot.session_id, "yes"))}
            onDeny={() => mutate(() => sendMessage(snapshot.session_id, "no"))}
            onChange={() => mutate(() => sendMessage(snapshot.session_id, "change"))}
          />
          <div className="lower-grid">
            <Conversation snapshot={snapshot} />
            <Timeline
              events={snapshot.timeline}
              selectedId={activeEvent?.id || null}
              onSelect={setSelectedEvent}
            />
          </div>
        </div>
        <Inspector snapshot={snapshot} selected={activeEvent} />
      </section>
    </main>
  );
}
```

- [ ] **Step 6: Extend CSS for the full dashboard**

Append to `workbench/src/styles.css`:

```css
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.panel-header h2,
.panel-header h3 {
  margin: 0;
}

.field-label {
  display: block;
  margin: 12px 0 6px;
  color: #59687d;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

select,
textarea {
  width: 100%;
  border: 1px solid #cbd6e4;
  border-radius: 6px;
  background: #ffffff;
  color: #172033;
  padding: 8px;
}

button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid #c7d2e0;
  border-radius: 6px;
  background: #ffffff;
  color: #172033;
  padding: 8px 10px;
  cursor: pointer;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.segmented,
.button-row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.segmented button {
  flex: 1;
}

.segmented .active {
  background: #163b73;
  color: #ffffff;
  border-color: #163b73;
}

.send-button {
  width: 100%;
  margin-top: 8px;
  background: #163b73;
  border-color: #163b73;
  color: #ffffff;
}

.main-stack {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 12px;
  min-width: 0;
}

.lower-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.9fr);
  gap: 12px;
  min-width: 0;
}

.facts-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.fact {
  border: 1px solid #d9e1ec;
  border-radius: 6px;
  padding: 8px;
  min-width: 0;
}

.fact span {
  display: block;
  color: #657389;
  font-size: 12px;
  font-weight: 700;
}

.fact strong {
  display: block;
  overflow-wrap: anywhere;
  margin-top: 4px;
}

.pending-action {
  border: 1px solid #e3c16f;
  border-radius: 8px;
  background: #fff8e8;
  padding: 10px;
  margin-top: 12px;
}

.json-block {
  max-height: 220px;
  overflow: auto;
  border: 1px solid #d9e1ec;
  border-radius: 6px;
  background: #f8fafc;
  padding: 8px;
  font-size: 12px;
}

.message-list,
.timeline-list {
  display: grid;
  gap: 8px;
  max-height: 520px;
  overflow: auto;
}

.message {
  border: 1px solid #d9e1ec;
  border-radius: 8px;
  padding: 8px;
}

.message span {
  color: #657389;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.message p {
  margin: 4px 0 0;
}

.message-assistant {
  background: #f4f8ff;
}

.timeline-row {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr) auto;
  align-items: center;
  width: 100%;
  text-align: left;
}

.timeline-row small {
  grid-column: 1 / 4;
  color: #657389;
  overflow-wrap: anywhere;
}

.timeline-row.selected {
  border-color: #163b73;
  box-shadow: 0 0 0 1px #163b73 inset;
}

.timeline-kind {
  color: #657389;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.status-badge {
  border-radius: 999px;
  border: 1px solid #c7d2e0;
  padding: 3px 8px;
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
}

.status-good {
  color: #0c6b58;
  background: #e8f7f2;
  border-color: #9ed9c7;
}

.status-warn {
  color: #8a5a00;
  background: #fff4d6;
  border-color: #e2c36f;
}

.status-bad {
  color: #9f2424;
  background: #ffecec;
  border-color: #efb4b4;
}

.status-neutral {
  color: #304056;
  background: #eef3f8;
}

.trace-path,
.muted {
  color: #657389;
  overflow-wrap: anywhere;
}

.compact {
  margin: 0 0 10px;
}

.loading {
  display: grid;
  place-items: center;
  color: #657389;
}

@media (max-width: 1250px) {
  .lower-grid,
  .facts-grid {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 7: Build the frontend**

Run:

```bash
cd workbench && npm run build
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add workbench/src
git commit -m "feat: build workbench dashboard UI"
```

---

### Task 9: Integrate Documentation And End-To-End Verification

**Files:**
- Modify: `README.md`
- Test/verification only: no new production module required.

- [ ] **Step 1: Update README Phase 4 instructions**

Add this section after Phase 3 in `README.md`:

```markdown
## Phase 4：Hybrid Ops Workbench

Phase 4 adds a local single-session workbench for scripted and manual agent demos.
It shows run controls, business state, pending actions, conversation, timeline,
tool calls, guard blocks, and write audit details.

Start the Python API:

```bash
uv run phase4-workbench
```

In another terminal, start the React workbench:

```bash
cd workbench
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

The default mode is deterministic/offline and does not require API keys. If
`DEEPSEEK_API_KEY` is configured, the UI will also expose LLM mode.
```

- [ ] **Step 2: Run all Python tests**

Run:

```bash
python3 -m unittest discover -s tests
```

Expected: PASS with all existing and new tests.

- [ ] **Step 3: Run frontend build**

Run:

```bash
cd workbench && npm run build
```

Expected: PASS.

- [ ] **Step 4: Run API config smoke**

Run:

```bash
uv run phase4-workbench --print-config
```

Expected: JSON output includes `"default_mode": "deterministic"` or the printed config includes `llm_available` and a case catalog with demo cases.

- [ ] **Step 5: Browser smoke**

Start backend:

```bash
uv run phase4-workbench
```

Start frontend in another terminal:

```bash
cd workbench && npm run dev
```

Open `http://localhost:5173` and verify:

- Demo case selector displays the shortlist.
- Step on `cancel_pending_order` creates a pending action.
- Confirm button completes the cancellation and shows a write lock.
- Run all works after Reset.
- Manual message updates the conversation without advancing script cursor.
- Timeline rows are selectable and details appear in Inspector.

- [ ] **Step 6: Commit docs and final integration**

```bash
git add README.md
git commit -m "docs: document phase4 workbench"
```

---

## Self-Review Checklist

- Spec coverage:
  - Backend API routes are covered in Tasks 4 and 5.
  - In-memory sessions and trace artifacts are covered in Task 4.
  - Demo shortlist and full curated cases are covered in Task 2.
  - Deterministic default and optional LLM mode are covered in Tasks 4, 5, and 8.
  - REST snapshots and future event-shaped timeline are covered in Task 3.
  - React Ops dashboard is covered in Tasks 7 and 8.
  - Error payloads are covered in Tasks 1 and 5.
  - README and verification are covered in Task 9.
- Placeholder scan:
  - No forbidden placeholder markers or undefined future implementation markers are intentionally left in the plan.
- Type consistency:
  - Backend uses `case_id`, `selected_case_id`, `script_cursor`, `script_message_count`, and `llm_available` consistently.
  - Frontend types mirror the snapshot keys from `app/workbench/snapshot.py`.
  - Routes in frontend API client match routes in `app/workbench/api.py`.
