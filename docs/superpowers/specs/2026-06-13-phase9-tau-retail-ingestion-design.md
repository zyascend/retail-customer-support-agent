# Phase 9.1: Tau Retail Smoke Test Ingestion — Design Spec

日期：2026-06-13
状态：待评审

## 目标

接入 tau3 retail 的前 5-10 个 supported task 作为 smoke test，验证 task → EvalCase 转换 + 脚本式用户消息 + reward evaluation 全链路能跑通。

## 整体阶段划分

- **Phase 9.1（本次）**：Smoke test — 脚本式用户消息、宽松评估、5-10 tasks
- **Phase 9.2（后续）**：Full ingestion — 模板式 UserSimulator、69 tasks、严格评估

## 架构

```
tau3 tasks.json → tau_loader.py → EvalCase → CuratedEvalRunner → AgentRuntime → 宽松评估 → Report
```

新增模块：

```
app/eval/
  tau_loader.py           ← tau3 task → EvalCase 转换器（本次）
  tau_user_simulator.py   ← 模板式 UserSimulator（Phase 9.2）
  cases.py                ← 修改：get_cases() 新增 tau_retail_smoke subset
```

## 组件设计

### tau_loader.py

核心函数：

```python
def load_tau_tasks(config: AppConfig, split: str = "train") -> list[dict]:
    """从 tau3 加载指定 split 的 task 列表。"""

def convert_task_to_eval_case(task: dict, subset: str) -> EvalCase | None:
    """将单个 tau3 task 转换为 EvalCase。返回 None 表示跳过（unsupported）。"""

def get_tau_smoke_cases(config: AppConfig) -> list[EvalCase]:
    """返回 5-10 个精选 supported task 的 EvalCase 列表。"""
```

#### task → EvalCase 转换逻辑

**用户消息构造**（脚本式）：

```
"{reason_for_call}. {known_info}. {unknown_info}."
```

将 `user_scenario.instructions` 的三个字段拼接成一条完整的初始用户消息。Agent 单轮处理，不涉及追问。

**EvalCase 字段映射**：

| tau3 字段 | EvalCase 字段 | 说明 |
|-----------|--------------|------|
| task.id | case_id = f"tau_{id}" | 加前缀避免与现有 case id 冲突 |
| task.user_scenario | messages[0].content | 拼接后的初始消息 |
| actions[].name | expected_tool_names | 提取所有 action name |
| actions[].name (ordered) | expected_tool_sequence | 按 tau3 顺序 |
| write actions | expected_db_assertions | 自动推导（见下） |
| 无 write action | expected_no_write = True | |
| TOOL_TO_CAPABILITY 映射 | capability | 从工具推断 |
| 固定值 | max_turns = 5 | smoke test 保守 |

**DB Assertion 自动推导**：

| Write Tool | expected_db_assertions |
|-----------|----------------------|
| cancel_pending_order | `{"order_status": "cancelled"}` |
| return_delivered_order_items | `{"order_status": "returned"}` |
| exchange_delivered_order_items | `{"order_has_items": [new_item_ids]}` |
| modify_pending_order_address | `{"order_address": {updated fields}}` |
| modify_pending_order_items | `{"order_has_items": [new_item_ids]}` |
| modify_pending_order_payment | `{"order_payment": new_payment_id}` |
| modify_user_address | `{"user_address": {updated fields}}` |
| transfer_to_human_agents | (no DB assertion, expected_no_write) |

#### Smoke Test Task 选择

从 69 个 supported task 中优先选择：
1. task 4/5/7（已知 task_issues，验证能否改善）
2. 覆盖主要 write capabilities：cancel、return、exchange、modify_items
3. train + test 各选几个

### cases.py 修改

```python
def get_cases(subset: str) -> list[EvalCase]:
    # 新增分支
    if subset == "tau_retail_smoke":
        from app.eval.tau_loader import get_tau_smoke_cases
        from app.config import resolve_config
        return get_tau_smoke_cases(resolve_config())
    # ... 现有分支不变
```

### 评估逻辑（宽松模式）

对于 `subset.startswith("tau_retail_")` 的 case，使用宽松判定：

1. **核心工具检查**：`expected_tool_names` 中至少一个 write tool 出现在 actual tool calls 中
2. **DB 方向检查**：有写操作 → DB hash 变化；无写操作 → DB hash 不变
3. **Auth 检查**：用户认证成功
4. **无意外 mutation**：不检查具体字段值
5. **tool_sequence 不强制匹配**：顺序不作为 failure
6. **NL assertion 不参与判定**：记录但不 gate

修改 `classify_failure()` 在 `app/eval/runner.py` 中，增加 tau subset 判定分支。

### CLI

```bash
# Smoke test（Phase 9.1）
uv run phase2-eval --subset tau_retail_smoke --trials 1

# Full ingestion（Phase 9.2）
uv run phase2-eval --subset tau_retail_supported --trials 1
uv run phase2-eval --subset tau_retail_train --trials 1
uv run phase2-eval --subset tau_retail_test --trials 1
```

## 不做的事（Phase 9.1）

- 不实现 UserSimulator（template 版留给 Phase 9.2）
- 不接入全部 69 个 supported task（smoke test 只需 5-10 个）
- 不进行 NL assertion 验证（仅记录）
- 不修改 AgentRuntime 的 12-node pipeline
- 不新增 Dashboard 视图（仅在 report metadata 中标记 tau）

## 验收标准

- [ ] `uv run phase2-eval --subset tau_retail_smoke --trials 1 --no-progress --json` 产生合法 report
- [ ] smoke test 5-10 个 task 全都有对应的 EvalCase 和结果
- [ ] report 的 `dataset_root` 指向 tau3 retail 目录
- [ ] 至少一个 write task 成功（confirmation → DB mutation）
- [ ] 至少一个 no-write task 保持 DB hash 不变
- [ ] 现有 `curated_mvp` 和 `generalized_mvp` 仍然通过
- [ ] `uv run python -m pytest tests/ -q` 通过
- [ ] `uv run ruff check .` 通过
