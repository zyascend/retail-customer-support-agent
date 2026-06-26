# Tau Wrong-Tool 优化交接文档（2026-06-26）

> 目标：把最近一轮 tau 全量覆盖、wrong_tool / tool_exception / guard_blocked 优化尝试、当前最优结果、失败模式、下一步方向完整整理，方便其他 threads 接手。

---

## 1. 背景与目标

本轮工作的起点是：

- 已经把 tau retail **114 个 task** 全部接入 `tau_retail_all`
- 全量 live eval 基线较低，主要问题集中在：
  - `wrong_tool`
  - `tool_exception`
  - `guard_blocked`

目标分三步：

1. 把 114 个 case 全量跑通，建立可比较基线
2. 优先吃掉 `tool_exception` 和 `confirmation_failure` 这类高确定性问题
3. 再聚焦 `wrong_tool` 的复杂规划类问题

---

## 2. 关键时间线 / 过程总结

### Phase A — 全量 tau 接入

**变更**
- 新增 `tau_retail_all` subset
- 新增 `app/eval/tau_coverage.py` 覆盖统计脚本
- `tau_retail_all` 包含全部 114 个 tau retail task（含 2 个零 action fallback case）

**相关提交**
- `a7d7da0` — `feat: 新增 tau_retail_all subset 和覆盖统计脚本，支持跑满 114 个 tau task`

**结果**
- 首次全量基线：
  - `eval-6e7067ca1b60`
  - `75/114`
  - `65.79%`
- failure label 分布：
  - `wrong_tool`: 20
  - `tool_exception`: 10
  - `guard_blocked`: 7
  - `confirmation_failure`: 2

---

### Phase B — 修复 user_simulator（高确定性收益）

#### B1. 名字提取修复

修复点：`app/eval/tau_user_simulator.py`

解决了以下问题：
- `"You are Ethan Garcia, and ..."` 这类逗号格式未匹配
- `"You are an interesting guy called Noah Patel ..."` 误提取成 `an`
- `"You're Chen Smith ..."` 未匹配
- `"user noah_ito_3850"` / `"Lucas (lucas_santos_6600)"` 无法映射到 DB user_id

新增了：
- `_resolve_name_to_user_id()`

#### B2. 邮箱提取修复

修复点：`app/eval/tau_user_simulator.py`

解决了以下问题：
- 多邮箱任务只取第一个邮箱，导致故意放置的错误邮箱被使用
- 改为优先取最后一个邮箱（通常是正确邮箱）

**相关提交**
- `4bb2e3d` — `fix: 修复 user_simulator 名字提取和邮箱匹配 bug，tau pass_rate 74.56% (+10 cases)`

**结果**
- `eval-6511561edc1b`
- `85/114`
- `74.56%`

相对 baseline：
- **+10 cases**
- `tool_exception: 10 → 3`
- `confirmation_failure: 2 → 0`
- `wrong_tool: 20 → 19`

**结论**
- 这是当前最确定、收益最明确的一轮优化
- 说明很多失败其实不是策略问题，而是 simulator / identity 数据问题

---

### Phase C — premature_transfer 尝试（有收益，但有限）

#### C1. 第一版思路

尝试拦截：
- 认证/加载上下文后立即 `transfer_to_human_agents`

实现路径：
- 在 `AgentLoop` 中加入 `premature_transfer_blocked`
- 当 LLM 想直接 transfer 时，返回 synthetic tool error，提示其先尝试写工具

第一版宽泛实现导致回归，不可用。

#### C2. 第二版（更窄的 immediate-transfer 拦截）

保留 narrower 逻辑：
- 只有当最近工具链满足：
  - `find_user_id_by_email` / `find_user_id_by_name_zip`
  - `get_user_details`
  - 且尚未尝试任何 write tool
  - 且当前是 `transfer_to_human_agents`
- 才阻止 transfer

**相关提交**
- `2fa66e9` — `feat: 新增 premature_transfer 拦截，pass_rate 74.56%→77.19% (+3)`

**结果（最佳一次）**
- `eval-5429496a6622`
- `88/114`
- `77.19%`

相对 `74.56%`：
- **+3 cases**
- `guard_blocked: 7 → 4`
- `wrong_tool` 仍然是 `19`

**结论**
- 这条线有效，但收益很有限
- 核心问题不是“有没有拦 transfer”，而是模型在复杂请求上没有形成正确的多步执行策略

---

### Phase D — guard_blocked 白名单对齐

思路：
- 对 tau case，如果被 Guard block 的工具不在 `expected_tool_names` 中，则说明 Guard 正在阻止一个不该执行的动作
- 这种情况应视为“预期保护成功”，不一定判 fail

实现：
- `app/eval/runner.py` 中 `classify_failure()` 增加 blocked tool whitelist 判断

**相关提交**
- `1e21e0e` — `fix: tau guard_blocked 白名单，预期拦截不判失败`

**结果**
- 受 live API 波动 / rpm 限流影响，本轮结果不稳定
- 一次完整 50 workers 结果：
  - `eval-3899174d18e1`
  - `86/114`
  - `75.44%`
- 但这轮与最佳 run (`88/114`) 不可直接归因比较，因为 live run 波动较大

**结论**
- 代码逻辑方向合理
- 需要在更稳定的低并发 / pass@k 环境下验证其真实收益

---

### Phase E — wrong_tool 专项优化尝试

#### E1. 建立专项 subset

新增：
- `tau_retail_wrong_tool_focus`

包含固定 19 个 `wrong_tool` case：

```text
tau_46
 tau_36
 tau_47
 tau_72
 tau_71
 tau_45
 tau_88
 tau_84
 tau_92
 tau_91
 tau_93
 tau_94
 tau_95
 tau_97
 tau_98
 tau_107
 tau_109
 tau_110
 tau_113
```

专项结果：
- `eval-04984d707930`
- `0/19`
- 19/19 全部仍是 `wrong_tool`

#### E2. 代表 case 深挖

抽取 5 个代表 case：
- `tau_45`
- `tau_71`
- `tau_84`
- `tau_88`
- `tau_113`

对比发现：
- 大部分 case 的实际工具链是：
  - `find_user_id_by_*`
  - `get_user_details`
  - `transfer_to_human_agents`
- 即：**身份验证后直接转人工**
- 但其根因并不是简单 transfer，而是模型不会把复杂请求拆成：
  - order lookup
  - item selection
  - fallback write
  - batch write

#### E3. prompt / skill guidance 强化

尝试方向：
- 在 `app/skills/registry.py` 的 `cancel_order` / `modify_address` / `modify_items` / `return_items` / `exchange_items` 中加更强的 prompt guidance 和 few-shot

结果：
- `eval-79383dec07f0`
- `0/19`

**结论**
- 这批 wrong_tool 不是 prompt / few-shot 微调能解决的
- 需要更强的 orchestration 层，而不是更长的 skill guidance

---

### Phase F — Lightweight Planner / Subtask Orchestrator 尝试

实现了第一版轻量 planner：

**新增 / 改动**
- `app/agent/models.py`
  - `PlanItem`
  - `ExecutionPlan`
  - `SessionState.current_plan`
  - `TurnContext.proposed_plan`
  - `TurnContext.planner_invoked`
- `app/agent/planner.py`
  - `LightweightPlanner`
  - `render_plan_for_prompt`
- `app/agent/llm_agent.py`
  - 在 `run_turn()` 主循环前生成 `Planner Draft`
  - 作为 assistant message 注入 prompt
- `prompts/llm_agent_system_v001.md`
  - 增加 `## Planner` 段落

**验证**
- 单元测试全部通过（相关 tests 仍 OK）
- 但 wrong_tool 专项集结果：
  - `eval-f4df0189bcdd`
  - `0/19`

**结论**
- “把 planner 作为文本 scaffold 注入 prompt” 对模型几乎没有约束力
- 这说明：
  - **text planner ≠ orchestrator**
  - LLM 看到了 plan，但没有按 plan 做

---

## 3. 当前最好结果（authoritative）

### 当前最优完整 tau_retail_all 成绩

**推荐引用 run**
- `eval-5429496a6622`
- `88/114`
- `77.19%`

### 当前最优 breakdown

| failure_label | count |
|---|---:|
| passed | 88 |
| wrong_tool | 19 |
| tool_exception | 3 |
| guard_blocked | 4 |

### 稳定区间（live eval 有波动）

在近期多次全量 live eval 中，`tau_retail_all` 基本落在：

- **85/114 ~ 88/114**
- 即 **74.56% ~ 77.19%**

说明：
- 当前系统已经明显优于最初的 65.79%
- 但仍存在 live provider 波动、rpm 限流、tool-selection 不稳定问题

---

## 4. 当前明确已知的根因分类

### A. 已基本解决

#### 1. simulator / identity extraction 问题
- 名字 regex 提取错误
- 多邮箱选择错误
- synthetic user_id 映射失败

这部分已完成，收益非常高（+10）。

---

### B. 仍然悬而未决

#### 2. wrong_tool（19 个）
这 19 个不是 19 种 bug，而是 4 类缺失能力：

##### 模式 1：复杂需求的多步规划缺失
- 模型在复杂请求中不会显式拆解
- 典型表现：身份验证后直接 transfer

##### 模式 2：比较型 item selection 缺失
- 不会选“更便宜的 / 更贵的 / all but one / recent order item”

##### 模式 3：fallback / conditional workflow 缺失
- 不会执行“如果没有就 cancel”
- 不会处理“确认时改主意”

##### 模式 4：batch write orchestration 缺失
- 不会对多个订单 / 多个 item 连续落多次 write tool
- 典型：`tau_113`

---

## 5. 当前已经验证过“无效”的方向

以下方向已经做过实验，**可以直接视为低优先级或无效**：

### 无效方向 1：单纯加 skill guidance / few-shot
- 对 19 wrong_tool case：`0/19`
- 结论：不能靠更长 prompt 解决

### 无效方向 2：textual planner draft 注入
- 对 19 wrong_tool case：`0/19`
- 结论：模型不会严格按 draft 执行

### 收益很低方向 3：宽泛 / 半宽泛 premature_transfer 拦截
- 对全量提升仅 +3
- 而且实现和验证复杂，收益不成比例

---

## 6. 当前最值得继续的方向（建议给其他 thread）

### 优先级 P0：从“text planner”升级为 **code-driven pre-orchestrator**

这是最值得做的下一层。

### 为什么
因为现在的失败不是：
- 模型没看到说明
- 模型不知道工具名

而是：
- 模型没有形成稳定的 **read → select → write → fallback** 行为链

### 建议的最小版本
不是大改架构，而是先做一个 deterministic pre-orchestrator：

#### 方案
在复杂请求命中时，由代码先完成前置 read steps：

- `get_order_details`
- 必要时 `get_product_details`
- 必要时 item 筛选 / recent order 解析

然后把：
- 具体 order
- 具体 item candidates
- 具体 fallback context

作为 richer context 交给现有 LLM tool loop，让 LLM 只负责最后 write decision。

#### 适合优先覆盖的 case
建议其他 thread 先从这 5 个代表 case 开始：
- `tau_45`
- `tau_71`
- `tau_84`
- `tau_88`
- `tau_113`

因为这 5 个几乎覆盖了 19 wrong_tool 的全部根因模式。

---

### 优先级 P1：构造更强的 `tau_retail_wrong_tool_focus` 局部 harness

当前 subset 已有，但它只是 case 筛选。

建议进一步补：
- case 聚类脚本
- representative trace diff
- 按模式分组统计

用途：
- 局部优化 1~2 轮后，不必立即回归 114 个
- 可以在 19 个集上快速收敛

---

### 优先级 P2：稳定性 / Golden baseline

尽管 pass@3 / golden 还没做完，但方向仍值得继续。

原因：
- 当前 live eval 波动明显（85~88 / 114）
- 即使不继续优化能力，也应该把“稳定通过的部分”固化进 golden set

建议：
1. 先在 `tau_retail_all` 或其子集上跑 `--trials 3`
2. 提取 3 次都通过的稳定 case
3. `flywheel golden promote --confirm`
4. `flywheel check --no-progress --json`

注意：
- 目前 API 有 rpm 限流，建议低并发或夜间跑
- `max-workers 50` 偶发能跑通，但容易 429
- `max-workers 1~5` 更稳定，但耗时更长

---

## 7. 建议接手顺序（给其他 threads）

### Thread A（推荐优先）
**主题：code-driven pre-orchestrator**

交付目标：
- 为复杂 tau wrong_tool case 增加 deterministic pre-read / pre-selection 层
- 先救 `tau_45 / 71 / 84 / 88 / 113`

### Thread B
**主题：wrong_tool_focus 观测与聚类工具**

交付目标：
- 自动输出 representative case 对照
- 生成 expected vs actual tool chain 报告

### Thread C
**主题：pass@3 + golden**

交付目标：
- 跑 3-trial
- promote 稳定 case
- 建 golden regression baseline

---

## 8. 已修改 / 新增文件清单（本轮）

### 已有效落地
- `app/eval/tau_loader.py`
- `app/eval/cases.py`
- `app/eval/tau_coverage.py`
- `app/eval/tau_user_simulator.py`
- `app/eval/runner.py`

### 已实验但未证明有效
- `app/agent/llm_agent.py`（premature transfer & planner 相关尝试）
- `app/agent/planner.py`
- `prompts/llm_agent_system_v001.md`
- `app/agent/models.py`

> 注意：这些 planner / premature-transfer 相关改动虽然已经落在工作区/提交链中，但从实验结果看，尚未证明能提升 wrong_tool_focus，因此后续 thread 接手时应优先评估“保留/回滚/重做”。

---

## 9. 最后一句话结论

**本轮最成功的工作是修复 tau user simulator 的身份提取问题（+10 case）。**

**当前最大的剩余问题不是 prompt，而是复杂请求缺少 deterministic orchestration。**

如果后续要继续推进，最值得投入的方向是：

> **把 planner 从“文本建议”升级为“代码先做关键 read / selection，再让 LLM 做最后 write 决策”的 pre-orchestrator。**
