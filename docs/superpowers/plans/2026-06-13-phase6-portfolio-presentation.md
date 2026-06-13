# Phase 6: Portfolio-Grade Presentation Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有系统包装为清晰、有据、可演示的 AI Agent 工程作品集，让面试官在 3-5 分钟内理解项目价值。

**Architecture:** 四个独立工作领域 — Ruff 机械修复、Workbench 前端打磨（case 分组 + timeline 信息层级 + pending action 突出）、文档重写（README + portfolio-architecture.md）、Demo 截图。

**Tech Stack:** Python (FastAPI + Pydantic), TypeScript (React), CSS

---

### Task 1: Ruff 全量修复

**Files:**
- 自动修复 ~47 个文件（12 lint + 35 format）

- [ ] **Step 1: 运行 ruff check --fix 修复 import 排序**

```bash
uv run ruff check --fix .
```

Expected: 12 个 I001 错误被自动修复，零新错误。

- [ ] **Step 2: 运行 ruff format 格式化全部文件**

```bash
uv run ruff format .
```

Expected: 35 files reformatted, 22 files already formatted（或类似输出）。

- [ ] **Step 3: 验证两条命令均为零输出**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: 两条命令均无输出（即无错误、无待格式化文件）。

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "chore: ruff check --fix + ruff format 全量修复"
```

---

### Task 2: Workbench Backend — 案例分组与排序

**Files:**
- Modify: `app/workbench/cases.py`

- [ ] **Step 1: 新增 CASE_GROUPS 并重排 DEMO_CASE_IDS**

在 `CASE_TITLES` 字典后面添加 `CASE_GROUPS`，同时按用户旅程叙事重排 `DEMO_CASE_IDS`。

将文件中的：

```python
DEMO_CASE_IDS = [
    "cancel_pending_order",
    "return_delivered_order_item",
    "block_wrong_user_order_access",
    "transfer_to_human",
    "deny_cancel_confirmation",
    "auth_name_zip_lookup_order",
    "modify_pending_order_items_success",
    "modify_pending_order_payment_success",
    "block_item_product_mismatch",
    "block_payment_insufficient_gift_card",
]
```

替换为：

```python
DEMO_CASE_IDS = [
    "auth_name_zip_lookup_order",
    "cancel_pending_order",
    "return_delivered_order_item",
    "modify_pending_order_items_success",
    "modify_pending_order_payment_success",
    "block_wrong_user_order_access",
    "block_item_product_mismatch",
    "block_payment_insufficient_gift_card",
    "deny_cancel_confirmation",
    "transfer_to_human",
]

CASE_GROUPS = [
    {
        "key": "auth",
        "label": "身份认证",
        "emoji": "🔐",
        "case_ids": ["auth_name_zip_lookup_order"],
    },
    {
        "key": "success",
        "label": "成功写操作",
        "emoji": "✅",
        "case_ids": [
            "cancel_pending_order",
            "return_delivered_order_item",
            "modify_pending_order_items_success",
            "modify_pending_order_payment_success",
        ],
    },
    {
        "key": "blocked",
        "label": "写保护阻止",
        "emoji": "🛡️",
        "case_ids": [
            "block_wrong_user_order_access",
            "block_item_product_mismatch",
            "block_payment_insufficient_gift_card",
        ],
    },
    {
        "key": "confirmation",
        "label": "用户确认流程",
        "emoji": "🔄",
        "case_ids": ["deny_cancel_confirmation"],
    },
    {
        "key": "transfer",
        "label": "边界能力",
        "emoji": "📞",
        "case_ids": ["transfer_to_human"],
    },
]
```

- [ ] **Step 2: 更新 build_case_catalog 返回值，包含 groups**

在 `build_case_catalog` 函数的 `return` 字典中添加 `"groups"` 键：

```python
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
        "groups": CASE_GROUPS,
    }
```

- [ ] **Step 3: 验证后端 API 返回 groups 数据**

```bash
uv run phase4-workbench &
sleep 2
curl -s http://localhost:8000/api/workbench/config | python3 -m json.tool | grep -A5 groups
```

Expected: 输出包含 `groups` 数组，有 5 个分组，每组有 key/label/emoji/case_ids。

```bash
kill %1 2>/dev/null
```

- [ ] **Step 4: 提交**

```bash
git add app/workbench/cases.py
git commit -m "feat: workbench案例按用户旅程分组，新增CASE_GROUPS"
```

---

### Task 3: Workbench Backend — Timeline 事件权重

**Files:**
- Modify: `app/workbench/snapshot.py`

- [ ] **Step 1: _timeline_event 添加 weight 参数**

在 `_timeline_event` 函数签名中添加 `weight` 参数，并将其包含在返回字典中：

```python
def _timeline_event(
    *,
    event_id: str,
    kind: str,
    label: str,
    status: Optional[str],
    timestamp: Optional[str],
    summary: Optional[str],
    detail: Any,
    source_index: int,
    weight: str = "secondary",
) -> Dict[str, Any]:
    return {
        "id": event_id,
        "kind": kind,
        "label": label,
        "status": status,
        "timestamp": timestamp,
        "summary": summary,
        "detail": detail,
        "source_index": source_index,
        "weight": weight,
    }
```

- [ ] **Step 2: build_timeline 中计算每个事件的权重**

在 `build_timeline` 函数中，为以下事件类型传 `weight="primary"`：

- `kind == "tool_call"` → primary
- `kind == "write_audit"` → primary
- `kind == "step"` 且 `step.node` 在 `{"intent_and_slot_extractor", "policy_reasoner", "write_action_guard"}` 中 → primary
- 其余事件保持默认 `weight="secondary"`

修改 `build_timeline` 中创建 step timeline event 的部分，计算 `_step_weight(step.node)`：

在 `build_timeline` 函数之前添加辅助函数：

```python
_PRIMARY_STEPS = {"intent_and_slot_extractor", "policy_reasoner", "write_action_guard"}


def _step_weight(node: str) -> str:
    return "primary" if node in _PRIMARY_STEPS else "secondary"
```

然后修改 `build_timeline` 中两处调用 `_timeline_event` 创建 step 事件的地方，添加 `weight=_step_weight(step.node)`：

第一处（step 事件，约 line 107）：
```python
            (
                (turn_index, 20 + index, index),
                _timeline_event(
                    event_id=f"step-{index}",
                    kind="step",
                    label=step.node,
                    status=step.status,
                    timestamp=None,
                    summary=_summarize_detail(detail),
                    detail=detail,
                    source_index=index,
                    weight=_step_weight(step.node),
                ),
            )
```

对于 tool_call 事件的 `_tool_timeline_event`，也需要传入 `weight="primary"`。修改 `_tool_timeline_event`：

```python
def _tool_timeline_event(record: Any, index: int) -> Dict[str, Any]:
    detail = redact_value(to_plain_data(record))
    return _timeline_event(
        event_id=f"tool_call-{index}",
        kind="tool_call",
        label=record.tool_name,
        status=record.status,
        timestamp=None,
        summary=_summarize_detail(detail.get("error"))
        or _summarize_detail(detail.get("observation")),
        detail=detail,
        source_index=index,
        weight="primary",
    )
```

对于 write_audit 事件（约 line 153），添加 `weight="primary"`：

```python
                _timeline_event(
                    event_id=f"write_audit-{index}",
                    kind="write_audit",
                    label=...,
                    status=...,
                    timestamp=...,
                    summary=...,
                    detail=detail,
                    source_index=index,
                    weight="primary",
                ),
```

- [ ] **Step 3: 验证 API 返回 timeline 包含 weight 字段**

```bash
uv run phase4-workbench &
sleep 2
# 创建 session 并 step 到有事件
curl -s -X POST http://localhost:8000/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"mode":"deterministic","case_id":"cancel_pending_order"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(e['id'],e.get('weight','MISSING')) for e in d['timeline']]"
```

Expected: timeline 事件中 message 类为 `secondary`，intent_and_slot_extractor / policy_reasoner / write_action_guard / tool_call / write_audit 类为 `primary`。

```bash
kill %1 2>/dev/null
```

- [ ] **Step 4: 提交**

```bash
git add app/workbench/snapshot.py
git commit -m "feat: timeline事件添加weight字段区分主次信息层级"
```

---

### Task 4: Workbench Frontend — Types 扩展

**Files:**
- Modify: `workbench/src/types.ts`

- [ ] **Step 1: 添加 CaseGroup 接口，更新 CaseCatalog 和 TimelineEvent**

在 `types.ts` 中，在 `WorkbenchCase` 接口之后添加：

```typescript
export interface CaseGroup {
  key: string;
  label: string;
  emoji: string;
  case_ids: string[];
}
```

在 `CaseCatalog` 接口中添加 `groups` 字段：

```typescript
export interface CaseCatalog {
  subset: string;
  demo_case_ids: string[];
  demo_cases: WorkbenchCase[];
  all_cases: WorkbenchCase[];
  groups: CaseGroup[];
}
```

在 `TimelineEvent` 接口中添加 `weight` 字段：

```typescript
export interface TimelineEvent {
  id: string;
  kind: "message" | "step" | "tool_call" | "write_audit";
  label: string;
  status: string | null;
  timestamp: string | null;
  summary: string | null;
  detail: unknown;
  source_index: number;
  weight: "primary" | "secondary";
}
```

- [ ] **Step 2: 验证 TypeScript 编译**

```bash
cd workbench && npx tsc --noEmit
```

Expected: 零错误（可能会有因未修改的组件暂时不匹配的 warning — 这些在后续任务中解决）。

- [ ] **Step 3: 提交**

```bash
cd workbench && git add src/types.ts && git commit -m "feat: types添加CaseGroup、TimelineEvent.weight字段"
```

---

### Task 5: Workbench Frontend — Labels 扩展

**Files:**
- Modify: `workbench/src/labels.ts`

- [ ] **Step 1: 添加分组相关标签和权重状态标签**

在 `labels.ts` 末尾添加 `groupLabel` 导出函数：

```typescript
const GROUP_LABELS: Record<string, string> = {
  auth: "身份认证",
  success: "成功写操作",
  blocked: "写保护阻止",
  confirmation: "用户确认流程",
  transfer: "边界能力",
};

export function groupLabel(key: string): string {
  return GROUP_LABELS[key] || key;
}
```

添加 `weightLabel` 导出函数：

```typescript
export function weightLabel(weight: "primary" | "secondary"): string {
  return weight === "primary" ? "关键" : "辅助";
}
```

- [ ] **Step 2: 验证编译**

```bash
cd workbench && npx tsc --noEmit
```

Expected: 零新增错误。

- [ ] **Step 3: 提交**

```bash
cd workbench && git add src/labels.ts && git commit -m "feat: labels添加分组成员和权重标签函数"
```

---

### Task 6: Workbench Frontend — 分组 Case Selector

**Files:**
- Modify: `workbench/src/components/RunControl.tsx`

- [ ] **Step 1: 重写 case selector 为 optgroup 分组结构**

将 `RunControl.tsx` 中的 `<select>` 选项列表从扁平 `<option>` 列表改为 `<optgroup>` 分组。

当前代码（约 line 126-139）：
```tsx
        <select
          disabled={busy || !hasAnyCaseOption}
          onChange={(event) => onSelectCase(event.target.value)}
          value={selectedCaseId}
        >
          {selectedCaseId && !hasSelectedCaseOption ? (
            <option value={selectedCaseId}>{selectedCaseId}</option>
          ) : null}
          {caseOptions.map((workbenchCase) => (
            <option key={workbenchCase.case_id} value={workbenchCase.case_id}>
              {workbenchCase.title}
            </option>
          ))}
        </select>
```

替换为：

```tsx
        <select
          disabled={busy || !hasAnyCaseOption}
          onChange={(event) => onSelectCase(event.target.value)}
          value={selectedCaseId}
        >
          {selectedCaseId && !hasSelectedCaseOption ? (
            <option value={selectedCaseId}>{selectedCaseId}</option>
          ) : null}
          {showAll
            ? caseOptions.map((workbenchCase) => (
                <option key={workbenchCase.case_id} value={workbenchCase.case_id}>
                  {workbenchCase.title}
                </option>
              ))
            : catalog.groups.map((group) => (
                <optgroup key={group.key} label={`${group.emoji} ${group.label}`}>
                  {group.case_ids.map((caseId) => {
                    const workbenchCase = caseOptions.find(
                      (c) => c.case_id === caseId,
                    );
                    if (!workbenchCase) {
                      return null;
                    }
                    return (
                      <option key={caseId} value={caseId}>
                        {workbenchCase.title}
                      </option>
                    );
                  })}
                </optgroup>
              ))}
        </select>
```

**说明**: "演示" 模式使用 optgroup 分组，"全部" 模式保持扁平列表。

- [ ] **Step 2: 验证编译**

```bash
cd workbench && npx tsc --noEmit
```

Expected: 零类型错误。

- [ ] **Step 3: 提交**

```bash
cd workbench && git add src/components/RunControl.tsx && git commit -m "feat: 演示模式case selector按叙事分组optgroup"
```

---

### Task 7: Workbench Frontend — Timeline 信息层级

**Files:**
- Modify: `workbench/src/components/Timeline.tsx`

- [ ] **Step 1: 次要事件视觉降级，关键事件保持醒目**

修改 timeline 行的 CSS 类名以反映权重：

将约 line 33 的：
```tsx
                  className={isSelected ? "timeline-row selected" : "timeline-row"}
```

替换为：
```tsx
                  className={
                    "timeline-row" +
                    (isSelected ? " selected" : "") +
                    (event.weight === "secondary" ? " weight-secondary" : "")
                  }
```

同时在次要事件的 `timeline-summary` 中对于普通 pipeline step（kind 为 step 且 weight 为 secondary 且有多个同类事件）显示一个简短的步骤计数，可以在 summary 已经存在的情况下使用。

- [ ] **Step 2: 验证编译**

```bash
cd workbench && npx tsc --noEmit
```

Expected: 零错误。

- [ ] **Step 3: 提交**

```bash
cd workbench && git add src/components/Timeline.tsx && git commit -m "feat: timeline次要事件视觉降级，关键事件保持醒目"
```

---

### Task 8: Workbench Frontend — Pending Action 突出

**Files:**
- Modify: `workbench/src/components/BusinessState.tsx`

- [ ] **Step 1: 增强 pending action 区块，添加更醒目的待确认指示**

在 `pendingAction` 存在时，已有的渲染在 `<section className="pending-action">` 中（约 line 57-79）。在其 `<h3>` 前添加一个醒目的操作提示条：

```tsx
      {pendingAction ? (
        <section className="pending-action" aria-label="待确认操作">
          <div className="pending-action-banner">
            <span className="pending-action-icon">⏳</span>
            <span className="pending-action-prompt">需要用户确认才能执行</span>
          </div>
          <div className="section-label">待确认操作</div>
          <h3>{actionLabel(pendingAction.action_name)}</h3>
          <p>{pendingAction.user_facing_summary}</p>
          <pre>{formatJson(pendingAction.arguments)}</pre>
          <div className="control-row compact">
            <button
              className="button button-primary"
              disabled={busy}
              onClick={onConfirm}
              type="button"
            >
              确认
            </button>
            <button className="button" disabled={busy} onClick={onDeny} type="button">
              拒绝
            </button>
            <button className="button" disabled={busy} onClick={onChange} type="button">
              修改
            </button>
          </div>
        </section>
```

- [ ] **Step 2: 验证编译**

```bash
cd workbench && npx tsc --noEmit
```

Expected: 零错误。

- [ ] **Step 3: 提交**

```bash
cd workbench && git add src/components/BusinessState.tsx && git commit -m "feat: pending action区块添加醒目操作提示条"
```

---

### Task 9: Workbench Frontend — 样式

**Files:**
- Modify: `workbench/src/styles.css`

- [ ] **Step 1: 添加新样式**

在 CSS 文件末尾（约 line 637 之前）添加以下新样式：

```css
/* Timeline weight hierarchy */
.timeline-row.weight-secondary {
  opacity: 0.62;
  border-left: 3px solid transparent;
}

.timeline-row:not(.weight-secondary) {
  border-left: 3px solid #2563eb;
}

.timeline-row.selected:not(.weight-secondary) {
  border-left: 3px solid #1d4ed8;
}

.timeline-row.weight-secondary .timeline-title {
  font-weight: 600;
}

.timeline-row:not(.weight-secondary) .timeline-title {
  font-weight: 800;
}

/* Pending action banner */
.pending-action-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: -12px -12px 10px -12px;
  border-radius: 8px 8px 0 0;
  background: #f59e0b;
  color: #ffffff;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 800;
}

.pending-action-icon {
  font-size: 16px;
}

.pending-action-prompt {
  letter-spacing: 0.02em;
}

/* Override pending-action border when banner is present */
.pending-action {
  border-color: #f59e0b;
}

/* optgroup labels in case selector */
select optgroup {
  font-weight: 800;
  color: #667085;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
```

- [ ] **Step 2: 验证 Workbench 构建**

```bash
cd workbench && npm run build
```

Expected: 构建成功，无错误。

- [ ] **Step 3: 提交**

```bash
cd workbench && git add src/styles.css && git commit -m "feat: timeline权重样式、pending action醒目横幅、optgroup标签样式"
```

---

### Task 10: README.md 重写

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 重写 README 为作品集叙事结构**

完整替换 README.md 内容（当前约 204 行），新结构 8 段 ~200 行。内容如下：

```markdown
# Retail Customer Support Agent

A 12-node LLM agent for retail customer support with a 7-layer write safety guard and dual-track deterministic + semantic reasoning. Built on tau2-bench retail data, designed to be a portfolio piece demonstrating AI agent engineering — safe writes, intent disambiguation, and full auditability.

> **Demo screenshot:** [Workbench overview showing timeline, guard block, and write audit](docs/demo-screenshots/workbench-overview.png)

## Problem Statement

Retail customer support agents face three hard challenges:

1. **Safe write operations** — cancelling orders, modifying payments, returning items must not happen accidentally or without authorization. Every write needs explicit confirmation and multi-layer guard checks.
2. **Intent disambiguation** — "I want to change my order" could mean cancel, modify items, modify address, or modify payment. The agent must extract structured intent from unstructured natural language.
3. **Full auditability** — every decision, tool call, and DB mutation must be traceable to a specific policy rule, with before/after hashes and idempotency keys.

This project addresses all three with a deterministic-first, LLM-augmented architecture.

## Architecture Overview

```
receive_message → conversation_gate → identity_resolver → intent_and_slot_extractor
→ context_loader → policy_reasoner → action_planner → write_action_guard
→ tool_executor → observation_reducer → response_generator → run_logger
```

**Dual-track decision**: Every decision node runs two tracks in parallel — a code track (regex-based, always active) and an LLM track (semantic, opt-in). Merge rule: **deny wins**. The code track is the correctness anchor; LLM fills semantic gaps but never overrides code-extracted structured data.

**7-layer write guard**: Authentication → Confirmation → Ownership → Read-before-write → Policy → Resource Locks → Idempotency. Every write tool call passes through all seven layers before execution.

## Key Design Decisions

- **Deny wins merge** — Any track that says deny produces deny. Both must say allow for allow. This ensures the deterministic code track acts as a safety floor.
- **Code track as anchor** — LLM decisions that contradict code decisions are overridden. LLM fills semantic gaps (extracting `reason` from natural language) but doesn't override code-extracted order IDs or item IDs.
- **Single source of truth for write actions** — `app/agent/action_specs.py` defines all 7 write operations. Guards, prompts, tool registry, and runtime all derive from this one file.

## Quick Start

```bash
# 1. Install dependencies
uv sync --extra dev

# 2. Start Workbench demo (deterministic mode, no API key needed)
uv run phase4-workbench &          # Python API on :8000
cd workbench && npm install && npm run dev  # React UI on :5173

# 3. Run eval (deterministic mode)
uv run phase2-eval --subset generalized_mvp --trials 1

# 4. Run tests
uv run python -m pytest tests/ -q
```

## Demo Walkthrough

Open `http://localhost:5173` and explore the 10 demo cases, grouped by user journey:

| Group | Cases | What It Shows |
|-------|-------|---------------|
| 🔐 身份认证 | Name + ZIP lookup | Authentication flow, user identity resolution |
| ✅ 成功写操作 | Cancel order, Return items, Modify items, Modify payment | Happy path write operations with confirmation |
| 🛡️ 写保护阻止 | Wrong user access, Product mismatch, Insufficient gift card | Guard layers blocking unauthorized writes |
| 🔄 用户确认 | Denied cancellation | User-facing confirmation dialog, deny flow |
| 📞 边界能力 | Transfer to human | Unsupported operations escalation |

**Key evidence in the timeline**: Intent extraction → Policy decision (allow/deny + reason) → Tool call result → Guard block details → Write audit (DB hash before/after, idempotency key).

![Guard block detail](docs/demo-screenshots/guard-block.png)
![Write audit detail](docs/demo-screenshots/write-audit.png)
![Confirmation pending](docs/demo-screenshots/confirmation-pending.png)

## Eval Results

| Metric | curated_mvp (11 cases) | generalized_mvp (30 cases) |
|--------|------------------------|---------------------------|
| pass_1 | 11/11 | 30/30 |
| pass_k | 11/11 | 30/30 |
| db_accuracy | 100% | 100% |

**Failure classification**: 14 ordered labels (llm_json_failure → auth_failure → wrong_intent → ...) ensure precise debugging.

![Eval passing](docs/demo-screenshots/eval-passing.png)

## Project Structure

```text
app/agent/       — 12-node pipeline runtime, state models, prompts, guard
app/tools/       — retail adapter, tool registry, write gateway
app/eval/        — curated + generalized eval cases, runner, failure labels
app/workbench/   — Workbench API (FastAPI backend)
workbench/       — Workbench React UI
prompts/         — versioned LLM prompts with SHA-256 hashes
docs/            — design specs, plans, architecture docs
```

## Development

```bash
# Lint
uv run ruff check .

# Format
uv run ruff format --check .

# Run a single test
uv run python -m pytest tests/test_agent_core.py -v

# Run interactive chat
uv run phase1-chat --interactive
```

For detailed architecture reference, see [`docs/portfolio-architecture.md`](docs/portfolio-architecture.md).
```

- [ ] **Step 2: 验证 Markdown 渲染**

```bash
head -20 README.md
```

确认文件格式正确，无语法错误。

- [ ] **Step 3: 提交**

```bash
git add README.md
git commit -m "docs: README重写为作品集叙事结构，面向面试官3分钟理解"
```

---

### Task 11: docs/portfolio-architecture.md 创建

**Files:**
- Create: `docs/portfolio-architecture.md`

- [ ] **Step 1: 创建架构文档**

新文件 `docs/portfolio-architecture.md`，7 段约 300 行：

```markdown
# Portfolio Architecture: Retail Customer Support Agent

> 面试深度参考资料 — 当面试官从 README 产生兴趣后，想深入了解设计决策时，就打开这一个文档。

## 1. 系统概述

一个基于 12-node LangGraph StateGraph 的零售客服 Agent。核心设计理念：**确定性先行，LLM 增强，拒绝优先**。系统必须始终做出安全决策，即使 LLM 出错或不可用。

关键数字：12 个 pipeline 节点、7 层写保护、2 轨并行决策（code + LLM）、1 个单一事实来源（action_specs.py）、30 个 eval case 全部通过。

## 2. 12-Node Pipeline

```
receive_message → conversation_gate → identity_resolver → intent_and_slot_extractor
→ context_loader → policy_reasoner → action_planner → write_action_guard
→ tool_executor → observation_reducer → response_generator → run_logger
```

| # | Node | 职责 | 输入 | 输出 |
|---|------|------|------|------|
| 1 | receive_message | 解析用户输入，加入 state.messages | raw text | user message |
| 2 | conversation_gate | 协议过滤（问候、感谢、无关话题） | user message | pass / early reply |
| 3 | identity_resolver | 用户身份认证（email / name+zip） | user message | user_id, auth_method |
| 4 | intent_and_slot_extractor | 意图识别 + 槽位填充 | user message | intent, slots |
| 5 | context_loader | 加载订单、商品、用户、支付数据 | user_id, order_id | loaded_context |
| 6 | policy_reasoner | 策略检查：允许/拒绝/需澄清 | intent, context | policy_decision |
| 7 | action_planner | 生成待执行写操作 | policy_decision | pending_action |
| 8 | write_action_guard | 7 层安全检查 | pending_action | pass / block |
| 9 | tool_executor | 执行工具调用 | action, args | tool_results |
| 10 | observation_reducer | 结果归纳，提取要点 | tool_results | observation |
| 11 | response_generator | 生成用户回复 | observation, context | assistant message |
| 12 | run_logger | 记录 trace artifact | full state | trace JSON |

**Circuit-breaker 模式**: 如果某节点追加了 assistant 消息到 `state.messages`，后续节点自动跳过（通过 `_has_assistant_response()` 检查）。这允许 conversation_gate 和 policy_reasoner 提前终止 pipeline。

## 3. Dual-Track Decision

### Code Track

- Regex-based intent extraction（关键词 + 模式匹配）
- Hardcoded policy rules（订单状态、商品可用性、支付方式归属）
- Explicit slot checks（order_id 格式、user_id 匹配）
- **始终运行**，不依赖外部 API

### LLM Track

- Semantic extraction via DeepSeek（OpenAI-compatible API）
- 仅在 `--require-llm` 且 `DEEPSEEK_API_KEY` 配置时运行
- 提取 code track 难以捕获的语义信息（如 `reason` 字段）

### Merge Rule: Deny Wins

```
track_a \ track_b | allow              | deny               | ask_clarification
------------------+--------------------+--------------------+-------------------
allow             | allow              | deny               | ask_clarification
deny              | deny               | deny               | deny
ask_clarification | ask_clarification  | deny               | ask_clarification
```

**为什么这样设计？** 在金融交易场景中，false negative（拒绝合法操作）优于 false positive（允许非法操作）。用户遇到 false negative 可以重新请求，但 false positive 可能造成不可逆的损失。

Code track 是"锚"——它提取的 order_id、item_id、user_id 等结构化数据，LLM 不能覆盖。LLM 只能补充 code track 未提取的字段。

## 4. 7-Layer Write Guard

`WriteActionGuard` 在 `app/agent/guard.py` 中实现，在**每一个写工具调用前**执行：

| Layer | 检查项 | 失败处理 | 实现位置 |
|-------|--------|----------|----------|
| 1. Authentication | 用户必须已登录 | block: `auth_required` | guard.py |
| 2. Confirmation | write 必须 `confirmed=True` | block: `confirmation_required` | guard.py |
| 3. Ownership | 订单必须属于认证用户 | block: `wrong_user` | guard.py |
| 4. Read-before-write | 订单必须先加载到 context | block: `order_not_loaded` | guard.py |
| 5. Policy | 订单状态、商品可用性、支付归属、礼品卡余额 | block: 具体原因 | guard.py |
| 6. Resource Locks | 同一资源不允许多个并发/重复写入 | block: `resource_locked` | guard.py |
| 7. Idempotency | 基于 hash 的幂等性 key | 去重而非 block | guard.py |

**关键不变量**: tools never call the guard directly。`ToolGateway` (`app/tools/gateway.py`) 是唯一入口点。

## 5. ToolGateway & Action Specs

### 读写分离

```
                   ┌──────────────────┐
User Message → ... →  action_planner  →  write_action_guard → ToolGateway
                   └──────────────────┘                              │
                                              ┌──────────────────────┤
                                              ▼                      ▼
                                        Read Tools            Write Tools
                                   (lookup, get_details)   (cancel, return, ...)
                                              │                      │
                                              └──────────┬───────────┘
                                                         ▼
                                                  Tool Results
```

- **Read tools**: 直接从 adapter 调取数据，不经过 guard
- **Write tools**: 必须先通过 `WriteActionGuard.check()`，由 gateway 统一调度

### 单一事实来源

`app/agent/action_specs.py` 定义 `WriteActionSpec` — 所有 7 个写操作的权威注册表：

```python
# 7 write operations: cancel_pending_order, modify_pending_order_address,
# return_delivered_order_items, exchange_delivered_order_items,
# transfer_to_human_agents, modify_pending_order_items,
# modify_pending_order_payment
```

每次新增写操作，**只需修改这一个文件**。Guard rules、tool registry、LLM prompts 中的 {action_catalog} 模板、runtime 中的 merge 逻辑全部从此派生。

## 6. Eval & Trace Infrastructure

### Eval Case 设计

- **curated_mvp** (11 cases): 人工精选，覆盖核心能力
- **generalized_mvp** (30+ cases): 基于 capability × policy_area 矩阵的系统化变体

每个 `EvalCase` 指定：
- `messages` — 模拟用户对话
- `expected_intent` — 期望识别出的意图
- `expected_tool_names` — 期望调用的工具
- `expected_guard_block_reason` — 期望的 guard 阻止原因（如有）
- `expected_db_assertions` — 数据库最终状态期望
- `expected_no_write` — 是否应无写操作

### 14 种 Failure Classification

优先级顺序（label 决定分类桶）:

1. llm_json_failure — LLM 返回无法解析的 JSON
2. auth_failure — 身份认证失败
3. wrong_intent — 意图识别错误
4. ... (共 14 种，定义在 `classify_failure()`)

### Artifact 契约

- **Eval run**: `artifacts/phase2/eval_runs/<id>.json` — schema_version v1
- **Eval report**: `artifacts/phase2/reports/<id>.json` — schema_version v1
- **Trace**: `artifacts/phase1/runs/<id>.json`
- **Dashboard**: `artifacts/phase3/dashboard/<id>/index.html`

所有 artifact 包含 schema_version、dataset paths、code commit、model config、prompt hashes、DB hashes。

## 7. Workbench

Workbench (`app/workbench/` + `workbench/`) 是一个 FastAPI + React 单会话演示面板。它的角色：

- **Demo**: Phase 6 的核心演示工具 — 面试官可以看到完整的 agent 运行过程
- **Debug**: 开发者可以逐步运行 case，观察每个 pipeline 节点的输入输出
- **Future AgentOps**: Phase 11 将在此基础上增加 run history、trace comparison、eval report browser

当前约束：单会话、不保存历史、不比较 trace、交互范围受限于预设 case 脚本。
```

- [ ] **Step 2: 提交**

```bash
git add docs/portfolio-architecture.md
git commit -m "docs: 创建作品集架构参考文档portfolio-architecture.md"
```

---

### Task 12: Demo 截图

**Files:**
- Create: `docs/demo-screenshots/workbench-overview.png`
- Create: `docs/demo-screenshots/guard-block.png`
- Create: `docs/demo-screenshots/write-audit.png`
- Create: `docs/demo-screenshots/confirmation-pending.png`
- Create: `docs/demo-screenshots/eval-passing.png`

- [ ] **Step 1: 创建目录**

```bash
mkdir -p docs/demo-screenshots
```

- [ ] **Step 2: 启动 Workbench 并截取关键画面**

```bash
# 终端 1: 启动 backend
uv run phase4-workbench

# 终端 2: 启动前端
cd workbench && npm run dev
```

打开 `http://localhost:5173`，依次操作并截图：

1. **workbench-overview.png**: 选择 "取消待处理订单"，点击 "运行全部"，等待完成后截取全屏（展示 6 个面板区域：RunControl, BusinessState, Conversation, Timeline, Inspector，以及 topbar 的 case label 和 mode pill）
2. **guard-block.png**: 选择 "阻止访问他人订单"，点击 "运行全部"，在 Timeline 中点击 guard block 事件，展开 Inspector 中的阻止详情，截取 Timeline + Inspector 并列区域
3. **write-audit.png**: 在上一步的同一 session 中，或切换到 "取消待处理订单"，在 Timeline 中点击 write_audit 事件，展开 Inspector 显示 DB hash before/after 和 idempotency key，截取
4. **confirmation-pending.png**: 选择 "取消待处理订单"，逐步执行到 pending action 出现，截取 BusinessState 面板（显示 pending action 橙色横幅、操作名称、参数、确认/拒绝/修改按钮）
5. **eval-passing.png**: 在终端运行 `uv run phase2-eval --subset generalized_mvp --trials 1`，截取最终输出（显示 30/30 passes）

保存截图到 `docs/demo-screenshots/`。

- [ ] **Step 3: 提交**

```bash
git add docs/demo-screenshots/
git commit -m "docs: 添加5张demo截图（workbench全景、guard block、write audit、confirmation、eval通过）"
```

---

### Task 13: 全面验收

- [ ] **Step 1: 运行测试**

```bash
uv run python -m pytest tests/ -q
```

Expected: 所有测试通过。

- [ ] **Step 2: 验证 Ruff**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: 两条命令均零输出。

- [ ] **Step 3: 验证 Eval 30/30**

```bash
uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{d[\"metrics\"][\"pass_1\"]}/{d[\"metrics\"][\"pass_1\"]}')"
```

Expected: 30/30。

- [ ] **Step 4: 验证 Workbench 构建**

```bash
cd workbench && npm run build
```

Expected: 构建成功，无错误。

- [ ] **Step 5: 提交（如有残留变更）**

```bash
git status
# 如有未提交变更
git add -A && git commit -m "chore: Phase 6 最终验收通过"
```
