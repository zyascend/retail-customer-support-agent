# Phase 5 Spec & Plan Review — Optimization Analysis

## 审查结论

Phase 5 的设计文档（spec）质量很高，能力矩阵清晰。实施计划（plan）覆盖了 spec 的所有关键需求，但存在 **可优化的结构性问题**。以下是具体分析。

---

## 一、Plan 中的准确性问题（需修正）

### 1. `WRITE_ACTIONS`/`DEFERRED_WRITE_ACTIONS` 常量已存在

**现状**：`app/agent/guard.py` 已经包含：
```python
WRITE_ACTIONS = {
    ...,
    "modify_pending_order_items",  # 已存在
    ...
}
DEFERRED_WRITE_ACTIONS = {"modify_pending_order_payment"}  # 被阻塞
```

**Plan Task 3 Step 4 说**：「Add `modify_pending_order_items` and `modify_pending_order_payment` to write actions」

**问题**：`modify_pending_order_items` 已经在 `WRITE_ACTIONS` 中，不需要重复添加。关键操作应该是：将 `modify_pending_order_payment` 从 `DEFERRED_WRITE_ACTIONS` 移到 `WRITE_ACTIONS`。

**建议**：将 Step 4 改为「Move `modify_pending_order_payment` from `DEFERRED_WRITE_ACTIONS` to `WRITE_ACTIONS`」，并明确需删除 `DEFERRED_WRITE_ACTIONS` 或置为空集合。

### 2. `_resource_lock` 的 category map 已部分存在

**现状**：
```python
category = {
    "cancel_pending_order": "cancel",
    "modify_pending_order_address": "modify_address",
    "modify_pending_order_items": "modify_items",  # 已存在
}
```

**Plan Task 3 Step 9** 再次列出整个 map 且**遗漏了 `modify_pending_order_payment`**。应改为仅添加 `"modify_pending_order_payment": "modify_payment"`。

### 3. import 语句可能引入重复

**Plan Task 3 Step 3** 建议添加 `from app.tools.retail_adapter import (find_variant_in_db, get_current_payment_method_id, get_order_from_db, get_user_from_db)`，但 `get_order_from_db` 和 `get_user_from_db` **已被导入**。应精确为只添加新的两个函数。

---

## 二、任务合并优化

### 可合并的任务对：

| 合并 | 理由 | 节省工作量 |
|------|------|-----------|
| **Task 1 + Task 6** | 都修改 `app/eval/cases.py`、`app/eval/runner.py`、`tests/test_eval_runner.py`。Task 1 做 plumbing，Task 6 做 cases，分两个 commit 即可，不必分两个 task。 | 减少重复的 git 操作、文件切换 |
| **Task 4 + Task 5** | 都修改 `app/agent/runtime.py` 和 `tests/test_agent_core.py`。Guard block response 映射是 runtime 的自然组成部分，拆开反而增加来回改动。 | 减少一次完整的测试循环 |

**建议的任务顺序**（共 6 个 task）：

1. **Task A**: Extend eval case contract (原 Task 1 + Task 6 合并)
2. **Task B**: Complete local retail write tools (原 Task 2)
3. **Task C**: Strengthen write guard policy (原 Task 3，修正上述准确性问题)
4. **Task D**: Add runtime auth, intents, planners + guard responses (原 Task 4 + Task 5 合并)
5. **Task E**: Update workbench demo cases (原 Task 7)
6. **Task F**: Final verification + docs (原 Task 8)

---

## 三、缺失项

### 1. 新 demo case 的中文标题

`app/workbench/cases.py` 的 `CASE_TITLES` 字典为现有 11 个 case 提供了中文翻译。Plan 未提及为新 Phase 5 cases 添加中文标题。建议新增：

```python
"modify_pending_order_items_success": "修改待处理订单商品",
"modify_pending_order_payment_success": "修改待处理订单支付方式",
"modify_user_default_address_success": "修改用户默认地址",
"block_item_product_mismatch": "阻止跨产品换货",
"block_item_unavailable": "阻止换货缺货商品",
"block_payment_not_owned": "阻止使用他人支付方式",
```

### 2. `modify_pending_order_payment` 工具实现中的 `_get_payment_method` 可用性验证

Plan Task 2 Step 5 实现 `modify_pending_order_payment` 时调用了 `self._get_payment_method(order["user_id"], payment_method_id)`。当前代码中 `_get_payment_method(self, user_id: str, payment_method_id: str)` 已存在（line 150），Plan 未确认其行为（是否对不存在的 payment_method 抛异常）。建议 task 开始时先验证。

### 3. `_conversation_gate` 中 guard 错误映射的具体位置

Plan Task 5 Step 3 的代码片段不完整，只显示了 `GUARD_USER_MESSAGES` 的定义和修改 `_conversation_gate` 的意图，但没有给出完整的替换逻辑。当前 `_conversation_gate` 的 error 分支是：

```python
self._assistant(state, f"I could not complete that update: {record.error}.")
```

应改为：

```python
user_msg = GUARD_USER_MESSAGES.get(record.error, record.error)
self._assistant(state, f"I could not complete that update: {user_msg}.")
```

### 4. eval case 数量缺口

Plan 描述的 cases 大约 27-28 个，spec 要求约 30 个。建议补充 2-3 个边界 case，例如：
- `block_modify_user_address_wrong_user` — 用户尝试修改他人地址
- `block_modify_items_count_mismatch` — item 和 new_item 数量不匹配
- `name_zip_auth_insufficient_fields` — name+zip 缺少字段时请求补全

---

## 四、结构性改进建议

### 1. 计划文档过冗长（1673 行）

大量 inline Python 代码增加了计划长度。建议将长代码块替换为文件路径引用 + 关键逻辑描述。例如 Task 2 Steps 4-5 的实现代码可以简化为：

> 在 `LocalRetailTools` 中实现 `modify_pending_order_items`（~40行，含 order 状态校验、item 查找、variant 可用性检查、替换逻辑）和 `modify_pending_order_payment`（~20行，含 order 状态校验、支付方式差异检查、gift card 余额检查）。

这样可以将计划压缩到 600-800 行，更容易审阅。

### 2. 添加 pre-flight checks

在 Task 开始前增加验证步骤：
- 确认 `find_user_id_by_name_zip` 在 `retail_adapter.py` 中已实现且通过现有测试
- 确认 `modify_user_address` 工具在 `retail_adapter.py` 中已实现
- 确认 `find_variant_in_db` 和 `get_current_payment_method_id` 是否需要新建

这些验证可以避免实现中途发现前置条件不满足。

### 3. Spec 中 `modify_user_address` 的范围需要更精确

Spec 说 add `modify_user_address` tests and runtime path，但实际上该工具已存在。真正缺失的是 runtime 层面的 intent routing 和 planner。Plan 正确处理了这一点，但 spec 可以更精确地描述为「add runtime support for modify_user_address intent」。

### 4. Guard `_validate_policy` 中 exchange 的 product/availability 检查

Plan Task 3 Step 7 正确指出 exchange 应复用 `_validate_item_replacements`，这是好的。但目前 `_validate_policy` 中 exchange 分支只检查了 count mismatch。添加 product 和 availability 检查后，现有的 `block_exchange_product_mismatch` 和 `block_exchange_unavailable_replacement` eval cases 才能通过。Plan 应强调这是一个**行为变更**，可能影响现有 exchange 测试。

---

## 五、风险点

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| `modify_pending_order_payment` 从 DEFERRED 移出后，所有 payment 路径突然激活 | 未充分测试的路径可能导致意外行为 | 先在 guard 和 tool 层完成实现，再做 runtime 集成 |
| guard 的 `_validate_item_replacements` 被 exchange 复用 | 可能改变现有 exchange 的 guard 行为 | 需要对现有 exchange cases 做回归测试 |
| `_conversation_gate` 中 guard error 映射不完整 | 部分 guard reason 仍以机器可读形式暴露给用户 | 确保 `GUARD_USER_MESSAGES` 覆盖所有 `_validate_policy` 的返回值 |
| eval case 字段 `subset`, `capability`, `policy_area` 是新增的 | 现有所有代码不识别这些字段，可能导致序列化问题 | 确保 `EvalCase` dataclass 接受 unknown fields 或显式添加新字段 |

---

## 总结

Spec 的质量很高。Plan 覆盖完整但存在 **3 个准确性问题**（WRITE_ACTIONS、resource_lock、import 重复）和 **2 个可合并任务对**（Task 1+6、Task 4+5），以及 **4 个缺失项**（中文标题、conversation_gate 映射细节、eval case 数量缺口、pre-flight checks）。建议按上述优化后的 6-task 结构执行，总工作量不变但更流畅。
