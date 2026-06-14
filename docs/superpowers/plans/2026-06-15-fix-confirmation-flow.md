# Confirmation Flow 修复计划

## 问题诊断

通过分析 eval traces、测试失败、和源码，定位到三个根因：

### 根因 1：Deterministic 模式下 AgentLoop 不产生 tool_calls

`DeterministicProvider.chat_with_tools()` 只返回纯文本（`finish_reason="stop"`），永远不返回 `tool_calls`。AgentLoop 收到空 tool_calls 后直接走 `_step_finalize`，跳过 `_step_pending`，pending_action 永远不会被创建。

**影响范围**：5 个 workbench 测试全部因此失败（都用 `mode="deterministic"`），Workbench 的 deterministic 演示模式整体不可用。

### 根因 2：Live/LLM 模式下 exchange case 的 LLM 行为不稳定

LLM（deepseek-v4-flash）在处理 exchange 请求时，有时输出纯文本确认询问（类似 `ask_clarification`）而不调用 `exchange_delivered_order_items` 工具。没有 tool_call → 没有 guard 阻断 → 没有 pending_action → 用户回复 "yes" 被当作新一轮对话而非确认。

**影响范围**：`exchange_delivered_order_item` case 在 curated_mvp 中偶发失败（`wrong_tool`）。

### 根因 3：Deny 场景 LLM 响应不含 "No changes were made"

`_preflight_confirmation` 在 `resolution == "denied"` 时直接返回硬编码消息 `"No changes were made."`。但在 LLM 路径中，用户说 "no" 后可能被 AgentLoop 当作新对话轮次处理（因为 pending_action 可能未被正确设置），导致 LLM 自由生成响应而非走 preflight 短路。

**影响范围**：`deny_cancel_confirmation`、`deny_modify_address_confirmation` 在 generalized_mvp 中失败（`response_mismatch`）。

---

## 修复方案

### Step 1：恢复 Deterministic 模式的 confirmation 流程

**问题**：`DeterministicProvider` 不产生 tool_calls，AgentLoop 的 pending_action 机制对 deterministic 模式完全无效。

**方案**：在 `handle_user_message` 中，当 provider 为 DeterministicProvider（或 provider 为 None 触发了 deterministic fallback）时，不走 AgentLoop，改用内置的确定性流程处理 pending_action：

- 在 `_preflight_identity` 之后，检测如果是确定性模式且没有 LLM provider，执行确定性意图识别 + 工具调用
- 或者：让 `DeterministicProvider.chat_with_tools()` 返回至少一个 tool_call（基于规则匹配）

**推荐方案**：在 `handle_user_message` 中，当 `self.provider is None`（触发 `deterministic_fallback`）时，不走 AgentLoop，改为直接走简化流程：
1. 正则提取 intent + slots
2. 如果是写操作，直接调用 `_gateway.execute`（不带 confirmed=True），让 guard 返回 `explicit_confirmation_required`
3. 如果 guard block，创建 pending_action，设置 `confirmation_status = "required"`
4. 返回确认询问消息

**涉及文件**：
- `app/agent/runtime.py` — `handle_user_message` 方法
- `app/agent/providers.py` — 可能需要扩展 `DeterministicProvider`

### Step 2：修复 exchange LLM prompt/flow

**问题**：LLM 不调用写工具而是输出纯文本确认。需要在 prompt 或 AgentLoop 层面引导 LLM 对写意图始终先调用写工具。

**方案 A（Prompt 优化）**：在 `prompts/llm_agent_system_v001.md` 中强化规则——当用户明确表达了写意图且所有必要信息已提供时，**必须先调用对应的写工具**，工具返回的 guard block 会触发确认流程，不要自行输出确认询问文本。

**方案 B（代码兜底）**：在 AgentLoop 中检测：如果 LLM 响应中没有 tool_calls 但 conversation history 中有明确的写意图，则追加一条系统消息敦促 LLM 调用工具。

**推荐**：A 优先（prompt 优化），B 作为兜底。先看 prompt 优化能否稳定解决。

**涉及文件**：
- `prompts/llm_agent_system_v001.md`

### Step 3：确保 deny 响应包含 "No changes were made"

**问题**：`_preflight_confirmation` 在 denied 时已正确返回 `"No changes were made."`，但问题是 preflight 可能未被触发（因为 pending_action 未正确设置）。

**修复**：Step 1 和 Step 2 解决后，deny 场景应能正常走 preflight 短路。额外加固：在 `_preflight_confirmation` 中 denied 分支的消息保持不变（已正确）。

如果 root cause 修复后仍有问题，可在 `handle_user_message` 末尾检测 `confirmation_status == "denied"` 时确保消息包含该文本。

**涉及文件**：
- `app/agent/runtime.py` — 可能需要加固

### Step 4：更新 5 个 workbench 测试

**内容**：5 个失败测试的 `confirmation_status` 断言值与修复后的实际行为对齐。

涉及：
- `test_step_and_run_all_share_conversation_state` — 更新 first/last confirmation_status 期望值
- `test_generated_generalization_case_replays_with_seeded_runtime` — 同上
- `test_confirmed_write_tool_call_appears_after_confirmation_message` — 同上
- `test_wrong_user_demo_exposes_guard_block_signal` — assistant 消息内容匹配
- `test_session_step_and_run_all` (test_workbench_api.py) — 同上

**涉及文件**：
- `tests/test_workbench_session.py`
- `tests/test_workbench_api.py`

---

## 执行顺序

1. **Step 1** — 修复 deterministic 模式 confirmation 流程（核心修复）
2. **Step 4** — 更新 5 个测试断言（验证 Step 1）
3. **Step 2** — 优化 exchange LLM prompt
4. **Step 3** — 验证 deny 响应（可能已被 Step 1 自动修复）

## 验收标准

- `uv run python -m pytest tests/ -q` — 全部通过
- `uv run phase2-eval --subset curated_mvp --require-llm` — 11/11 pass
- `uv run phase2-eval --subset generalized_mvp --require-llm` — 30/30 pass
- Workbench deterministic 模式可正常完成 cancel/return/exchange 的 confirmation 流程
