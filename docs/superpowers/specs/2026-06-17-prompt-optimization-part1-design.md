# Prompt Optimization Part 1 Design

## Summary

本设计覆盖 `docs/superpowers/specs/2025-06-16-harness-engineering-optimization.md` 中 Prompt 优化的三个子项，但按两个落地阶段推进：

- **Phase A（优先）**：`1.1` 系统提示词精简压缩 + `1.3` 显式停止条件
- **Phase B（紧随其后，同一主题内完成）**：`1.2` 补充复杂场景 few-shot

本次设计目标不是改 runtime、tool schema 或 guard 逻辑，而是仅通过重构 `prompts/llm_agent_system_v001.md` 的信息组织，降低 prompt 冗余、减少 planner 歧义，并为多步骤场景提供更强示例牵引。

## Goals

1. 将当前 prompt 从“18 条规则 + CRITICAL 长展开 + Workflow 重复强调”压缩为“核心合同 + 写操作合同 + 停止条件 + 示例”结构。
2. 保留项目关键不变量：
   - 写操作绝不绕过 Guard
   - LLM 绝不在 Guard 前自行拒绝写操作
   - 确认后不重做已完成操作
3. 显式定义何时应继续、何时应停止，减少 early stop 与无意义 loop。
4. 在不把 `1.2` 拆出本主题的前提下，让复杂 few-shot 建立在更紧凑稳定的 prompt 骨架上。

## Non-Goals

- 不修改 `app/agent/runtime.py`、`app/agent/llm_agent.py`、`app/tools/registry.py` 或 Guard 执行逻辑。
- 不引入新的 `think` 工具、provider、context budgeting 或 refusal classifier。
- 不在本主题内新增 prompt 分片系统，仍维持单文件 `prompts/llm_agent_system_v001.md`。

## Current Problems

### 1. 重复规则过多

当前 `prompts/llm_agent_system_v001.md` 同时在以下区域重复表达“读完后仍要调用 write tool，让 guard 决定”的同一语义：

- `Rules` 第 4/5 条
- `## ⚠️ CRITICAL: Never Refuse Without Calling the Write Tool`
- `## Workflow`

这种重复有两个副作用：

- token 成本高，但新增信息密度有限
- planner 需要在多个相似段落里抽取同一 contract，增加噪音

### 2. 缺少明确停止条件

当前 prompt 强调 `complete multi-part requests`，但没有反向说明“何时可以结束”。
这会导致模型更容易出现两类问题：

- **过早结束**：写操作成功后直接总结，没有完成剩余金额/子任务
- **过度继续**：guard block 或任务完成后仍继续尝试无意义工具调用

### 3. few-shot 偏单步，无法支撑复杂 continuation

当前示例大多是“查一次 → 写一次 → 返回一句”。这足够覆盖基础 guard contract，但不足以教会模型：

- 写操作成功后继续完成原始请求中的剩余部分
- 正确进行退款/差价计算
- 在 block 后识别无替代路径并收尾

## Design Principles

### 1. Rule budget 优先

只有会显著影响 planner 行为、且无法完全从 tool schema / guard / runtime 推导出来的内容，才保留在顶层规则里。

### 2. Safety rules 与 heuristics 分层

高强度约束（如 write-through-guard）与高频启发（如 recent order、single payment method）分区表达，避免同级混排。

### 3. Stop contract 独立成区块

停止条件不再埋在示例或“complete request”描述里，而是单独定义成显式 contract。

### 4. few-shot 只教高价值路径

示例数量不追求多，而追求覆盖 continuation、金额计算、成功后继续完成剩余任务这几类最难路径。

## Proposed Prompt Structure

新的 `prompts/llm_agent_system_v001.md` 结构调整为：

1. `Identity`
2. `Available Tools`
3. `Retail Policy`
4. `Current Session State`
5. `Core Contract`
6. `Write Requests`
7. `Heuristics`
8. `Stop Conditions`
9. `Examples`
10. `Tool Call Format`

### 5. Core Contract

目标是将当前 18 条规则压缩到约 8–10 条，保留真正影响 planner 的硬约束。

建议保留的规则语义：

1. **No data fabrication** — 任何订单、用户、商品、金额都必须来自工具结果
2. **Read before write** — 写前必须先读取对应事实
3. **Always state order status when relevant** — 查订单时显式说出状态
4. **Write through guard** — 不要在文本里预先拒绝写操作，必须调用 write tool 让 guard 决策
5. **Handle guard blocks concisely** — block 后清楚说明原因，不长篇道歉
6. **Recover from tool errors when possible** — 能修就修，不能修再解释或转人工
7. **Complete multipart requests** — 不要只完成第一步
8. **Use tools for money answers** — 涉及退款/差价/余额必须基于 observation + `calculate`
9. **Do not retry successful writes** — 已完成操作不得重做

### 6. Write Requests

这是对当前 `CRITICAL` + `Workflow` 的合并重写。

该区块应只有一个目的：**告诉模型，写操作的允许性由 guard 决定，而不是由模型在调用前自行裁决。**

建议内容：

- 若用户请求取消/退货/换货/改地址/改支付/改配送等写操作：
  1. 先读相关订单或用户事实
  2. 然后立即调用对应 write tool
  3. 即使你预计会失败，也仍然调用
  4. guard 要确认时，再向用户请求确认
  5. guard block 后，再向用户解释原因与可行替代

保留 1 组 `WRONG / RIGHT` 对照即可，不再保留长列表重复案例。

### 7. Heuristics

把当前高频优化规则与 safety rules 解耦，作为独立区块保留，避免主合同过长。

建议纳入：

- `Use loaded recent orders before asking for IDs`
- `Use known single payment methods`
- `Combine same-order item changes`
- `Match replacement variants exactly`
- `Use exact order item IDs for returns/exchanges`
- `Avoid exhaustive fallback loops`

其中可进一步合并，控制在 4–6 条。

### 8. Stop Conditions

新增独立区块，建议使用明确枚举：

```text
Stop and provide a final response when:
(a) all user-requested actions and questions are complete, or
(b) a guard block prevents progress and no useful alternative remains, or
(c) available tools cannot make further progress after reasonable retries.
```

这条 contract 用来补足 `complete multi-part requests` 的另一半：

- 什么时候不能提前停
- 什么时候应该果断收尾

### 9. Examples

示例分两阶段调整：

#### Phase A

先保留少量基础示例，保证结构重写后仍有最基本的 anchoring：

1. 订单状态查询
2. 单一步骤写操作成功（如 cancel）
3. 单一步骤 guard block（如 non-pending cancel）
4. ownership violation 但仍调用 write tool
5. transfer to human

#### Phase B

在同一主题的第二阶段，把例子升级成“2 个基础 + 3 个复杂”的组合：

1. **Return + refund total**
   - 先读订单
   - 调 return write tool
   - 成功后继续计算指定 item 总退款
   - 最后一起回答“已发起退货 + 退款金额”

2. **Exchange + price difference / gift card balance**
   - 先读订单与产品详情
   - 调 exchange write tool
   - 成功后根据 observation 计算正负差价
   - 若用户问 gift card 余额，继续完成余额推导

3. **Multi-part continuation after successful write**
   - 例如“取消订单并告诉我最贵商品多少钱”
   - 写成功后继续完成剩余问答，而不是立即总结

这些复杂示例应优先覆盖报告中指出的缺失场景，而不是继续补更多单步写操作示例。

## Rule Mapping

建议从旧结构到新结构做如下映射：

- 旧 `Rules #1 #2 #3 #4 #5 #6 #8 #9 #10 #18` → 新 `Core Contract`
- 旧 `Rules #12 #13 #14 #15 #16 #17` → 新 `Heuristics`
- 旧 `CRITICAL` + `Workflow` → 新 `Write Requests`
- 新增 `Stop Conditions` 承接旧 `Rules #9` 的反向约束
- 旧 `Examples` 中保留高信号样例，其余由复杂 continuation few-shot 替换

## Expected Benefits

### 1. Token efficiency

通过去掉规则/CRITICAL/workflow 的语义重叠，prompt 应显著缩短，同时不损失关键 contract。

### 2. Better planning clarity

模型更容易识别：

- 什么是必须服从的硬规则
- 什么是有帮助但次一级的启发
- 什么情况下应该继续
- 什么情况下应该停止

### 3. Better continuation behavior

复杂 few-shot 会直接教会模型：写成功后不要立刻结束，而要完成剩余任务与金额回答。

## Risks

### 1. 过度压缩导致隐性能力回退

如果删掉过多细节，可能让某些依赖现有 wording 的场景回退。

**缓解**：
- Phase A 只压缩明显重复项，不删核心约束
- 保留至少一个 `ownership violation but still call write tool` 正反例

### 2. few-shot 与规则同时大改，收益归因不清

**缓解**：
- 先完成 Phase A，再接着做 Phase B
- 两阶段都属于本主题，但验证时分开观察

### 3. recent order / payment heuristics 被压得太后面

**缓解**：
- 将 heuristics 独立成区块，而不是完全删除
- live eval 重点观察 recent-order 与 refund/payment 相关失败是否回升

## Validation Plan

### Phase A validation

- 读取并人工审查新 prompt 结构，确认：
  - 核心不变量仍在
  - `Stop Conditions` 明确存在
  - `CRITICAL` / `Workflow` 不再重复表达
- 运行与 prompt 相关的 targeted tests（若本轮新增测试，则先跑测试）
- 运行至少一个小范围 eval 子集，观察：
  - premature refusal 是否无明显回退
  - multi-part completion 是否改善或持平

### Phase B validation

- 审查 few-shot 是否覆盖：
  - return + refund amount
  - exchange + price difference
  - successful write + remaining subtask
- 再跑同一 eval 子集，重点比较 continuation/money 类案例

## Files In Scope

- Modify: `prompts/llm_agent_system_v001.md`
- Reference: `app/agent/prompts.py:44`
- Reference: `app/agent/llm_agent.py:1212`
- Optional tests to add during implementation if needed: prompt assembly / regression tests under `tests/`

## Open Implementation Notes

1. Prompt 主题内部按两阶段实施，但仍视为同一优化项。
2. 如果实现阶段发现缺少 prompt-level regression test，可以补一个轻量测试，验证组装后的 prompt 含有 `Stop Conditions` 与关键 guard contract。
3. 若 live eval 结果显示 recent-order 或 payment-path 回退，则优先微调 `Heuristics` 区块，而不是重新膨胀 `Core Contract`。

## Recommendation

采用“**同一主题，两阶段落地**”方案：

- **先做 `1.1 + 1.3`**：先把 prompt 压成更清晰的合同
- **紧接着做 `1.2`**：把复杂 few-shot 插入新的结构中

这样既满足“`1.2` 不与本次任务分开”，也保证验证时能区分结构优化与 few-shot 优化各自的效果。
