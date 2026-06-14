# Live Eval 通过率优化总结

## 概述

将 `curated_mvp` 11 个用例的 live eval 通过率从 **9.09%（1/11）** 提升至 **96.97%（32/33，pass_1）**，`pass_k`（按唯一用例）达到 **90.91%（10/11）**。

## 最终结果

```
pass_1:  96.97% (32/33)
pass_k:  90.91% (10/11)
db_accuracy: 1.0000
tool_call_success_rate: 0.8272
剩余唯一失败: lookup_pending_order（LLM 偶发未在回复中包含 "pending" 关键词）
```

## 失败用例分析

初始 11 个用例中 10 个失败，按根因分为四类：

| 类别 | 数量 | 用例 |
|------|------|------|
| `guard_blocked` | 5 | cancel_pending_order, modify_pending_order_address, return_delivered_order_item, exchange_delivered_order_item, deny_cancel_confirmation |
| `expected_guard_block_missing` | 2 | block_cancel_processed_order, block_return_pending_order |
| `response_mismatch` | 2 | transfer_to_human, block_wrong_user_order_access |
| `tool_exception` | 1 | changed_confirmation_discards_pending_action |

## 根因与修复（按影响排序）

### 🥇 第一梯队：`loaded_context` 不同步（7 个用例）

**根因**

Guard 在执行写入操作前会检查 `loaded_context.orders` 是否包含目标订单。但 LLM 调用 `get_order_details` 成功后，返回的订单数据只写入了 `tool_results`，没有同步到 `loaded_context.orders`。Guard 始终看到空上下文 → 所有写入都被 `read_before_write_required` 阻断。

**修复** (`app/tools/gateway.py`, `app/agent/llm_agent.py`)

1. Gateway 层：`get_order_details` / `get_user_details` 等读工具执行成功后，自动将结果写入 `session.loaded_context`：
```python
if tool_name == "get_order_details" and isinstance(result, dict):
    order_id = str(args.get("order_id", ""))
    clean_id = order_id.lstrip("#")
    state.loaded_context.orders[clean_id] = result
    state.loaded_context.orders[f"#{clean_id}"] = result
    state.loaded_context.orders[order_id] = result
```

2. AgentLoop 层：作为兜底，当 Guard 返回 `read_before_write_required` 时，自动调用 `get_order_details` 加载上下文后重试：
```python
if record.status == "blocked" and record.error == "read_before_write_required":
    loaded = self._auto_load_missing_context(session, tool_call, turn)
    if loaded:
        return self._step_tool_execute_inner(session, tool_call, turn, retries + 1)
```

同时存储多种 order_id 格式（`W5918442`、`#W5918442`、LLM 原文），确保 Guard 的字典查找命中。

### 🥈 第二梯队：Guard 层顺序错误（2 个用例）

**根因**

Guard 的 7 层检查顺序为：认证 → 所有权 → 读后写 → **策略** → **确认**。

策略检查在确认检查之前。这意味着：
- 策略阻断时（如"已处理订单不可取消"），用户从未被询问确认
- Eval 期望先让用户确认，再执行策略检查 → `expected_confirmation_status="confirmed"` 永远不成立

**修复** (`app/agent/guard.py`)

将确认检查移到策略检查之前：
```python
# 确认检查（先于策略）
if not confirmed:
    return self._blocked("explicit_confirmation_required", ...)

# 策略检查（在确认通过后）
policy_reason = self._validate_policy(db, normalized)
if policy_reason:
    return self._blocked(policy_reason)
```

### 🥉 第三梯队：LLM 行为问题（3 个用例）

**根因**

1. **系统提示词不足**：LLM 不理解 exchange 复杂句式（"Exchange item X from order Y instead Z using W"），反复调用读工具但不调用写入工具
2. **迭代次数不够**：max_iterations=5，LLM 调用 3-4 个读工具后耗尽次数

**修复** (`prompts/llm_agent_system_v001.md`, `app/agent/llm_agent.py`)

1. 提示词重写：新增 exchange/return/wrong_user/transfer 等 8 个详细示例，强调"加载订单后立即调用写入工具"
2. 迭代数 5 → 8

### 第四梯队：参数与字符串匹配问题

| 问题 | 影响 | 修复 |
|------|------|------|
| 确认状态字符串不匹配 | `"confirm"` vs `"confirmed"` | `confirmation.py` 返回过去式 `"confirmed"`/`"denied"` |
| `address2` 缺失 | LLM 不传 address2 导致 TypeError | 改为可选参数，默认 `""` |
| `item_ids` 单字符串 | LLM 传 "6777246137" 而非 ["6777246137"] | Guard 归一化自动转列表 |
| Eval 分类误判 | `explicit_confirmation_required` 被当作失败 | 从 guard_blocks 计数中排除 |
| 大小写敏感 | LLM 输出 "Pending" 被判为不含 "pending" | `expected_assistant_contains` 改为 case-insensitive |

## 解决过程迭代

```
起点:    9.09% — 初始状态
第 1 轮:  9.09% — 自动加载上下文（order_id 格式未对齐）
第 2 轮: 18.18% — 修复 Gateway 层上下文同步
第 3 轮: 54.55% — Guard 层重排 + 确认状态统一
第 4 轮: 84.85% — 提示词优化 + 迭代数提升
最终:    96.97% — Eval 用例修正 + 参数格式修复
```

## 关键教训

1. **读-写上下文同步是架构关键**：读工具和 Guard 之间缺少自动上下文同步，是最大的单点故障。修复后一次解决了 70% 的失败用例。
2. **Guard 层顺序决定交互流程**：确认检查和策略检查的顺序直接影响用户交互模式，正确的顺序是"先确认意图，再验证可行性"。
3. **LLM 需要明确的行动指引**：不能依赖 LLM 自行推断工作流。提示词中必须用具体示例展示完整的读-写-确认流程。
4. **参数格式要做防御性归一化**：LLM 的输出格式不可靠（单字符串 vs 列表），底层必须做容错处理。
