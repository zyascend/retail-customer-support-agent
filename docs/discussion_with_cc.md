# 完善架构设计文档

> [discussion-llm-agent-architecture.md](docs/discussion-llm-agent-architecture.md) 我准备改下架构 进行一轮讨论 输出了讨论后的设计文档 你看看 有没有需要优化的，补充的，细化的。

<details><summary>8 previous messages</summary>

> 我会先用 `brainstorming` 技能来把这份架构讨论文档当成设计输入审一遍：先看现有内容，再从边界、可演进性、风险和落地细节几条线补建议。
>
> <details><summary>Explored a file, ran a command</summary>
>
> <details><summary>Explored 2 files</summary>
>
> - Read `~/.codex/skills/brainstorming/SKILL.md`
> - Read `./docs/discussion-llm-agent-architecture.md`
>
> </details>
>
> - Ran `git status --short`
>
> </details>
>
> 我已经看完讨论记录了。接下来我会再对照实际产出的设计文档和项目结构看一眼，重点找“决策已经对，但文档还没落到可执行边界”的地方。
>
> <details><summary>Explored a file, a list, ran a command</summary>
>
> <details><summary>Explored a file, a list</summary>
>
> - Read `./docs/design-llm-agent-tool-calling.md`
> - Listed files
>
> </details>
>
> - Ran `git log --oneline -5`
>
> </details>
>
> 这份设计方向整体是清楚的：你们已经把“LLM 做决策，code 做边界和账本”这个主轴定下来了。为了避免建议悬浮，我再快速抽样看几个现有核心模块，确认哪些建议会真正影响落地。
>
> <details><summary>Explored 4 files</summary>
>
> - Read `./app/agent/runtime.py`
> - Read `./app/agent/models.py`
> - Read `./app/tools/gateway.py`
> - Read `./app/agent/guard.py`
>
> </details>
>
> 我这边的判断已经比较稳定了：设计文档不是“方向不够”，而是有几处需要补成工程契约，否则实现时容易把 LLM-agent 的自由度和可测性绞在一起。我再取一下行号，方便你后面直接改文档。
>
> <details><summary>Explored 4 files</summary>
>
> - Read `./docs/design-llm-agent-tool-calling.md`
> - Read `./app/tools/registry.py`
> - Read `./app/agent/providers.py`
> - Read `./app/agent/action_specs.py`
>
> </details>
</details>

整体方向我觉得是对的：把 agent 从“code 推断意图 + handler 执行”改成“LLM 决策 + gateway/guard 执行边界”，这是这类客服 agent 更自然的形态。现在最值得补的不是大方向，而是几个工程契约，否则实现时会卡在模式切换、确认流、tool schema 和 eval 可重复性上。

我建议优先补这几处：

1. **`deterministic` 保留与删除旧 pipeline 有冲突**
   文档一边说保留 `--mode deterministic` 走现有 12-node pipeline，另一边说删除 `pipeline.py`、`plan_handlers.py`、`graph.py`。这两件事不能同时成立。见 [design doc](./docs/design-llm-agent-tool-calling.md:150) 和 [删除模块](./docs/design-llm-agent-tool-calling.md:222)。
   建议明确成两阶段：先双模式共存，旧 pipeline 不删；等 LLM 模式 eval 达标后，再删除旧 pipeline，或把 deterministic fallback 降级为更小的 emergency fallback。

2. **需要定义 `ToolCallResponse` / tool message 的标准结构**
   现在写了 `chat_with_tools(messages, tools) -> ToolCallResponse`，但没有定义返回结构。建议补清楚：assistant content、tool_calls、tool_call_id、arguments JSON 解析失败、finish_reason、token_usage、provider raw metadata。
   这会直接影响 `step_llm_reason()`、trace、eval 统计和 DeepSeek/OpenAI 兼容层。

3. **确认流要再细化**
   文档说 guard 返回 `explicit_confirmation_required` 后设置 `pending`，但需要写清楚 pending 里保存什么：原始 tool name、arguments、用户可读摘要、idempotency/resource lock 是否提前生成、下一轮 confirm 时是否重新跑 guard。
   我的建议：confirm 后仍然重新跑 `gateway.execute(..., confirmed=True)`，不要信任 pending 里的旧验证结果；pending 只保存用户确认的候选动作和摘要。

4. **Unknown tool / malformed args 要变成结构化 tool result，不要抛异常**
   文档说 registry 拒绝幻觉工具，但最好明确：未知工具、参数 JSON 解析失败、缺 required 参数，都返回可喂回 LLM 的结构化错误，而不是让 loop 直接崩。这样 LLM 有一次自我修正机会，连续失败保护再兜底。

5. **Tool schema 生成要从“文本 catalog”升级成真正 JSON Schema 契约**
   现在文档提到 OpenAI function calling schema，但还需要补：required 字段、enum 值，比如 cancellation reason、shipping_method；数组字段类型；description；additionalProperties 策略。
   特别是 `reason` 交给 LLM 映射没问题，但 schema/guard 要一起约束允许值。

6. **State 拆分后，trace/eval 应该明确同时记录 SessionState + TurnContext**
   `TurnContext` 不持久化是对运行态而言，但 trace artifact 仍然应该记录本轮 steps、durations、token、termination。建议文档里写成：“不进入跨轮 session 序列化，但进入 run trace”。

7. **`state_summary` 需要一份预算和格式规范**
   现在只说压缩上下文。建议补：最大 token 预算、包含哪些字段、隐藏哪些 PII/大字段、订单摘要格式、最近 N 条消息策略、tool result 摘要策略。这个会极大影响稳定性和成本。

8. **Eval 适配还缺“负向断言”**
   只用 `required_tools` 可能不够。建议加 `forbidden_tools` 或 `expected_no_write` 继续作为强断言，防止 LLM 多调用了危险写工具但最后结果碰巧对。DB 断言保留很好，但工具层负向断言也有价值。

9. **Prompt 版本和策略同步要有校验**
   单文件 prompt 是对的，但建议补一个轻量测试：确认 prompt 中 tool 名称和 registry 一致，policy 文件能加载，模板变量全部替换，无 `{state_summary}` 这种残留。

如果只改设计文档，我会先补一个“关键工程契约”章节，包含：`ToolCallResponse`、`PendingAction` 确认协议、tool error schema、state_summary 预算、双模式迁移边界。这样这份设计就不只是方向正确，而是可以直接拆 implementation plan 了。

> 我觉得 可以不留deterministic 模式了 你觉得呢

我倾向：**可以不留 deterministic 模式**，而且这可能更干净。

但我会把它拆成一句更精确的原则：

**不保留旧 12-node deterministic runtime；保留 deterministic 的测试桩、guard、gateway、pre-flight 和 trace/eval 能力。**

理由很直接：

1. **双架构会拖累重构**
   如果 `--mode deterministic` 继续存在，你就会被迫维护旧 `pipeline.py / plan_handlers.py / graph.py` 的接口、state 字段和 eval 语义。那新架构的 `SessionState + TurnContext`、tool-calling loop、prompt contract 都会被旧系统牵着走。

2. **学习目标更一致**
   既然这轮目标是 LLM tool-calling agent architecture，就应该让主路径真正成为 LLM loop，而不是“新路径 + 旧路径兜底”。否则很多关键问题会被绕开，比如 tool schema、malformed tool call、confirmation pending、LLM eval 波动。

3. **fallback 不应该是旧 agent，而应该是安全降级**
   LLM 故障时，合理兜底是：
   - 读操作失败：提示稍后再试或转人工
   - 写操作失败：绝不执行，转人工或要求重试
   - provider 不可用：明确返回 service unavailable / human handoff
   而不是偷偷走另一套旧决策系统。

我建议文档改成这样：

```text
删除 --mode deterministic 作为生产/运行时模式。
保留 deterministic test harness：
- FakeToolCallingProvider / ScriptedProvider 用于单元测试 agent loop
- guard/gateway/pre-flight 继续 deterministic
- eval 可用固定 LLM transcript 或 mock provider 做稳定回归
```

也就是说，**删旧 pipeline，但别删可重复测试能力**。

唯一要注意的是：当前很多 eval 可能依赖无 API key 也能跑。如果删 deterministic runtime，需要补一个 `FakeToolCallingProvider`，让测试仍然离线可跑。这个比保留 12-node pipeline 更轻，也更贴近新架构。

所以我的推荐结论是：

**删。旧 deterministic pipeline 不留。测试层保留 deterministic mock。LLM 不可用时走安全失败/转人工，不走旧架构 fallback。**

> 对对对 你提到了harness 这是一个很重要的设计原则

对，这个点很关键。可以把它提升成整份架构设计里的一个原则：

**Runtime 单一，Harness 多样。**

也就是：

- **Runtime 只保留 LLM tool-calling agent 一条主路径**
  不再维护旧 12-node deterministic pipeline，也不保留 `--mode deterministic` 作为同级架构。

- **Determinism 放在 harness 层解决**
  单测、eval、回放、调试、CI 都可以用可控 provider、固定 tool-call transcript、mock gateway、trace replay 来获得稳定性。

- **Fallback 只做安全失败，不做旧架构代跑**
  LLM 不可用时，系统应该拒绝危险写操作、转人工、或返回明确失败，而不是退回另一套隐藏决策系统。

我会建议在设计文档加一节：

```markdown
## Runtime / Harness 边界

核心原则：Runtime 单一，Harness 多样。

生产 runtime 只保留一条 LLM tool-calling 路径：
pre-flight → agent loop → gateway/guard → post-processing。

不保留旧 deterministic pipeline，也不保留 `--mode deterministic`。

Deterministic 能力下沉到测试与评估 harness：
- `ScriptedToolCallingProvider`：按脚本返回固定 tool calls / assistant text
- `FakeFailingProvider`：模拟 timeout、malformed JSON、unknown tool、重复失败
- `TraceReplayHarness`：从 trace artifact 回放某一轮消息与工具结果
- `EvalHarness`：支持 live LLM、scripted LLM、trace replay 三种后端

这样 CI 可以稳定，生产架构也不会被旧 pipeline 牵制。
```

这个原则还能顺手解决你文档里的一个矛盾：
之前“删除 pipeline”与“保留 deterministic mode”冲突。现在改成：

**删除 deterministic runtime；新增 deterministic harness。**

这非常漂亮，边界一下就清楚了。

> 对对 这是一个正确的选择 然后按你的建议进行优化上面的问题时  你还有要和我讨论确定的么

<details><summary>1 previous message</summary>

> 我继续按 `brainstorming` 的方式处理：先把剩下需要拍板的架构分歧收束掉，避免一会儿改文档时把实现策略写死在我自己的假设里。
</details>

需要，但不多。大的方向已经定了，我觉得只剩这几件值得你拍板：

1. **Harness 范围**
   我的默认建议：第一版必须有 `ScriptedToolCallingProvider` 和 `FakeFailingProvider`；`TraceReplayHarness` 可以写进设计，但放到后续步骤。
   原因是前两个直接保证 CI 和单测稳定，trace replay 更像调试增强。

2. **CI / Eval 分层**
   我的默认建议：
   - CI 只跑 deterministic harness，不打真实 LLM API
   - live LLM eval 手动或 nightly 跑
   - benchmark report 里区分 `scripted`、`live`、`replay`

3. **LLM 故障策略**
   我的默认建议：不 fallback 到旧 runtime。API 不可用、连续失败、malformed tool call 超限时，统一安全失败或转人工；写操作绝不执行。

4. **Malformed / unknown tool call 修正机会**
   我的默认建议：未知工具、参数 JSON 错误、缺 required args 都先作为 tool error 喂回 LLM，让它自修正；连续 3 次失败才中断。

5. **确认流**
   我的默认建议：`pending_action` 只保存候选动作和用户可读摘要。用户确认后必须重新走 `gateway.execute(..., confirmed=True)`，guard 重新校验，不信任旧结果。

6. **旧代码删除节奏**
   我的默认建议：设计上明确“最终删除旧 pipeline”，实施上可以在同一个 PR/阶段里删除，但前提是 scripted harness 已经覆盖核心 loop 场景。

我觉得最需要你确认的是第 1 个：

**第一版 harness 要做到什么程度？我推荐先做 `ScriptedToolCallingProvider + FakeFailingProvider`，把 `TraceReplayHarness` 写进设计但不作为第一阶段必做。你觉得这样合适吗？**

> 可以不第一阶段做

好，那我把 harness 原则收束成：

**第一阶段必做：**
- `ScriptedToolCallingProvider`
- `FakeFailingProvider`
- CI / 单测基于这两类 fake provider 保持稳定

**设计里保留但不进第一阶段：**
- `TraceReplayHarness`
- 更完整的 replay/debug workbench

下一个我觉得要确认的是 **CI / Eval 分层**：

我的建议是 **CI 不打真实 LLM API**，只跑 deterministic harness；真实 LLM eval 作为手动命令或 nightly benchmark，并且 report 明确标记 `scripted` / `live`。

你觉得 live LLM eval 要不要进常规 CI？我倾向不要。

> 建议的理由是什么呢

我倾向 **live LLM eval 不进常规 CI**，理由主要是这几个：

1. **CI 应该验证代码回归，不应该被模型波动污染**
   live LLM 输出会受模型版本、服务状态、采样、上下文细节影响。一次失败不一定代表代码坏了，容易让 CI 信号变脏。

2. **成本和速度不可控**
   你现在 eval case 数量已经不少，后面还会增长。每次 push 都打真实 API，会变慢、变贵，也容易碰 rate limit。

3. **失败定位困难**
   如果 CI 红了，你需要先判断是代码问题、prompt 问题、模型行为漂移、网络问题、provider 故障，还是限流。这个反馈环太慢。

4. **常规 CI 更适合 deterministic contract**
   比如 tool schema 是否正确、guard 是否拦截、pending flow 是否安全、unknown tool 是否可恢复、loop 是否超限，这些都能用 scripted/fake provider 稳定验证。

5. **live eval 更像质量监控，不是每次提交的门禁**
   它适合手动跑、nightly 跑、或发布前跑。指标看趋势：成功率、平均 tool calls、token、延迟、失败类别。它不是“这次 commit 能不能合”的唯一判断。

所以我建议分层：

```text
PR / 常规 CI:
  pytest + scripted provider + fake failing provider
  目标：稳定验证架构契约和安全边界

Nightly / 手动:
  live LLM eval
  目标：观察真实模型效果、prompt 质量、支持率、成本和延迟

Release gate:
  可选跑 live smoke，比如 5-10 个关键 happy path / dangerous write path
```

这样你既不会失去真实模型质量反馈，也不会让日常开发被非确定性拖住。

> okok

好，那这个决策也可以定下来：

**CI / Eval 分层原则：**

- **常规 CI 不调用真实 LLM API**
- CI 只跑 deterministic harness：
  - `ScriptedToolCallingProvider`
  - `FakeFailingProvider`
  - guard / gateway / pre-flight / context builder / eval adapter 单测
- **live LLM eval 不作为普通提交门禁**
- live eval 放到：
  - 手动命令
  - nightly benchmark
  - release 前小规模 smoke
- eval report 必须标记 backend：
  - `scripted`
  - `live`
  - 后续可加 `replay`

下一个我建议确认的是 **LLM 故障策略**。

我的默认建议是：
**LLM/provider 故障时不 fallback 到旧 deterministic runtime；只做安全失败或转人工。写操作在 LLM 故障时绝不执行。**

也就是：
- provider timeout / unavailable → 返回暂时无法处理或转人工
- malformed tool call 连续超限 → 中断并转人工
- unknown tool 连续超限 → 中断并转人工
- 写操作没拿到明确合法 tool call + guard allow + user confirmation → 不执行

这个你应该也会同意，但它是安全边界，最好明确拍板。确认吗？

> 确认

确认，记下来：

**LLM 故障策略：安全失败，不旧路代跑。**

具体规则：

- 不 fallback 到旧 deterministic runtime
- provider timeout / unavailable：返回暂时无法处理，或转人工
- malformed tool call / unknown tool / missing args：先给 LLM 自修正机会
- 连续失败超过阈值：中断并转人工
- 写操作必须同时满足：
  - 合法 tool call
  - 参数 schema 通过
  - gateway/guard allow
  - 用户显式确认
- 任一条件不满足：不执行写操作

这条和前面的 **Runtime 单一，Harness 多样** 是一组，非常稳。

最后还有两个小决策值得确认：

1. **Malformed / unknown tool 修正次数**
   我建议：单轮最多连续 3 次 tool-call 执行失败，之后中断转人工。

2. **确认流 guard 重跑**
   我建议：`pending_action` 只保存候选动作，不保存“已通过的 guard 结果”。用户确认后重新执行 `gateway.execute(..., confirmed=True)`，guard 再校验一次。

这两个可以一起定吗？我的建议是都采用。

> 确认采用

好，这两个也定下来：

**Tool-call 失败修正：**
- unknown tool / malformed JSON / missing required args / tool execution error，先作为结构化 tool error 喂回 LLM
- 单轮连续失败最多 3 次
- 超过阈值后中断，安全失败或转人工
- 不执行任何未通过 schema + gateway + guard 的写操作

**确认流：**
- `pending_action` 只保存候选动作和用户可读摘要
- 不保存“guard 已通过”这种状态
- 用户下一轮确认后，重新调用 `gateway.execute(..., confirmed=True)`
- guard 必须重新校验认证、ownership、read-before-write、policy、lock、idempotency
- 只有重新校验通过，才执行写工具

我觉得现在架构决策已经足够完整，可以把设计文档优化掉了。
我会改 [docs/design-llm-agent-tool-calling.md](./docs/design-llm-agent-tool-calling.md)，重点补：

- Runtime 单一，Harness 多样
- 删除 deterministic runtime，保留 deterministic harness
- CI / live eval 分层
- Tool-call response / error contract
- LLM 故障安全失败策略
- pending confirmation protocol
- state_summary 预算和 trace 规则
- 修正旧 pipeline 删除与 fallback 的冲突

确认我直接改文档吗？

> 改

<details><summary>10 previous messages</summary>

> 收到，我直接改设计文档。会把刚才拍板的原则写成架构约束，并同步清掉“保留 deterministic runtime”和“删除旧 pipeline”之间的矛盾。
>
> <details><summary>Explored a file, ran a command</summary>
>
> - Ran `wc -l docs/design-llm-agent-tool-calling.md`
>
> <details><summary>Explored a file</summary>
>
> - Read `./docs/design-llm-agent-tool-calling.md`
>
> </details>
>
> </details>
>
> 我会做一次文档级重写而不是小补丁：新增几个明确契约章节，并把实施步骤从“双模式迁移”改成“单 runtime + deterministic harness”。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./docs/design-llm-agent-tool-calling.md` (+185 -14)
>
> </details>
>
> 文档主体已经改完了。现在我做一轮自检，找是否还有旧 deterministic fallback 的残留、结构前后矛盾，顺手看一下 diff。
>
> <details><summary>Explored a file, a search, ran a command</summary>
>
> <details><summary>Explored a file, a search</summary>
>
> - Read `./docs/design-llm-agent-tool-calling.md`
> - Searched for `deterministic|fallback|code-only|双模式|--mode|pipeline|TraceReplay|Scripted|FakeFailing|provider 不可用` in `design-llm-agent-tool-calling.md`
>
> </details>
>
> - Ran `git diff -- docs/design-llm-agent-tool-calling.md`
>
> </details>
>
> 自检里发现一个小语义问题：“Code Fallback”这个标题容易让人误会成还有旧 runtime 兜底。我会顺手把它改成“安全失败”，再把“不可改动模块”这个标题改得更准确一点，避免表格里出现“保留但扩展”的矛盾。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./docs/design-llm-agent-tool-calling.md` (+2 -2)
>
> </details>
>
> 我已经把容易误导的措辞也修了。最后再跑一次文档扫描，确认没有旧双模式残留，然后给你一个简短总结。
>
> <details><summary>Explored a search, ran 3 commands</summary>
>
> <details><summary>Explored a search</summary>
>
> - Searched for `双模式|code-only|Code Fallback|保留当前|--mode deterministic|降级到旧|deterministic runtime` in `design-llm-agent-tool-calling.md`
>
> </details>
>
> - Ran `git diff --stat -- docs/design-llm-agent-tool-calling.md`
>
> - Ran `git diff -- docs/design-llm-agent-tool-calling.md | sed -n '1,260p'`
>
> - Ran `git status --short docs/design-llm-agent-tool-calling.md docs/discussion-llm-agent-architecture.md && wc -l docs/design-llm-agent-tool-calling.md`
>
> </details>
</details>

改好了：[docs/design-llm-agent-tool-calling.md](./docs/design-llm-agent-tool-calling.md)

我主要补强了这些设计点：

- 加入核心原则：**Runtime 单一，Harness 多样**
- 明确删除 `--mode deterministic` runtime，不再保留旧 12-node pipeline 作为 fallback
- deterministic 能力下沉到 harness：`ScriptedToolCallingProvider`、`FakeFailingProvider` 第一阶段必做，`TraceReplayHarness` 后续
- 补了 CI / live eval 分层：常规 CI 不打真实 LLM，live eval 放手动、nightly、release smoke
- 补了 LLM 故障策略：安全失败或转人工，不旧路代跑，写操作故障时绝不执行
- 补了 tool-call error contract、连续失败 3 次中断
- 补了 pending confirmation 协议：确认后必须重新跑 guard
- 补了 tool schema、provider response、state_summary、trace、eval backend / forbidden tools 等工程契约
- 修掉了之前“删除旧 pipeline”和“保留 deterministic mode”的冲突

这是文档修改，没有跑测试。另：这两个文档目前都是 git untracked 状态。

> 可以 开始设计spec了

<details><summary>16 previous messages</summary>

> 我会把刚才已经拍板的架构决策整理成正式 spec，而不是重新打开所有问题。先快速对齐现有 spec 的格式，再落到 `docs/superpowers/specs/` 里。
>
> <details><summary>Explored 2 files, ran a command</summary>
>
> <details><summary>Explored 3 files</summary>
>
> - Read `~/.codex/skills/brainstorming/SKILL.md`
> - Read `./docs/design-llm-agent-tool-calling.md`
> - Read `./docs/superpowers/specs/2026-06-13-phase9.2-full-tau-ingestion-design.md`
>
> </details>
>
> - Ran `git status --short`
>
> </details>
>
> 我会把它做成正式、可评审的 spec 文件，路径沿用项目已有规范：`docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`。内容会比讨论文档更像实施前的契约：目标、非目标、组件、数据流、错误处理、测试与验收。
>
> <details><summary>Created a file</summary>
>
> - Wrote `./docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md` (+718 -0)
>
> </details>
>
> Spec 初稿已经落盘。我现在做自审：扫占位符、内部矛盾、范围过大点，以及和刚刚讨论文档是否一致。
>
> <details><summary>Explored a file, ran 2 commands</summary>
>
> <details><summary>Explored a file</summary>
>
> - Read `./docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`
>
> </details>
>
> - Ran `wc -l docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`
>
> <details><summary>Explored a file</summary>
>
> - Read `./docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`
>
> </details>
>
> - Ran ``rg -n "TBD|TODO|待定|保留 `--mode deterministic`|code-only|旧.*fallback|第一阶段.*TraceReplay|不进常规 CI|deterministic pipeline" docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md``
>
> </details>
>
> 自审里撞到一个 shell 反引号的小插曲，不影响文件。内容上我发现两处可以更清楚：`parsers.py` 不能整文件删除又说保留 helper；还有 Python 示例用了可变默认值，作为 spec 不该给未来实现埋坑。我马上修掉。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md` (+15 -15)
>
> </details>
>
> 我把 spec 示例里的可变默认值改成 `Field(default_factory=...)`，也把“删除/精简”边界改清楚了。再做最后一遍扫描和状态检查。
>
> <details><summary>Explored a search, ran 2 commands</summary>
>
> <details><summary>Explored a search</summary>
>
> - Searched for ``TBD|TODO|待定|code-only|旧.*fallback|保留 `--mode deterministic`|第一阶段.*TraceReplay|= \[\]|= \{\}|= set\(\)`` in `2026-06-13-llm-agent-tool-calling-architecture-design.md`
>
> </details>
>
> - Ran `git status --short`
>
> - Ran `git diff -- docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md | sed -n '1,260p'`
>
> </details>
>
> Spec 自审通过了：没有 TBD/TODO，也没有旧双模式的残留矛盾。按照这个项目的 spec 流程，我会只把新 spec 文件单独提交，其他未跟踪讨论文档先保持原样。
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `git branch --show-current`
> - Ran `git status --short`
>
> </details>
>
> 当前在 `design/llm-agent-tool-calling` 分支。我现在只 stage 新的正式 spec 文件，不碰那几个讨论文档。
>
> <details><summary>Ran a command</summary>
>
> - Ran `git add docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md && git status --short`
>
> </details>
>
> 正式 spec 已经 staged。接下来我按 brainstorming 流程把 spec 提交掉，然后请你评审；等你确认后再进入 implementation plan。
>
> <details><summary>Ran a command</summary>
>
> - Ran `git commit -m "docs: add llm agent tool-calling architecture spec"`
>
> </details>
</details>

Spec 已经写好并提交了：

[docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md](./docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md)

提交：`8a25e0e docs: add llm agent tool-calling architecture spec`

我做了自审：没有 TBD/TODO；已明确“Runtime 单一，Harness 多样”；删掉 deterministic runtime，不把旧 pipeline 当 fallback；第一阶段 harness 只包含 `ScriptedToolCallingProvider` 和 `FakeFailingProvider`，`TraceReplayHarness` 放后续。

另外我只提交了正式 spec 文件；这几个讨论文档还保持 untracked：`docs/design-llm-agent-tool-calling.md`、`docs/discussion-llm-agent-architecture.md`、`docs/discussion_with_cc.md`。

请你先 review 这个 spec。你确认后，我们再进入 implementation plan。

> ok 实现上可以拆成长期路径 分为多个阶段 不一定要在一个session里完成

<details><summary>15 previous messages</summary>

> 明白，这个约束很重要：实现计划不应该假装“一口气重构完”。我会用 `writing-plans` 技能把它拆成长期路径，每个阶段都能独立验证、能停、能恢复。
>
> <details><summary>Explored a file</summary>
>
> - Read `~/.codex/skills/writing-plans/SKILL.md`
>
> </details>
>
> 我会先把 plan 做成“多阶段长期路线图 + 第一阶段可执行任务”。这样既不把大重构塞进一个 session，也不会让后续执行者没落点。
>
> <details><summary>Explored 4 files</summary>
>
> - Read `./docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`
> - Read `./docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`
> - Read `./docs/superpowers/plans/2026-06-13-phase9.2-full-tau-ingestion.md`
> - Read `./docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`
>
> </details>
>
> 我会把这个做成“master implementation plan”：先定义长期阶段和退出条件，再把 Phase 1 写到足够可执行；后续每个阶段开始前可以再生成更细的阶段计划。这样不会把 5 个阶段硬塞进一次执行。
>
> 我会刻意避免“后续再说”这种模糊说法：每个阶段都会有明确目标、退出条件和验证命令；但只有 Phase 1 展开到可直接开工的 checkbox 粒度。
>
> <details><summary>Created a file</summary>
>
> - Wrote `./docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md` (+1079 -0)
>
> </details>
>
> 长期计划已经写出来了。现在我做自审，重点检查有没有把后续阶段写得太虚、有没有 TODO 占位、以及 Phase 1 的代码片段和当前文件结构是否对得上。
>
> <details><summary>Explored 3 files, a search</summary>
>
> - Searched for `TBD|TODO|implement later|fill in|appropriate|Similar to|Phase 1.*TraceReplay|常规 CI.*真实|= \[\]|= \{\}|= set\(\)` in `2026-06-13-llm-agent-tool-calling-architecture.md`
> - Read `./docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md`
> - Read `./docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md`
> - Read `./docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md`
>
> </details>
>
> 自审发现一个小坑：Phase 1 Task 1 的测试文件一开始引入了 `pytest`，但那一阶段还没用到，会让 focused lint 红。我会修成每个阶段都能单独过 lint。
>
> <details><summary>Edited a file</summary>
>
> - Wrote `./docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md` (+3 -3)
>
> </details>
>
> 我修了 lint 细节。再做最后状态检查，然后把 plan 提交到当前分支。
>
> <details><summary>Explored a search, ran 2 commands</summary>
>
> <details><summary>Explored a search</summary>
>
> - Searched for `TBD|TODO|implement later|fill in|appropriate|Similar to|Iterable|import pytest` in `2026-06-13-llm-agent-tool-calling-architecture.md`
>
> </details>
>
> - Ran `wc -l docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md`
>
> - Ran `git status --short`
>
> </details>
>
> Plan 自审干净，`import pytest` 现在只出现在需要异常断言的 Task 2 追加块里。接下来我只 stage/commit 这个 plan 文件。
>
> <details><summary>Ran a command</summary>
>
> - Ran `git add docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md && git commit -m "docs: add LLM tool-calling architecture implementation plan"`
>
> </details>
</details>

实现计划已经按“长期路径、多阶段、可中断恢复”的方式写好并提交了：

[docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md](./docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md)

提交：`ccac9c7 docs: add LLM tool-calling architecture implementation plan`

计划结构是：

- Phase 1：tool-calling contract、JSON schema、`ScriptedToolCallingProvider` / `FakeFailingProvider`，不改 runtime
- Phase 2：`SessionState` / `TurnContext` 和 `ContextBuilder`
- Phase 3：独立实现 LLM agent loop
- Phase 4：切换 `AgentRuntime`，删除旧 runtime
- Phase 5：eval / live benchmark 分层
- Phase 6：后续 trace replay harness

我把 Phase 1 展开到了可直接执行的 checkbox 粒度；Phase 2-6 保留为 planning brief，等前一阶段完成后再单独生成更细计划。这样不会把整个架构迁移塞进一个 session，节奏更稳。

> 改成中文

<details><summary>8 previous messages</summary>

> 我会用 `writing-plans` 的格式约束来改这个计划文档：主要把说明、阶段、任务、预期结果都转成中文，代码片段和命令保持原样，避免破坏可执行性。
>
> <details><summary>Explored a file</summary>
>
> - Read `~/.codex/skills/writing-plans/SKILL.md`
>
> </details>
>
> 我会直接把已提交的 implementation plan 文档翻成中文版本，并保留代码块、命令、文件路径和测试断言的可执行性。翻译完我会做一轮扫描，确认没有明显英文说明残留或占位符。
>
> <details><summary>Created a file</summary>
>
> - Wrote `./docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md` (+1079 -0)
>
> </details>
>
> 计划文档已经整体中文化了，代码块、命令和 commit message 保持英文以便直接执行。现在我做一轮扫描，确认没有不该残留的英文说明和占位符，然后提交这个文档更新。
>
> <details><summary>Explored a search, ran 2 commands</summary>
>
> <details><summary>Explored a search</summary>
>
> - Searched for `TBD|TODO|implement later|fill in|appropriate|Similar to|Expected:|Run:|Goal:|Architecture:|Tech Stack:|Long-Term|Task [0-9]:|Step [0-9]:` in `2026-06-13-llm-agent-tool-calling-architecture.md`
>
> </details>
>
> - Ran `git diff -- docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md | sed -n '1,260p'`
>
> - Ran `git status --short`
>
> </details>
>
> 扫描没有发现占位符或英文模板标题残留。现在我提交中文化修改。
>
> <details><summary>Ran a command</summary>
>
> - Ran `git add docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md && git commit -m "docs: translate LLM tool-calling plan to Chinese"`
>
> </details>
</details>

已改成中文并提交：

[docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md](./docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md)

提交：`f04c8fb docs: translate LLM tool-calling plan to Chinese`

我保留了代码块、命令、文件路径和 commit message 的英文，确保计划仍然可以直接执行。
