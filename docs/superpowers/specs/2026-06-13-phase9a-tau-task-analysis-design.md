# Phase 9a: Tau Task Space Analysis — Design Spec

日期：2026-06-13
状态：待评审

## 目标

在 full tau ingestion 之前做轻量调研，输出分析报告，为 Phase 9 决定首批 ingestion 范围。

## 产出

1. **主报告**：`docs/tau-task-space-analysis.md`
2. **结构化数据**（可选）：`artifacts/phase9a/task_classifications.json`

## 数据来源

- `tasks.json` — 114 个 task（从 `TAU3_RETAIL_ROOT/domains/retail/` 读取）
- `split_tasks.json` — train(74) / test(40) / base(114)
- `task_issues/` — 3 个已知问题 task 的执行日志

## 分类框架

每个 task 标注为以下之一：

```
supported
  核心工具链完整，guard 规则匹配，DB assertion 可验证

partial
  核心工具完整但有辅助能力缺失
  ├── partial_missing_tool: 使用了 calculate 或 get_item_details
  ├── partial_nl_assertion: NL assertion 当前无法自动验证
  ├── partial_policy_gap: policy 规则可能存在差距
  └── partial_multi: 多个 partial 因素叠加

unsupported
  核心工具缺失或场景不可处理
  ├── unsupported_tool: 依赖我们完全没有的工具
  ├── unsupported_policy: 策略在当前系统不可表达
  ├── unsupported_interaction: 需要多 Agent 或外部协作
  └── unsupported_unknown: 无法分类
```

### 分类判定规则

1. **核心工具检查**：task 的 `evaluation_criteria.actions[].name` 是否都在 Agent 已支持工具集中
2. **辅助工具检查**：是否用到 `calculate`（13 次）或 `get_item_details`（3 次）
3. **NL assertion 检查**：`evaluation_criteria.nl_assertions` 是否为 null
4. **政策关键词检查**：task 描述中是否涉及 gift card / discount / refund / warranty / compensation / coupon
5. **交互模式检查**：task 的 action 序列是否需要当前 Agent 不支持的多步骤协作

判定顺序：先检查 unsupported 条件 → 再检查 partial 条件 → 其余为 supported。

## 报告结构

### 1. 概述
- 数据来源路径、task 总数、split 分布
- 分析日期、脚本版本

### 2. Task 空间统计
- 按 split 分布 (train/test)
- 按 reward_basis 分布（DB+NL_ASSERTION vs DB-only）
- 按 action 数量分布（min/max/avg）
- 按涉及工具频率分布（Top 15 工具）

### 3. 工具覆盖分析
- Agent 已支持工具 vs tau3 要求工具对照表
- 缺失工具详情：
  - `calculate`：13 次出现，影响的 task 列表，评估绕过可能性
  - `get_item_details`：3 次出现，影响的 task 列表
- 工具覆盖率的整体评估

### 4. 分类结果
- supported / partial / unsupported 汇总（数量 + 占比）
- 按 split 拆分的分类分布
- partial 子类别细分表
- unsupported 子类别细分表
- 完整 task 分类清单（按 task ID 排列）

### 5. NL Assertion 分析
- 统计：40 个 task 有 NL assertion
- 按类型分类：
  - `must_say`：要求 agent 传达了特定信息
  - `must_not_say`：要求 agent 没有说某些内容
  - `must_convey`：要求特定信息已传达但不限措辞
- 与现有 `expected_assistant_contains` 的映射评估
- 3-5 个代表性示例摘录
- 对 Phase 9 ingestion 的影响评估

### 6. 按 Capability 维度聚合
- 按意图类型分组（cancel / return / exchange / modify_address / modify_items / modify_payment / modify_user_address / transfer / lookup）
- 每组内 supported / partial / unsupported 分布
- 与现有 capability matrix（`docs/phase5-capability-matrix.md`）的对照

### 7. 已知问题 Task
- `task_issues/` 目录下 3 个 task 的简要说明
- 问题类型（termination_reason）和是否需要特殊处理

### 8. Phase 9 首批 Ingestion 建议
- 推荐接入范围（具体 task 数量和 split 分布）
- 排除项及原因
- 风险提示（NL assertion、calculate 依赖、policy gap）
- 建议接入策略：先 smoke subset（5-10 个 supported task），验证通过后再扩量

## 分析脚本设计

### 位置
`app/analysis/tau_task_analyzer.py`

### 接口
```python
def analyze_and_report() -> str:
    """主入口：运行完整分析，返回 Markdown 报告文本。"""

def load_tasks(config: AppConfig) -> List[dict]:
    """加载 tasks.json。"""

def load_splits(config: AppConfig) -> dict:
    """加载 split_tasks.json。"""

def classify_task(task: dict) -> TaskClassification:
    """对单个 task 进行分类。"""

def analyze_nl_assertions(tasks: List[dict]) -> NLAssertionAnalysis:
    """分析所有 NL assertion。"""

def aggregate_by_capability(
    tasks: List[dict],
    classifications: List[TaskClassification],
) -> CapabilityAggregation:
    """按 capability 维度聚合。"""
```

### 依赖
- 仅 Python 标准库 + `app.config.AppConfig`（读 tau3 路径）
- 不依赖 Agent runtime、LLM provider、eval runner
- 不发起网络请求

### 运行方式
```bash
uv run python -m app.analysis.tau_task_analyzer
# 输出 docs/tau-task-space-analysis.md
# 可选 --json 输出 artifacts/phase9a/task_classifications.json
```

### 数据模型
```python
@dataclass
class TaskClassification:
    task_id: str
    split: str  # train | test
    status: str  # supported | partial | unsupported
    subcategory: Optional[str]  # partial_missing_tool, unsupported_policy, ...
    tools_used: List[str]
    missing_tools: List[str]
    has_nl_assertion: bool
    has_policy_keywords: bool
    action_count: int
    reward_basis: List[str]
    notes: str
```

## 验收标准

- [ ] `docs/tau-task-space-analysis.md` 存在且内容完整（覆盖报告结构 8 个章节）
- [ ] 分析脚本可复现运行（同一份 tasks.json 产生相同报告）
- [ ] 分类覆盖全部 114 个 task，无遗漏
- [ ] supported / partial / unsupported 分类合理，有清晰判定依据
- [ ] 缺失工具 `calculate` 和 `get_item_details` 有影响评估
- [ ] NL assertion 有类型分类和代表性示例
- [ ] Phase 9 首批 ingestion 有具体 task 数量和 split 建议
- [ ] 报告能清楚说明 full tau ingestion 的已知支持面和风险
- [ ] 现有测试和 eval 不受影响（Phase 9a 为纯分析，不改 Agent runtime）

## 不做的事

- 不新增 CLI 子命令（`phase9a-analyze`）
- 不修改 Agent runtime、guard、tool 层
- 不接入 tau3 的 user simulator
- 不实现 tau3 task → EvalCase 的转换逻辑（留给 Phase 9）
- 不实现 reward evaluation（留给 Phase 9）
- 不新增 Python 依赖
