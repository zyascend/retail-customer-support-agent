# Skill 资产化技术优化复盘

## 1. 背景

本项目是一个面向零售售后场景的 LLM tool-calling agent。它需要在多轮对话中完成：

- 查询订单状态
- 取消 pending 订单
- 修改 pending 订单地址 / 商品 / 支付方式 / 配送方式
- 退货 delivered 商品
- 换货 delivered 商品
- 修改用户默认地址
- 超范围请求转人工

随着功能逐步扩展，项目中关于“某类写操作应该怎么做”的行为知识分散到了多个层级：

1. `app/agent/action_specs.py` — 写操作元数据（intent、required_args、risk）
2. `prompts/llm_agent_system_v001.md` — 写操作规则、few-shot 示例
3. `app/tools/registry.py` — tool description 后缀中的行为约束
4. `app/agent/llm_agent.py` — premature refusal map、observation enrichment、response correction 等运行时补丁逻辑

这种分散式知识组织在功能少的时候还能工作，但有两个问题：

- **维护成本上升**：修改某类能力时，需要同时修改 prompt、schema 描述、eval case、甚至局部兜底逻辑
- **评测归因困难**：当某轮优化导致“退货”能力回退时，只能看到整体 pass rate 下降，无法快速定位是哪个能力单元出了问题

因此，这一轮优化的目标是把这些高频写操作的行为知识收敛成一层可版本化、可复用、可评测的 Skill 资产。

---

## 2. 问题定义

### 2.1 行为知识分散，改一处容易漏一处

在优化前，以 `exchange_delivered_order_items` 为例：

- 操作本身的 required args 和 risk 在 `action_specs.py`
- 什么时候该调用它、什么时候不该调用它，在 system prompt 的 `Write Requests` / `Examples`
- tool schema 的文字约束又在 `registry.py` 的 description 拼接逻辑
- 金额类 follow-up 的补充知识，还散落在 `llm_agent.py` 的 observation enrichment / correction 方法里

结果就是：

- 改 prompt，不一定同步改 tool 描述
- 补新 few-shot，不一定同步到评测标签
- 新增 bad case 后，很难说这是“某个 Skill 退化了”，还是系统整体 drift 了

### 2.2 Eval 只能看整体，不容易按能力拆开

现有 eval 体系已经很完整，支持：

- `curated_mvp`
- `generalized_mvp`
- `synthetic_seeded_v1`
- `generalization`
- `tau_*`

但评测结果主要按这些维度展开：

- subset
- case_id
- category
- failure_label
- scenario_family / variant_type / language_variation_level

缺少一个直接表达“这是哪类能力”的稳定维度。比如：

- `cancel_order`
- `return_items`
- `exchange_items`
- `modify_payment`

这意味着：

- 改了换货提示词后，只能从 failed case 列表里人工判断影响面
- 很难形成“这个 Skill 本轮 pass rate 是否回退”的可观测信号

### 2.3 Prompt 里有经验，但不是工程资产

优化前，许多高价值经验确实已经存在，比如：

- 写操作必须先调 write tool，让 guard 决定
- 不要在第一次 write tool 调用前提前 ask confirmation
- 写成功后要继续完成剩余子任务
- 修改商品后不要再用 modify payment 去 cover replacement charges
- 退货 / 换货后要继续回答 total refund / price difference / gift card balance

但这些经验主要存在于：

- prompt 文本
- case 设计经验
- runtime 特殊兜底

它们更像“经验积累”，还不是“工程可管理资产”。

---

## 3. 优化目标

这一轮优化聚焦 Skill 资产化，不改底层执行架构。目标如下：

1. **结构目标**：把 8 个高频写操作沉淀为显式 Skill 定义
2. **提示词目标**：把写操作的规则和示例，从 prompt 主体中抽离到 Skill guidance
3. **评测目标**：让 eval 结果支持按 Skill 维度聚合
4. **版本目标**：为每个 Skill 生成稳定 hash，支持后续变更追踪

非目标：

- 不把 Agent Loop 改造成新的 workflow engine
- 不用 DSL 重写 Guard / ToolGateway / Runtime
- 不在这一轮引入 plan-execute 或多 Agent 架构
- 不尝试一次性消灭所有 `llm_agent.py` 中的行为补丁逻辑

换句话说，这一轮优化的原则是低侵入改造，优先做知识组织升级，而不是执行链路重构。

---

## 4. 优化思路

### 4.1 引入 SkillSpec，作为“行为资产单元”

新的 Skill 数据模型放在：

- `app/skills/spec.py`

核心字段包括：

- `skill_id`
- `display_name`
- `version`
- `description`
- `intent_patterns`
- `entry_tools`
- `required_reads`
- `guard_constraints`
- `prompt_guidance`
- `few_shot_examples`
- `risk`
- `related_action_specs`
- `tags`

它的设计意图不是取代 `action_specs.py`，而是补一层更上层的“方法资产”：

- `action_specs` 负责“这个写操作的底层执行规格是什么”
- `SkillSpec` 负责“这类请求在对话里应该怎么被处理”

### 4.2 引入 Skill Registry，统一收敛 8 个写操作能力

新的 Skill 注册表放在：

- `app/skills/registry.py`

本轮先覆盖 8 个写操作 Skill：

- `cancel_order`
- `modify_address`
- `modify_items`
- `modify_payment`
- `return_items`
- `exchange_items`
- `modify_user_address`
- `modify_shipping`

每个 Skill 都明确记录：

- 它匹配什么类型的用户请求
- 它通常会调用哪些工具
- 写前必须先读哪些事实
- 它受哪些 guard 约束
- 它应该给模型什么 guidance
- 它该配什么 few-shot 示例

这一步的收益是：

- 写操作经验不再只属于 prompt
- 也不再只属于 action spec
- 而是被提升成一层独立资产

### 4.3 将 prompt 中的写操作经验改为 Skill 动态注入

原来的 `prompts/llm_agent_system_v001.md` 中，写操作部分直接包含：

- Write Requests 规则
- 大量写操作示例
- 多步骤 continuation 场景

优化后：

- prompt 模板保留全局合同（Identity / Core Contract / Write Requests / Heuristics / Stop Conditions）
- 新增 `{skill_guidance}` 占位符
- Skill guidance 在 `AgentLoop._load_system_prompt_template()` 中动态注入

相关文件：

- `prompts/llm_agent_system_v001.md`
- `app/agent/llm_agent.py`

这样做的收益是：

- prompt 主体不再需要直接维护所有写操作示例
- 写操作经验的演进，转移到 Skill registry
- 同时保留 prompt 模板结构稳定，避免执行层被大幅扰动

### 4.4 让 eval 能按 Skill 聚合

为此，本轮改了三处：

1. `app/eval/cases.py`
   - `EvalCase` 新增 `skill_id`
   - 给现有写操作相关 case 打上 skill 标签

2. `app/eval/runner.py`
   - `EvalCaseResult` 新增 `skill_id`
   - 执行结果中透传 case 的 skill_id

3. `app/eval/metrics.py`
   - 新增 `compute_skill_metrics()`
   - 在总体 metrics 中新增 `skill_metrics`

这样，report 中除了总 pass rate，还能看到：

- `cancel_order` 的通过率
- `exchange_items` 的通过率
- `modify_payment` 的失败标签分布

### 4.5 为 Skill 增加变更可追踪 hash

在 `app/skills/registry.py` 中，为每个 Skill 计算稳定 hash：

- 基于 `intent_patterns`
- `entry_tools`
- `required_reads`
- `guard_constraints`
- `prompt_guidance`
- `few_shot_examples`

然后在：

- `app/eval/baseline.py`

把 `skill_hashes` 写入 `baseline_metadata`。

这样做之后，两次 eval run 可以回答一个之前回答不了的问题：

> 这次回归，究竟是哪个 Skill 定义发生了变化？

---

## 5. 实施过程

### 5.1 第一步：新增 Skill 数据模型

先新增：

- `app/skills/__init__.py`
- `app/skills/spec.py`

这一步先解决“Skill 长什么样”的问题，不触碰现有执行逻辑。

### 5.2 第二步：把 8 个写操作收敛成 Skill Registry

在 `app/skills/registry.py` 中定义 8 个 SkillSpec。

数据来源不是凭空重写，而是从现有实现中抽取：

- `action_specs.py` 的 required_args / risk / intent
- prompt 中的写操作规则和 few-shot
- `llm_agent.py` 中高价值的行为知识（例如 continuation / calculate / payment suppression）

这一步的重点是“收敛”，不是“发明新规则”。

### 5.3 第三步：重构 prompt 装配方式

原始 prompt 中的复杂写操作示例，被替换为：

- 全局 Write Requests 合同
- `## Skill Guidance`
- `{skill_guidance}` 动态占位符

同时保留少量跨 Skill 示例（如 status lookup / transfer），避免 prompt 完全失去 read / generic 示例。

### 5.4 第四步：把 skill_id 接入 eval case

接着改 `EvalCase`，新增 `skill_id` 字段，并给现有 case 标记：

- cancel / guard / confirmation 相关 case → `cancel_order`
- modify items / item block / item confirmation → `modify_items`
- exchange success / exchange block → `exchange_items`
- synthetic shipping → `modify_shipping`

这一步完成后，case 终于有了一个“能力单元”标签。

### 5.5 第五步：把 skill_id 透传进 eval result 和 metrics

接着打通：

- `EvalCase.skill_id`
- `EvalCaseResult.skill_id`
- `compute_skill_metrics()`
- report 中的 `metrics.skill_metrics`

并且保持兼容性：

- `EvalCaseResult.skill_id` 设为可选默认值，避免破坏旧测试构造器

### 5.6 第六步：把 skill_hashes 放进 baseline metadata

这一点很关键。它让 Skill 资产不只是“有定义”，而是：

- 有稳定签名
- 能参与 baseline 对比
- 能成为后续回归归因的一部分

### 5.7 第七步：补测试并修兼容性回归

新增：

- `tests/test_skill_registry.py`

覆盖：

- Skill registry 数量与 ID
- `build_skill_guidance_for_prompt()` 内容
- `skill_hashes()` 完整性
- `compute_skill_metrics()` 聚合逻辑
- `baseline_metadata` 中是否包含 `skill_hashes`

同时在回归测试中发现一个问题：

- `tests/test_agent_core.py` 会直接检查 prompt 模板是否包含 `total refund` / `price difference` / `continue with the remaining part of the original request` 这些锚点

因为这些示例被迁移到了 Skill 动态注入层，模板本身不再直接包含这些短语，导致测试失败。

修复方式不是把大段旧示例塞回去，而是在 `## Skill Guidance` 段增加一条简洁静态说明，保留这些关键 anchor。

这样既兼容旧测试，也不破坏 Skill 收敛目标。

---

## 6. 验证与实验结果

### 6.1 单元测试

通过：

- `tests/test_skill_registry.py`
- `tests/test_tool_schema.py`
- `tests/test_agent_core.py`

其中关键回归点：

- prompt 模板结构保持兼容
- tool schema 未受 Skill 引入影响
- 新增 Skill 层的 registry / hash / metrics 正常工作

### 6.2 定向 eval runner 测试

`tests/test_eval_runner.py` 全量在当前环境中较慢，因此采用定向回归方式验证：

- `baseline` 相关断言
- `metrics` 相关断言
- `failure_analysis` 相关断言
- 新增 `skill_metrics` 逻辑

结果通过，说明 eval 主链没有被 Skill 化破坏。

### 6.3 live eval：curated_mvp

命令：

```bash
uv run phase2-eval --subset curated_mvp --max-workers 1
```

结果：

- `11/11` 通过
- `pass_rate = 1.0`
- `db_accuracy = 1.0`
- `mutation_error_rate = 0.0`

这说明：

- Skill 资产化没有破坏 MVP 基线能力
- 底层 Guard / ToolGateway / AgentLoop 行为保持稳定

### 6.4 live eval：generalized_mvp

命令：

```bash
uv run phase2-eval --subset generalized_mvp --live --max-workers 10
```

结果：

- `29/30` 通过
- `pass_rate = 0.9667`
- `db_accuracy = 1.0`
- `mutation_error_rate = 0.0`

唯一失败用例：

- `block_exchange_unavailable_replacement`
- failure label: `wrong_tool`

从 trace 看，这个失败不是系统性破坏，而是模型 planning 波动：

- 预期：先调 `exchange_delivered_order_items`，再由 Guard 返回 `replacement_item_unavailable`
- 实际：模型先识别 replacement item unavailable，然后主动给用户推荐可用替代款式

这说明：

- Skill 资产化本身是稳的
- 但 `exchange_items` 这个 Skill 的 guidance 还可以继续收紧
- 尤其要强调：**当用户已经指定了 new_item_id 时，即使你知道 unavailable，也应先调 write tool，让 Guard 决定**

---

## 7. 优化收益

### 7.1 结构收益：知识收敛

优化前：

```text
行为知识 = prompt + action_specs + registry description + llm_agent patch
```

优化后：

```text
行为知识 = Skill registry（主） + action_specs（执行规格） + Guard（安全判定）
```

虽然还没有完全消除所有重复，但至少形成了清晰的上层组织结构。

### 7.2 维护收益：改动边界更清晰

现在如果要优化某类能力，比如 `return_items`：

- 主要改 `app/skills/registry.py` 中对应 Skill 的 guidance / few-shot
- 不必先去 prompt 大段示例里搜索同类逻辑

这会明显降低“改一处漏一处”的概率。

### 7.3 评测收益：从整体 pass rate 升级为 Skill 维度可观测

新增 `metrics.skill_metrics` 后，report 可以直接表达：

- 哪个 Skill 的通过率下降了
- 哪个 Skill 的失败标签最集中
- 两次 baseline 之间到底是哪些 Skill 定义发生了变化

这让后续 bad case flywheel 更容易真正闭环。

### 7.4 面试收益：从“会调 prompt”升级到“会管理 prompt 资产”

这次优化最大的可讲点是：把 prompt 里的经验，升级成了工程里的资产。这表示你不只是在做 Agent feature，而是在考虑：

- 方法资产怎么版本化
- 行为知识怎么收敛
- 能力回归怎么按维度观测
- prompt 演化怎么接入评测体系

---

## 8. 剩余问题与下一步

### 8.1 剩余问题：exchange unavailable 分支仍有 planning 波动

当前最明显的待优化点是：

- `exchange_items` Skill 还不够强约束
- 模型在“已知 unavailable 的 replacement item”场景下，有时会选择直接推荐替代款，而不是先走 Guard block

### 8.2 下一步建议

#### 方向一：收紧 `exchange_items` Skill guidance

在 `app/skills/registry.py` 中为 `exchange_items` 增加更明确约束：

- 如果用户已经明确指定 `new_item_id`
- 即使该 item 已知 unavailable
- 也应先调用 `exchange_delivered_order_items`
- 让 Guard 返回 `replacement_item_unavailable`
- 再在 block 后推荐可替代选项

这会非常精准地修复 `29/30` 中剩下的 1 个 bad case。

#### 方向二：继续把 registry 的 write tool description 从 Skill 派生

当前 Skill 已经成为主知识层，但 `app/tools/registry.py` 中仍有一部分 write tool description 后缀逻辑是手工拼接的。

后续可以继续做：

- 让 write tool description 直接从 Skill 派生
- 进一步减少知识重复

#### 方向三：把 skill_id 扩展到动态生成 case

目前静态 case 已经打上了 `skill_id`，后续可以继续把：

- `generalization` 动态 case
- `tau_*` case

也映射到 Skill 维度，这样整套 eval 体系才会更完整。

---

## 9. 结论

这轮 Skill 资产化优化本质上是知识组织升级，不是功能扩展。

它没有改写 Agent Loop 或 Guard 执行链路，但做了三件事：

1. 把 8 个高频写操作沉淀成显式 Skill 资产
2. 让 prompt 中的经验可以通过 Skill 动态注入，不再散落各处
3. 让 eval 和 baseline 开始支持按 Skill 维度看回归

从结果看：

- MVP 基线没有回退
- `curated_mvp` 仍然 `11/11`
- `generalized_mvp` 达到 `29/30`
- 失败点收敛到一个 `exchange unavailable` planning 场景

因此可以认为这一轮优化是成功的。项目从"能跑的 Agent"往前推进了一步，变成了开始具备可管理能力资产的 Agent 工程系统。
