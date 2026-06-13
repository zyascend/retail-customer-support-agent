# 零售客服智能 Agent

一个 12 节点的 LLM Agent，面向零售客服场景，内建 7 层写安全护栏和「确定性规则 + LLM 语义」双轨决策机制。基于 tau2-bench retail 数据构建，定位为 AI Agent 工程的作品集项目——展示安全写操作、意图消歧、全链路可审计三项核心能力。

> **演示地址:** 按下方「快速开始」启动后，打开 `http://localhost:5173` 即可体验 Workbench，内含 10 个按用户旅程分组的精选案例。

## 解决的问题

零售客服 Agent 面临三个核心挑战：

1. **写操作安全** — 取消订单、修改支付方式、退换货等操作不能误触发，更不能越权执行。每一次写入都需要用户显式确认，并通过多层护栏检查。
2. **意图消歧** — 用户说"我想改一下订单"，可能意味着取消、换商品、改地址、改支付方式。Agent 必须从非结构化自然语言中提取出结构化的意图和槽位。
3. **全链路可审计** — 每一次决策、每一次工具调用、每一次数据库变更，都必须追溯到具体的策略规则，并提供操作前后的哈希对比和幂等键。

本项目以「确定性优先、LLM 增强」的架构应对这三个挑战。

## 架构概览

```
receive_message → conversation_gate → identity_resolver → intent_and_slot_extractor
→ context_loader → policy_reasoner → action_planner → write_action_guard
→ tool_executor → observation_reducer → response_generator → run_logger
```

**双轨决策**: 每个决策节点并行运行两条轨道——code track（基于正则，始终运行）和 LLM track（基于语义，按需启用）。合并规则：**拒绝优先（deny wins）**。Code track 是正确性的锚点；LLM 负责填补语义空白，但不会覆盖 code track 提取的结构化数据（如订单号、商品 ID）。

**7 层写护栏**: 身份认证 → 显式确认 → 所有权校验 → 先读后写 → 策略合规 → 资源锁 → 幂等性。每一次写操作在真正执行前，都必须依次通过全部七层检查。

## 关键设计决策

- **拒绝优先合并** — 任一轨道给出"拒绝"，最终结果就是拒绝。两轨都给出"允许"才算允许。这确保了确定性 code track 扮演安全底线的角色。
- **Code track 为锚** — LLM 的决策如果与 code track 冲突，会被覆盖。LLM 只补充 code track 未提取的语义字段（如退款原因），不能覆盖 code track 已提取的订单号、商品 ID 等结构化数据。
- **写操作单一事实来源** — `app/agent/action_specs.py` 定义了全部 7 种写操作。护栏规则、工具注册表、LLM 提示词中的 `{action_catalog}` 模板、运行时合并逻辑，全部由此派生。新增一种写操作只需改这一个文件。

## 快速开始

```bash
# 1. 安装依赖
uv sync --extra dev

# 2. 启动 Workbench 演示（确定模式，无需 API Key）
uv run phase4-workbench &           # Python API → :8000
cd workbench && npm install && npm run dev   # React 界面 → :5173

# 3. 运行 Eval（确定模式）
uv run phase2-eval --subset generalized_mvp --trials 1

# 4. 运行测试
uv run python -m pytest tests/ -q
```

如需启用 LLM 模式，在 `.env` 中配置 `DEEPSEEK_API_KEY` 即可。

## Demo 导览

打开 `http://localhost:5173`，按用户旅程分组体验 10 个案例：

| 分组 | 包含案例 | 展示内容 |
|------|---------|----------|
| 🔐 身份认证 | 姓名+邮编验证查订单 | 用户身份识别流程 |
| ✅ 成功写操作 | 取消订单、退货、换商品、改支付方式 | 带确认的完整写操作链路 |
| 🛡️ 写保护阻止 | 越权访问他人订单、跨商品替换、礼品卡余额不足 | 护栏各层拦截未授权写入 |
| 🔄 用户确认 | 拒绝取消确认 | 用户侧确认/拒绝/修改交互 |
| 📞 边界能力 | 转接人工客服 | 不支持操作的升级流转 |

**Timeline 中的关键证据**: 选中任意案例，点击「运行全部」，然后在 timeline 中查看：
- 意图提取 + 槽位填充 → 策略决策（允许/拒绝 + 理由）
- 工具调用结果 → 护栏阻止详情（如有）
- 写入审计记录（操作前后 DB 哈希、幂等键）

## Eval 结果

| 指标 | curated_mvp（11 case） | generalized_mvp（30 case） |
|------|----------------------|---------------------------|
| pass_1 | 11/11 | 30/30 |
| pass_k | 11/11 | 30/30 |
| db_accuracy | 100% | 100% |

失败分类体系包含 14 种有序标签（llm_json_failure → auth_failure → wrong_intent → ...），确保精准定位问题。

## 项目结构

```text
app/agent/       — 12 节点 pipeline 运行时、状态模型、提示词、护栏
app/tools/       — retail 适配器、工具注册表、写操作网关
app/eval/        — curated + generalized eval 案例、运行器、失败分类
app/workbench/   — Workbench API（FastAPI 后端）
workbench/       — Workbench React 前端
prompts/         — 带 SHA-256 哈希的版本化 LLM 提示词
docs/            — 设计文档、实施计划、架构参考
```

## 开发指南

```bash
# Lint 与格式化
uv run ruff check .
uv run ruff format --check .

# 运行单个测试
uv run python -m pytest tests/test_agent_core.py -v

# 交互式对话
uv run phase1-chat --interactive
```

深度架构参考见 [`docs/portfolio-architecture.md`](docs/portfolio-architecture.md)。

完整路线图见 [`docs/long-term-optimization-path.md`](docs/long-term-optimization-path.md)。
