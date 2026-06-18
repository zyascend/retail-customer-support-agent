# DeepSeek KV Cache 优化技术复盘

## 1. 背景

本项目是一个基于 DeepSeek tool-calling 的零售客服 agent。随着多轮对话、工具定义和上下文摘要不断增长，单次 LLM 请求的 `prompt_tokens` 成本持续上升。DeepSeek 官方文档说明其默认开启 KV Cache，并在 `usage` 中提供缓存命中统计字段，因此本轮优化的核心目标不是单纯“改 prompt 更短”，而是：

1. 提高可复用前缀的稳定性，提升 KV Cache 命中机会
2. 打通缓存命中指标采集链路，确保收益可以被量化
3. 用 live eval 做严格 A/B，对优化结果给出证据

参考文档：DeepSeek KV Cache 指南（`https://api-docs.deepseek.com/zh-cn/guides/kv_cache`）。

---

## 2. 问题定义

在初始实现中，LLM 调用链虽然已经具备较稳定的 system prompt 和 tool schema，但仍有两个明显问题：

### 2.1 前缀不稳定

`app/agent/llm_agent.py` 在构造消息时，会把动态 `state_summary` 注入 `system prompt`。这意味着：

- 已加载订单
- 用户付款方式
- 最近成功写操作
- 最近 guard block
- 历史截断摘要

这些会随 turn 波动的内容都进入了请求最前缀。根据 DeepSeek KV Cache 文档，这会明显降低完整前缀复用概率。

### 2.2 缓存收益不可观测

虽然 DeepSeek 文档明确说明 `usage` 中存在：

- `prompt_cache_hit_tokens`
- `prompt_cache_miss_tokens`

但项目原始实现只统计：

- `prompt_tokens`
- `completion_tokens`
- `total_tokens`

因此即使服务端发生缓存命中，eval 报告层也无法证明收益。

---

## 3. 优化目标

本轮优化只聚焦缓存相关收益，不以行为指标优化为主目标。具体目标如下：

1. **结构目标**：让 system prompt 尽量稳定，动态状态后移
2. **观测目标**：让缓存命中数据进入 trace、eval runner、metrics、report
3. **实验目标**：跑出严格 A/B 数据，至少拿到可引用的 hit/miss token 与 hit ratio

非目标：

- 不追求本轮将 `generalized_mvp` 行为指标稳定到 30/30
- 不在本轮解决所有 confirmation 波动与 tool selection 漂移问题

---

## 4. 优化思路

### 4.1 方案一：稳定 system prompt 前缀

原始实现将 `Current Session State` 直接拼入 system prompt，这会导致 system 每轮变化。优化后改为：

- `system` 只保留稳定规则和工具定义
- 动态 `state_summary` 改为单独的后置消息
- 历史截断摘要 `truncation_summary` 也不再写入 system，而是与状态消息一起下沉

这样做的收益是：

- 固定前缀更长
- 工具 schema + system 规则更容易被跨 turn 复用
- 动态会话态只影响后缀，不破坏共享前缀

### 4.2 方案二：在确认阶段隐藏误导性状态

在确认流程中，如果把 `Recent successful writes` 和 `Active safeguards` 暴露给模型，模型可能误以为某次待确认动作已经执行，导致重复确认或重复 write。

因此，在 `pending_action` 存在时：

- 保留 `Pending: ... waiting for user confirmation`
- 隐藏 `Active safeguards`
- 隐藏 `Recent successful writes`

这一步不是缓存优化本体，但它是“把动态状态后移”后暴露出来的行为问题修正。

### 4.3 方案三：打通缓存指标采集链路

目标是让 DeepSeek KV Cache 字段能够从 provider 一路进入 report：

`DeepSeek raw response -> provider.token_usage -> TurnContext -> EvalRunner -> compute_metrics -> report`

包括：

- `prompt_cache_hit_tokens`
- `prompt_cache_miss_tokens`
- `prompt_cache_hit_ratio`

---

## 5. 实施过程

### 5.1 第一步：泛化 token usage 聚合

首先扩展 token usage 聚合逻辑，不再只累计三项固定字段，而是累计所有整型 usage 字段。这样即使后续 provider 返回了新增 usage 字段，也能自动进入 report。

涉及位置：

- `app/agent/providers.py`
- `app/eval/runner.py`
- `app/eval/metrics.py`
- `tests/test_providers.py`
- `tests/test_eval_runner.py`

### 5.2 第二步：拆分 system 与动态状态

在 `app/agent/llm_agent.py` 中重构 `_build_messages`：

- system prompt 改为固定文案
- `state_summary` 改为单独 `assistant` 消息
- `truncation_summary` 不再污染 system 前缀

### 5.3 第三步：修正确认阶段上下文误导

live eval 暴露出地址修改 / 支付修改的 confirmation 回归后，继续排查发现问题不在缓存统计，而在确认阶段的状态摘要误导模型。

因此在 `app/agent/context_builder.py` 中加入：

- `pending_action` 存在时，不展示 `Recent successful writes`
- `pending_action` 存在时，不展示 `Active safeguards`

### 5.4 第四步：严格 A/B 遇到观测盲点

为了做严格 A/B，创建了独立 git worktree，在同一模型、同一 subset、同一并发配置下分别跑：

- 改造前基线 commit
- 改造后版本

最初 A/B 报告仍然拿不到缓存字段，虽然理论上 provider 代码已支持动态 usage 聚合。这说明问题不在 report 聚合，而更早发生在 provider 读取阶段。

### 5.5 第五步：系统化排查“为什么没返回”

排查顺序如下：

1. 查 trace 中 `llm_token_usage` 是否包含 cache 字段
2. 查 DeepSeek 文档，确认字段是否属于官方 usage schema
3. 查 `openai==2.41.1` 的 `CompletionUsage` 类型结构
4. 用 `with_raw_response.create(...)` 验证原始 body 是否包含字段

最终确认：

- DeepSeek 原始响应体中**确实有** `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`
- `openai==2.41.1` 的 typed `CompletionUsage` **不能可靠承载这些扩展字段**
- 原始实现从 `response.usage` 取值，因此在 `chat_with_tools` 路径把字段读丢了

### 5.6 第六步：provider 改为 raw response usage 提取

最终修复：

- `chat_with_tools` 改为 `with_raw_response.create(...)`
- 优先从原始 JSON 的 `usage` 提取整型字段
- 再 fallback 到 SDK typed `usage`

这样既保留兼容性，也保证 DeepSeek 扩展字段不丢失。

### 5.7 第七步：补齐 `prompt_cache_hit_ratio`

在 `app/eval/metrics.py` 中新增：

- `prompt_cache_hit_ratio = hit / (hit + miss)`

并同步到 eval report，保证最终报告能直接展示可引用指标，而不需要额外手算。

---

## 6. 验证与实验结果

### 6.1 严格 A/B 说明

A/B 采用独立 worktree，避免污染主工作区与未提交改动。配置保持一致：

- subset：`generalized_mvp`
- model：`deepseek-v4-flash`
- mode：`--live`
- concurrency：`--max-workers 50`

### 6.2 关键验证结论

在 provider 修复后，真实 `chat_with_tools` 冒烟调用已能直接拿到缓存字段，例如：

- `prompt_cache_hit_tokens=256`
- `prompt_cache_miss_tokens=9`

说明 `tool-calling` 场景本身并不屏蔽 KV Cache 字段，问题确实出在 SDK typed usage 提取方式。

### 6.3 fresh live report

最终 fresh report：

- `artifacts/phase2/reports/eval-8f1fb8f5e86f.json`

关键指标：

- `prompt_cache_hit_ratio = 0.9552`
- `prompt_cache_hit_tokens = 226560`
- `prompt_cache_miss_tokens = 10620`

这说明在当前 `generalized_mvp` live eval 样本下：

- Prompt 侧缓存命中率约为 **95.52%**
- 大部分 prompt token 已由缓存命中承担

---

## 7. 优化前后收益对比

### 7.1 可观测性收益

| 指标 | 优化前 | 优化后 |
|---|---:|---:|
| `prompt_cache_hit_tokens` | 不可观测 | 226560 |
| `prompt_cache_miss_tokens` | 不可观测 | 10620 |
| `prompt_cache_hit_ratio` | 不可观测 | 0.9552 |
| case 级 cache token 字段 | 无 | 有 |
| report 级 cache 指标 | 无 | 有 |

这里“优化前”不是 `0`，而是**采集链路无法读取**，因此无法做缓存收益归因。

### 7.2 架构收益

除了拿到指标，本轮改造还有两个长期价值：

1. **前缀稳定性提升**
   - 动态状态不再污染 system prompt
   - 更符合 DeepSeek KV Cache 的前缀复用机制

2. **后续优化具备可验证基础**
   - 以后做 prompt 压缩、schema 裁剪、状态摘要精简时，可以直接用 cache hit ratio 做实验指标，而不只是看 total tokens

---

## 8. 遇到的问题

### 8.1 行为回归与缓存优化耦合

将动态状态后移后，确认阶段出现了 `confirmation_status_mismatch`。这不是缓存观测问题，而是状态摘要设计问题，说明：

- 任何“前缀稳定化”改造都可能影响模型对会话阶段的理解
- 缓存优化不能只看 token，要同时观察行为副作用

### 8.2 SDK typed model 与供应商扩展字段不一致

这是本轮最关键的坑：

- 文档里有字段
- 原始响应体里有字段
- 但 SDK typed model 不一定稳定暴露这些字段

因此对于供应商扩展 usage 字段，不能假设 SDK 一定完整映射。

### 8.3 live eval 行为指标有噪声

不同轮次 live eval 会出现轻微波动，表现为：

- 29/30
- 30/30
- 某单项 confirmation 偶发失配

所以如果目标是缓存收益，应该把行为指标作为护栏，而不是作为主结论来源。

---

## 9. 最终结论

本轮缓存优化的主要成果不是“把 prompt tokens 绝对值立刻打下来”，而是完成了三件更关键的事：

1. **让 system 前缀更稳定**，为 KV Cache 命中创造了更合理的结构条件
2. **打通了 DeepSeek KV Cache 指标采集链路**，从 raw response 到 final report 全链路可见
3. **在 live eval 中拿到了可引用的缓存命中数据**：`prompt_cache_hit_ratio=0.9552`

换句话说，本轮最大的交付是：

> 项目现在不仅“尝试利用 KV Cache”，而且已经能够“量化自己到底命中了多少缓存”。

---

## 10. 后续建议

### 10.1 下一轮继续做真正的缓存增益实验

现在观测链路已经通了，下一轮可以做更纯粹的缓存收益实验，例如：

- 对比“状态摘要长版 vs 精简版”
- 对比“tool schema 完整版 vs 压缩版”
- 对比“不同 prompt 组织方式”

核心观察指标：

- `prompt_cache_hit_ratio`
- `prompt_cache_miss_tokens`
- `prompt_tokens`
- `average_latency_seconds`

### 10.2 对 provider 保持 raw usage 优先策略

只要继续依赖 DeepSeek 的扩展 usage 字段，就建议保留：

- raw response usage 优先
- typed usage fallback

避免未来 SDK 升级或字段变动时再次丢失观测能力。

### 10.3 将 cache 指标纳入常规优化报告

后续所有 prompt / schema / context 优化工作，建议在报告中固定包含：

- `prompt_cache_hit_ratio`
- `prompt_cache_hit_tokens`
- `prompt_cache_miss_tokens`

否则很难区分：

- 是 prompt 结构更优导致 token 更少
- 还是因为缓存命中更高导致实际成本更低

---

## 11. 涉及文件

本轮缓存优化与观测链路相关的关键文件如下：

- `app/agent/llm_agent.py`
- `app/agent/context_builder.py`
- `app/agent/providers.py`
- `app/eval/runner.py`
- `app/eval/metrics.py`
- `tests/test_providers.py`
- `tests/test_eval_runner.py`
- `tests/test_context_builder.py`
- `tests/test_agent_core.py`

---

## 12. 一句话总结

这次工作的核心成果是：**把 DeepSeek KV Cache 从“理论可用”变成了“结构上更可命中、指标上可观测、报告中可量化”。**
