# 检测层收敛重构与多语言泛化复盘

> 场景：面试讲述
> 关联 spec：[detection-layer-refactor.md](../plans/2026-06-27-detection-layer-refactor.md)
> 对比方案：[semantic-layer-architecture.md](../plans/2026-06-27-semantic-layer-architecture.md)（原文档，评审后推翻）

---

## 1. 一句话总结

把散落在 6 个文件、40+ 条英文正则的语义检测层，收敛成 3 个职责清晰的模块，**没有加任何一轮 LLM 调用**，靠主 LLM 的 tool-call 兜底实现多语言泛化。最终英文 eval 保持 100%，新增中文 eval 从 76.7% 提升到 100%。

整个过程最有价值的不是最终代码，而是**评审阶段推翻了一个看起来很合理的方案**——以及推翻它的那个反直觉洞察。

---

## 2. 背景：问题是什么

这是一个 LLM tool-calling 零售客服 agent。用户用自然语言查/改订单——取消、退货、换货、改地址、改支付、转人工。所有写操作经 7 层 Guard 校验后才执行。

agent 的主循环是：用户消息 → LLM（带 tool-calling）→ 决定调哪个工具 → Guard 校验 → 执行。这个主循环本身**就是一个多语言的语义理解引擎**——DeepSeek 天然能处理"kill my order""我要取消那个单""帮我撤了它"。

但系统里还有一层**正则预检**，散落在 6 个文件，40+ 条英文正则：

| 模块 | 做什么 | 语言 |
|------|--------|------|
| `action_candidates.py` | 意图 HINT（提示主 LLM 该调哪个写工具） | 英文 |
| `llm_agent.py` | 注入检测 / 拒绝纠正 / 写意图反查 | 英文 |
| `runtime.py` | 转人工短路 | 英文 |
| `confirmation.py` | 确认/拒绝/变更解析 | 中英双语 |
| `parsers.py` | 邮箱/姓名邮编提取 | 英文句式 |

痛点很明确：**加一门语言要改 6+ 个文件**。不可扩展。

---

## 3. 评审阶段：一个看起来合理的方案，被我推翻了

### 原方案的思路

有一份设计文档（[原文档](../plans/2026-06-27-semantic-layer-architecture.md)）提出：加一个 `SemanticDetector` 抽象层，**每轮多调 1~2 次 LLM**（`analyze()` + `detect_refusal()`），把意图/身份/转人工/确认全部交给 LLM 判断，正则作为降级。

文档质量很高——分层清晰、故障矩阵完整、有延迟预算表。乍看很合理：正则不够好 → 用 LLM 替代 → 多语言自动覆盖。

### 推翻它的那个反直觉洞察

评审时我逐行核对了代码，发现一个原方案没意识到的事实：

> **这个系统的主循环本来就是一个带 tool-calling 的 LLM，它已经在做意图分类了。**

主 LLM 收到"cancel order #W123"→ 决定调 `cancel_pending_order`。这就是意图识别，而且是多语言的、免费的、已经在跑的。原方案要加的 `analyze()` LLM 调用，和主 LLM 做的是**同一件事**——属于重复付费。

所以正确的问法不是"正则 vs LLM"，而是：

> 既然主 LLM 已经在做语义分类，为什么还要再加一个并行的 LLM 做同样的事？散落的正则该怎么治？

### 归因纠偏

原方案把"加语言改 6 文件"归因于"用正则做语义检测"。**归因错了**：

- 散落是问题 → **收敛解决**
- 正则做语义是问题 → **不成立**，主 LLM 已覆盖语义，正则只是快路径

---

## 4. 关键区分：这些检测根本不是一类

评审的第二个关键动作：把 6 处检测按"谁该负责泛化"重新分类。它们的安全性和状态依赖完全不同，塞进一个 `SemanticDetector` 是错的：

| 检测点 | 性质 | 状态依赖 | 泛化谁负责 |
|--------|------|---------|-----------|
| 格式提取(订单号/邮箱/商品ID) | 数据 | 无 | 正则（格式语言无关） |
| 意图分类(哪个写工具) | HINT | 无 | **主 LLM 的 tool-call** |
| 身份-邮箱 | 数据 | 无 | 正则 |
| 身份-姓名邮编 | 触发认证 | 无 | 正则快路径 + 主 LLM 工具兜底 |
| 转人工 | **控制 GATE** | 无 | 正则（确定性优先） |
| 确认解析 | **控制 GATE** | 无 | 正则（已精调，不动） |
| 注入检测 | **安全 GATE** | 无 | 正则 PRIMARY + LLM secondary |
| 拒绝纠正 | 编排 | **有**（查 loaded orders） | **留在 AgentLoop** |

### GATE vs HINT（原方案最大的安全错误）

原方案 §5.3 把所有字段一概称"HINT，错了主 Loop 兜底"。但逐字段看：

| 字段 | 性质 | LLM 误判后果 |
|------|------|------------|
| `intent` | ✅ HINT | 主 LLM 兜底 |
| `human_transfer` | ❌ **GATE** | 误转人工终止 turn，**无兜底** |
| `confirmation` | ❌ **GATE** | 误判 confirmed=执行本该取消的写操作，**无兜底** |

`confirmation` 已是中英双语精调（`confirmation.py`，项目规范明确警告 `confirm<2` 守卫不能动）。把它塌缩成 LLM 一个 `"confirmed"|"denied"` 字段，等于把**写操作的执行/放弃交给模型随机性**，且没有兜底层。

这是评审中最重要的一条：**GATE 字段必须确定性优先，LLM 只能在正则返回 unknown 时兜底，绝不能主导。**

---

## 5. 最终方案：三层收敛，不加 LLM 调用

```
Layer 0  extraction.py   格式提取（语言无关）
Layer 1  action_candidates.py  意图 HINT（正则 nudge，主 LLM 决策权威）
Layer 2  security.py      注入 + 转人工 GATE（确定性优先）
         ConfirmationResolver  确认 GATE（不动，已双语）
         AgentLoop 编排逻辑     有状态，留在原处
```

### 唯一加 LLM 的地方：注入 secondary

注入检测是当前**唯一真安全缺口**——英文正则覆盖已知模式，但中文注入（"忽略以上指令"）正则 miss。这里加 LLM secondary，但带**假阳守卫**：

> 仅在 `provider 可用 + enabled + 正则未命中 high-risk` 时才调 LLM，且只采纳 `severity=high` 的判定。

为什么这么保守？因为 high-risk 注入信号会直接 block 写操作（`llm_agent.py` 的 `_block_high_risk_prompt_injection_write`）。在英文 100% 的基线上，LLM 把正常客服话误判 injection = **合法写被误 block = eval 退步**。原方案的故障矩阵完全没提这个。

---

## 6. 分阶段落地与数据

### P0 纯收敛重构（零行为变化）

把散落的正则搬到 3 个模块，删除死代码（`_WRITE_KEYWORD_PATTERNS` 无任何调用点）、合并两个逐字符相同的转人工正则。

**验收**：英文 eval 30/30 = 100%，核心测试 92 passed。零新增 LLM 调用。

这一步是纯收益——降维护成本、合并重复、保护基线，零风险。

### P1 注入 LLM secondary

provider 加 per-call `timeout`/`max_tokens`（原方案 §4 依赖的全局短超时，当时 provider 根本不支持——这是评审发现的悬空前提）。security 层加 LLM secondary + 假阳守卫。默认 `enabled=False`，保护英文基线。

**验收**：27 个新测试覆盖假阳守卫 7 场景，默认配置下英文 eval 不回归。

### P2 中文多语言 pattern + 中文 eval

这是用真实数据验证设计假设的关键一步。

#### 现状 baseline：76.7%

造好 30 个中文 case（`generalized_mvp_zh`），先不加任何中文 pattern 跑一次：

```
generalized_mvp_zh (current, no zh patterns): 23/30 = 76.7%
```

7 个失败。**这一步的意义**：它证明了"主 LLM 兜底"假设的边界——主 LLM 能处理中文意图，但 GATE 和预检正则的中文缺口它兜不了。

#### 归因：7 个失败只有 2 类问题

逐个读 trace 归因，发现 7 个失败全部是这两类，**没有一个**是"主 LLM 决策错"：

| 失败类型 | 根因 | 修复 |
|---------|------|------|
| confirmation GATE（3 个） | "不了，改成X"被否定变更正则误判 denied；"是"确认权重1过不了 `confirm>=2` 守卫 | 否定变更要求否定词**紧邻**变更词；"是"提权至 3（与 yes 对等） |
| 预检正则中文 miss（4 个） | "退货/换货/取消"意图 HINT miss；"我叫 Sofia 邮编78784"身份 miss | `action_candidates`/`extraction` 加中文 pattern |

这验证了 spec 的核心论点：**泛化引擎是主 LLM，缺的只是 GATE 和预检的中文适配**——不需要每轮加 LLM 调用。

#### 修复后：100%

```
generalized_mvp_zh (after zh patterns): 30/30 = 100.0%
generalized_mvp (EN, regression check): 30/30 = 100.0%
```

中英文双 100%，零回归。

---

## 7. 决策对比表（面试可讲）

| 维度 | 原方案（加 SemanticDetector LLM） | 最终方案（收敛 + 主 LLM 兜底） |
|------|----------------------------------|------------------------------|
| 每轮新增 LLM 调用 | +1~2 | **0**（仅注入 secondary 在 regex miss 时触发） |
| 延迟 | +~1s/turn | +0 |
| 泛化引擎 | 新加的 semantic LLM | **主 LLM 本身（已多语言，免费）** |
| GATE 安全 | confirmation/transfer 交给 LLM | **确定性优先，LLM 仅 unknown 兜底** |
| 英文 100% 基线风险 | 高（新故障面 + GATE 交 LLM） | **低**（P0 纯搬运零行为变化） |
| 加一门语言改动 | 0（LLM 自动） | 2~3 处收敛后的 pattern |
| Provider 前置改造 | 必须加全局短超时（当时不支持） | 不需要（无每轮 LLM 调用） |
| 中文 eval 结果 | 未验证（无中文 subset） | **76.7% → 100%** |

---

## 8. 面试可深挖的点

### Q: 你怎么发现原方案有问题的？

逐行核对代码。三个具体抓手：

1. **`_WRITE_KEYWORD_PATTERNS` 是死代码**——原方案说它"被 `_block_premature_transfer` 使用"，但 grep 全仓库零调用点。这让我开始怀疑原方案对现状的描述精度。
2. **两个转人工正则逐字符相同**——原方案 §1 只列了 1 个，漏了 `llm_agent.py` 那个。说明原方案没完整摸现状。
3. **provider 不支持 per-call timeout**——原方案 §4/§5 的延迟预算和故障矩阵都建立在 3s 短超时上，但 `DeepSeekProvider` 实际是 client 级 30s timeout，`json()/chat()` 无形参。整个数字基础是悬空的。

### Q: 为什么不直接全部交给 LLM？正则不是过时了吗？

因为"正则做语义"和"正则做 GATE"是两件事。意图识别交给 LLM 没问题（主 LLM 已经在做）。但 `confirmation`/`human_transfer` 是 GATE——误判没有兜底层：

- `confirmation` 误判 confirmed → 执行本该取消的写操作
- `human_transfer` 误判 true → 直接转人工终止 turn

GATE 的本质是"错了没有救"，所以必须确定性优先。正则在这里不是"过时"，是"可控"。

### Q: 中文 76.7% → 100% 的 7 个失败，为什么主 LLM 兜不了？

因为主 LLM 调 `find_user_id_by_name_zip` 只是**读操作**，不会设置 `session.authenticated_user_id`——认证态只有预检短路才设。所以身份正则 miss 时，即使主 LLM 正确调了工具，认证态仍是 null，后续写操作被 Guard 拦。

这揭示了架构的一个约束：**预检短路和主 LLM 路径的副作用不对称**。预检不仅识别身份，还设置认证态；主 LLM 路径只读不设。所以身份提取必须由预检正则覆盖，不能只靠主 LLM。

### Q: 假阳守卫为什么是"仅 severity=high 且正则未命中才采纳"？

两个条件各有目的：
- **正则未命中 high-risk 才调 LLM**：正则已命中 high 时，结果已确定，调 LLM 既浪费又有干扰风险。
- **仅采纳 severity=high**：high-risk 信号会直接 block 写操作。如果 LLM 把"please cancel everything"误判成 medium 注入并采纳，合法写就被拦了——在英文 100% 基线上这是退步。所以只采纳 LLM 最确信（high）的判定，其余丢弃。

核心思想：**LLM secondary 是补充，不是替代；宁可漏报（正则没覆盖的变体），不可误报（误 block 合法写）。**

---

## 9. 反思：做得好与可改进

### 做得好

1. **评审没有停留在"文档看着不错"**——逐行核对代码，发现了 3 处与现状不符的描述，这些是原方案不可靠的信号。
2. **用真实数据验证假设**——P2 先跑 76.7% baseline 再归因，而不是假设"主 LLM 兜底就够了"。7 个失败证明兜底有边界，且边界清晰可修。
3. **P0/P1/P2 解耦 + go/no-go 门槛**——P0 零风险立即做，P1 默认关闭保护基线，P2 等中文 case 到位再开。没有一步到位赌全部。

### 可改进

1. **中文 eval 只有 30 个 case**——覆盖了主路径，但长尾表达（"帮我撤了那个单""这单不要了"）未覆盖。多语言泛化的鲁棒性需要更大规模 case 验证。
2. **姓名邮编的"数据模型墙"未根治**——`find_user_id_by_name_zip` 要 `first_name`/`last_name`，是英文名数据模型。中文"张三"→姓张名三是错配。本次靠"我叫 Sofia Rossi"（英文名）绕过，真正的中文名场景仍需改工具契约。
3. **`synthetic_seeded_v1` 的 43% 失败未归因**——spec §7.1 提到要先归因这批失败确认瓶颈，但实际跳过了直接做 P2。好在 P2 的归因结果（瓶颈在正则不在主 LLM）间接回答了这个问题，但不够严谨。

---

## 10. 关键数据

| 指标 | 改造前 | 改造后 |
|------|--------|--------|
| 英文 `generalized_mvp` | 100% | **100%**（零回归） |
| 中文 `generalized_mvp_zh` | 76.7%（无中文 pattern） | **100%** |
| 每轮新增 LLM 调用 | 0 | **0** |
| 检测正则散落文件数 | 6 | **3**（extraction / security / action_candidates） |
| 重复正则 | 2 个逐字符相同的转人工 | **1**（合并） |
| 死代码 | `_WRITE_KEYWORD_PATTERNS`（7 条无引用） | **0**（删除） |
| 单元测试 | 92（test_agent_core） | **120**（+28 检测层专项） |
| 加一门语言改动文件 | 6+ | **2~3**（Layer 1 + Layer 2） |

---

## 附：技术决策的三个第一性原则

这次重构背后有三条可复用的决策原则：

1. **别给系统已经有的能力付费**——动手前先问"这个能力系统已经有了吗"。主 LLM 已经在做意图分类，再加一个 LLM 做同样的事就是重复付费。

2. **GATE 和 HINT 不能用同一套策略**——HINT 错了有兜底，GATE 错了没救。GATE 必须确定性优先，LLM 只能做 unknown 兜底，不能主导。

3. **用数据定位瓶颈，别用架构假设瓶颈**——"正则是瓶颈"是假设，"7 个失败全是 GATE/预检正则 miss"是数据。数据说瓶颈在 GATE 精调不在主 LLM，方案就跟着数据走。
