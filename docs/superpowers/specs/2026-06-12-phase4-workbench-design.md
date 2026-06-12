# Phase 4 Hybrid Ops Workbench Design

Date: 2026-06-12

## Context

Phase 0 validated the local retail benchmark data. Phase 1 added a guarded
workflow runtime with confirmation and trace artifacts. Phase 2 added curated
eval runs and stable report artifacts. Phase 3 added a static trace and eval
dashboard.

Phase 4 will turn the project from a CLI/static-dashboard demo into a local,
interactive workbench. The workbench should show both business outcomes and the
agent workflow that produced them.

## Decision Summary

Build a single-session Hybrid Ops Workbench:

- Python API wrapping the existing `AgentRuntime`.
- Vite + React frontend with an operations dashboard layout.
- In-memory session state plus existing trace artifacts.
- Scripted demo cases with Step and Run all controls.
- Simple manual chat against the same session.
- Deterministic/offline mode by default, optional LLM mode when configured.
- REST request/response snapshots, with timeline data shaped like future events.

This phase does not build login, multi-user sessions, persistent run history,
SQLite storage, WebSocket streaming, remote deployment, or a full SaaS shell.

## Product Scope

The workbench is a local demo app. It should open into an operations dashboard,
not a marketing page or a generic chatbot.

The first version includes:

- A demo-friendly shortlist of cases, with a toggle for all `curated_mvp` cases.
- Step execution for scripted cases.
- Run all execution for scripted cases.
- Simple manual message input for the active single session.
- Deterministic/offline execution without API keys.
- Optional LLM mode when provider configuration is available.
- Always-visible business state and diagnostic state.

The default demo shortlist should include at least:

- Cancel pending order.
- Return delivered order item.
- Wrong-user guard block.
- Transfer to human.
- Denied confirmation / no-write flow.

## UX Structure

Use an operations dashboard layout.

Primary regions:

- Run Control: mode badge, case source toggle, case selector, Step, Run all,
  Reset, and manual input.
- Business State: authenticated user, active order, current intent, slots,
  confirmation status, pending action, and DB change summary.
- Pending Action Panel: visible and prominent when a write action is awaiting
  confirmation. Confirm, deny, and change actions send standard user messages to
  the runtime.
- Conversation: user and assistant messages for the active session.
- Timeline: node steps, tool calls, policy checks, guard blocks, and audit
  entries in chronological order.
- Tool/Audit Inspector: details for a selected timeline item, including
  arguments, normalized arguments when available, status, error/block reason,
  before/after DB hashes, idempotency key, and resource lock.

The visual style should be quiet, dense, and work-focused: compact grids,
tables, status badges, restrained color, and clear hierarchy. Avoid a landing
page, large hero sections, and decorative card-heavy composition.

## Backend Architecture

Add a workbench package, likely `app/workbench/`, containing:

- API app factory and route handlers.
- Session manager.
- Session controller.
- Snapshot builder.
- Case catalog helper.
- Error response helpers.

The API should expose:

- `GET /api/workbench/config`
  - Returns available cases, demo shortlist, default mode, and LLM availability.
- `POST /api/sessions`
  - Creates a session in deterministic or LLM mode, optionally bound to a case.
- `POST /api/sessions/{id}/select-case`
  - Selects a scripted case and resets that session.
- `POST /api/sessions/{id}/step`
  - Sends the next scripted user message and returns a snapshot.
- `POST /api/sessions/{id}/run-all`
  - Sends all remaining scripted user messages and returns a snapshot.
- `POST /api/sessions/{id}/messages`
  - Sends one manual user message and returns a snapshot.
- `POST /api/sessions/{id}/reset`
  - Resets the active session.
- `GET /api/sessions/{id}`
  - Returns the current snapshot.

The API can return complete session snapshots after every mutation. No streaming
is required in Phase 4.

## Runtime Behavior

Each workbench session owns:

- A fresh `AgentRuntime`.
- A single `ConversationState`.
- Initial DB hash.
- Current DB hash.
- Optional selected scripted case.
- Script cursor.
- Execution mode.
- Trace artifact path or trace metadata.

Scripted Step and Run all must feed `EvalCase.messages` into the same runtime
path used by manual chat. They should not bypass the guarded workflow.

The current `run_script()` behavior creates state internally and writes trace at
the end. Phase 4 should introduce a reusable controller for interactive use:

- Create session and initialize state.
- Send one user message through `runtime.handle_user_message(state, content)`.
- Build a snapshot from state and runtime DB.
- Write or update a trace artifact after each operation, so the UI always has a
  trace path.

Manual messages do not alter the scripted cursor unless the API call is a
scripted Step or Run all.

## Snapshot Contract

The frontend should treat the session snapshot as its source of truth.

The snapshot should include:

- Session id.
- Mode and LLM availability.
- Selected case id and script cursor.
- Available next actions.
- Messages.
- Business summary.
- Pending action.
- Current intent and slots.
- Policy decision.
- Confirmation status.
- Tool results.
- Timeline events.
- Audit logs.
- Guard blocks.
- Initial and current DB hashes.
- Trace artifact path.
- Structured errors when an operation fails.

Timeline events should use a stable shape:

- `id`
- `kind`
- `label`
- `status`
- `timestamp` when available
- `summary`
- `detail`
- `source_index`

This keeps Phase 4 REST-based while preserving a clean path to future
WebSocket/event streaming.

## Error Handling

Errors should be visible and recoverable when possible.

API errors return:

- `code`
- `message`
- `recoverable`
- `details`

Frontend behavior:

- Do not white-screen on case, message, LLM, tool, or guard failures.
- Show recoverable errors as banners or timeline events.
- Display guard blocks as controlled policy outcomes, not system failures.
- Keep pending actions visible when confirmation is unknown.
- Allow reset after unrecoverable session errors.

Deterministic mode must always be available. LLM mode appears only when provider
configuration is present. Provider JSON errors should be represented in the
timeline and should not crash the workbench.

## Security And Privacy Display

Continue the Phase 3 principle of redacting sensitive data where the UI does not
need raw values. This includes email, phone, address, zip, payment, and payment
method fields.

Workbench panels should still show enough structure for debugging, such as field
names, action names, order ids, status values, hash changes, guard reasons, and
resource locks.

## Runtime Fixes In Scope

Only fix runtime issues that directly affect Workbench usability and stability.
Examples:

- Confirmation button inputs map reliably to runtime confirmation intent.
- Pending action snapshots are explicit and stable.
- Provider JSON/API failures become timeline-visible errors.
- API-facing errors are normalized.
- Guard block snapshots include useful reason, tool, args, and DB hash data.

Broader CR items such as full prompt redesign, all intent edge cases, persistent
storage, and global guard refactors are out of scope unless they block the
Workbench.

## Testing Strategy

Backend tests should cover:

- Workbench config and case catalog.
- Session creation.
- Case selection and reset.
- Step execution.
- Run all execution.
- Manual message execution.
- Snapshot schema and key fields.
- Pending action confirmation.
- Guard block display data.
- LLM unavailable mode handling.

Runtime-adjacent tests should cover:

- Step and Run all produce equivalent final state for the same scripted case.
- The same `ConversationState` is reused across a session.
- Trace artifacts are generated or updated during interactive operation.
- Manual messages do not accidentally move the scripted cursor.

Frontend verification should cover:

- Build succeeds.
- Workbench opens locally.
- Demo shortlist and full curated toggle work.
- Step and Run all update the UI.
- Manual message updates conversation and timeline.
- Pending action panel appears and handles confirm/deny/change.
- Timeline, tool, audit, and business panels remain readable without overlap.

## Acceptance Criteria

Phase 4 is complete when:

- A local command such as `uv run phase4-workbench` starts the backend and gives
  clear instructions for opening the React workbench.
- The frontend can run in development mode against the local API.
- Default deterministic mode works without provider API keys.
- The demo shortlist runs successfully through Step and Run all.
- Manual chat works in the active single session.
- Cancel, return, wrong-user guard, transfer, and denied confirmation cases are
  understandable from the UI.
- Business state and diagnostic trace/audit state are both visible.
- Existing Python tests continue to pass.
- New backend tests pass.
- Frontend build or smoke verification passes.

## Explicit Non-Goals

- Multi-user or multi-session production UX.
- Authentication.
- Persistent run history.
- SQLite schema or migrations.
- WebSocket/token streaming.
- Cloud deployment.
- Full CR backlog remediation.
- Replacing the Phase 3 static dashboard.
