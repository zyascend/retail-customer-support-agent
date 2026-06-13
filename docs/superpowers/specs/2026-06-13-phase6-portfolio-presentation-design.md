# Phase 6: Portfolio-Grade Presentation Layer — Design Spec

**日期**: 2026-06-13
**状态**: 设计已确认，待实施
**来源**: docs/long-term-optimization-path.md Phase 6

## 目标

让 AI Agent 工程面试官在 3-5 分钟内理解项目价值。Phase 6 不新增 Agent 核心能力，仅将现有系统包装为清晰、有据、可演示的作品集。

## 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Demo 叙事分组 | 用户旅程（认证→成功→阻止→确认→转人工） | 模拟真实用户完整体验，面试官可自然跟随 |
| README 语气 | 作品集叙事型（8 段结构） | Phase 6 唯一目标是作品集入口，B/C 方案与目标矛盾 |
| 架构文档 | `docs/portfolio-architecture.md`（7 段结构） | 面试深度参考资料，补充 README 的设计 rationale |
| Demo 素材 | 静态截图 + 中文标注（5 张） | 精准展示证据点，不受操作流畅度影响 |
| Ruff 范围 | 全部修复（check --fix + format） | 一步到位，机械操作无回归风险 |

## 工作领域

### 1. 文档改写

#### README.md — 作品集叙事入口（8 段，~200 行）

1. **价值主张 + Demo 截图** — 一句话概述 + Workbench timeline 截图
2. **Problem Statement** — 零售客服 Agent 三挑战：安全写操作、意图消歧、可审计性
3. **Architecture Overview** — 12-node pipeline ASCII 流程图 + 双轨决策 + deny-wins
4. **Key Design Decisions** — 7 层写保护、code track 为锚、action_specs 单一来源
5. **Quick Start** — 4 条命令：install → workbench demo → eval → tests
6. **Demo Walkthrough** — 5 组用例表格，嵌入截图
7. **Eval Results** — 30/30 指标卡片
8. **Project Structure** — 精简目录树

旧 Phase 命令文档不删除，但不再作为主入口。README 自包含。

#### docs/portfolio-architecture.md — 面试深度参考（7 段，~300 行）

1. 系统概述
2. 12-Node Pipeline（ASCII 流程图 + 每节点职责 + circuit-breaker）
3. Dual-Track Decision（Code/LLM 职责边界、merge 规则、code track 锚定原理）
4. 7-Layer Write Guard（逐层详述）
5. ToolGateway & Action Specs（读写分离、单一事实来源、自动发现）
6. Eval & Trace Infrastructure（curated/generalized、14 种失败分类、artifact 契约）
7. Workbench（demo/调试/未来 AgentOps 产品化中的角色）

#### 历史文档归档

保留 `docs/superpowers/` 下所有 Phase 4/5 spec 和 plan。`docs/` 根目录只保留：`long-term-optimization-path.md`、`portfolio-architecture.md`、`phase5-capability-matrix.md`、`superpowers/`。

### 2. Workbench Demo 打磨

**约束**: 不改组件架构和路由，只调 case 标签、默认顺序、信息层级、关键状态展示。

#### Case 分组（按用户旅程）

```text
🔐 身份认证
  - 姓名+邮编认证查询订单 (auth_name_zip_lookup_order)

✅ 成功写操作
  - 取消待处理订单 (cancel_pending_order)
  - 退回已送达商品 (return_delivered_order_item)
  - 修改待处理订单商品 (modify_pending_order_items_success)
  - 修改待处理订单支付方式 (modify_pending_order_payment_success)

🛡️ 写保护阻止
  - 阻止访问他人订单 (block_wrong_user_order_access)
  - 阻止跨商品替换 (block_item_product_mismatch)
  - 阻止余额不足礼品卡支付 (block_payment_insufficient_gift_card)

🔄 用户确认流程
  - 拒绝取消确认 (deny_cancel_confirmation)

📞 边界能力
  - 转接人工客服 (transfer_to_human)
```

#### Timeline 信息层级

- **主要（视觉突出）**: Intent + Slots、Policy Decision、Tool Call / Guard Block 原因、Write Audit
- **次要（默认折叠或缩小）**: 12 个 pipeline step 节点、消息气泡

#### Pending Action 突出

在 Business State 面板中用醒目样式（橙色边框 + 背景）突出待确认操作卡片。

#### 变更清单

| 文件 | 变更 |
|------|------|
| `app/workbench/cases.py` | CASE_TITLES 优化、DEMO_CASE_IDS 按叙事重排、新增 CASE_GROUPS |
| `workbench/src/labels.ts` | 新增 group 相关标签、STATUS_LABELS 补充 |
| `workbench/src/types.ts` | CaseCatalog 新增 groups 字段 |
| `workbench/src/components/` | CaseSelector 支持分组渲染、Timeline 信息层级、PendingAction 突出 |
| `workbench/src/styles.css` | Pending action 高亮样式、timeline 事件权重样式 |

### 3. Demo 素材

5 张关键截图存入 `docs/demo-screenshots/`：

1. `workbench-overview.png` — 全屏：选中 case + business state + timeline + pending action
2. `guard-block.png` — timeline 聚焦 guard block 事件：block reason 详情展开
3. `write-audit.png` — timeline 聚焦 write audit：DB hash、idempotency key
4. `confirmation-pending.png` — pending action 卡片特写
5. `eval-passing.png` — 终端 `phase2-eval` 输出 30/30

每张截图带一句中文描述。README 中按叙事分组嵌入对应截图。

### 4. 工程卫生

```bash
uv run ruff check --fix .   # 修复 12 个 I001 import 排序
uv run ruff format .         # 格式化 35 个文件
```

无逻辑变更。

## 验收标准

1. README 作为项目作品集入口独立可读，不依赖旧 phase 文档
2. 新读者可通过 README 的 Quick Start 跑起 Workbench demo 和 eval 命令
3. Workbench 变更不引入新组件架构或路由复杂度
4. Demo 截图可用
5. `uv run python -m pytest tests/ -q` 通过
6. `uv run ruff check .` 通过（零输出）
7. `uv run ruff format --check .` 通过（零输出）
8. `uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json` 报告 30/30
9. `cd workbench && npm run build` 通过
