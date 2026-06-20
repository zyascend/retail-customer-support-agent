# 工台界面优化设计文档

> 日期: 2026-06-20
> 状态: 已批准

## 1. 概述

优化零售客服工作台 (Workbench) 的用户界面体验，聚焦两个核心方向：

1. **左侧 Case 列表** — 从有限 demo case 下拉框改为全量 82 个 case 的分组折叠树
2. **右侧 Inspector** — 从 raw JSON 展示改为按事件类型定制的结构化信息卡片

### 1.1 设计原则

- **零 JSON 展示**: 所有数据以标签-值的形式结构化渲染，不使用 `<pre>` 或 `JSON.stringify`
- **信息筛选**: 只展示对调试/验证有意义的字段，隐藏内部 ID、空值等
- **高可读性**: 中文标签、状态彩色 Badge、合理间距和视觉层次
- **数据驱动**: 左栏分组由后端 case 元数据自动生成，无需手动维护

## 2. 当前状态

### 2.1 布局

```
┌──────────┬──────────────────────────────┬──────────────┐
│ LEFT     │ MIDDLE                       │ RIGHT        │
│ w-64     │ flex-1                       │ w-72         │
│          │                              │              │
│ RunCtrl  │ BusinessState                │ Inspector    │
│ ──────── │ ──────────────────────────── │ ─────────── │
│ 演示/全部│ Conversation                  │ Trace 文件   │
│ 模式下拉  │                              │ 事件 ID      │
│ 案例下拉  │ Timeline                      │ 事件详情     │
│ step/run │                              │ (JSON <pre>) │
│ 手动消息  │                              │ 阻止记录     │
│ 发送     │                              │ (JSON <pre>) │
└──────────┴──────────────────────────────┴──────────────┘
```

### 2.2 问题

- **左侧**: 案例选择为 `<select>` 下拉框，全量 82 个 case 无法良好展示；`groups` 仅覆盖 14 个 demo case
- **右侧**: `Inspector` 组件展示 `event.detail` 和 `guard_blocks` 为 raw JSON (`<pre>`)，可读性差

### 2.3 后端数据结构

```python
# Case 层次 (来源: app/workbench/cases.py)
# all_cases 已包含 3 个子集，共 82 个 case
- generalized_mvp (30)   # 手工构造的基础测试集
  ├ auth, cancel, confirmation, exchange, guard
  ├ lookup, modify_address, modify_items, modify_payment
  ├ return, transfer
- synthetic_seeded_v1 (7) # Synthetic 世界场景
  ├ modify_shipping, transfer
- generalization (45)     # LLM 生成的泛化场景
  ├ cancel, guard, modify_shipping, transfer
```

## 3. 新布局设计（方案 C）

### 3.1 整体布局

```
┌─────────────┬───────────────────────────┬──────────────────┐
│ HEADER                                              [🌙] │
├──────────────┬──────────────────────────┬─────────────────┤
│ LEFT (w-72)  │ MIDDLE (flex-1)          │ RIGHT (w-80)    │
│              │ [Step] [Run All] [Reset]  │                 │
│ Case 分组树  │ ──────────────────────── │ 事件详情卡片    │
│ (可滚动)     │ BusinessState             │ (按类型定制)    │
│ ▼ 基础集     │ Conversation              │                 │
 │ ├ 身份      │                          │ ┌─────────────┐ │
│  ├ 取消      │  [手动消息输入...] [发送]  │ │ Tool Call   │ │
│  ├ 写保护    │                          │ │ ├ 工具名     │ │
│  ├ 确认      │  Timeline                │ │ ├ 状态 ✅    │ │
│ ▼ Synthetic │                          │ │ ├ 参数表     │ │
│ ▼ 泛化集     │                          │ │ ├ 结果       │ │
│              │                          │ │ └ 变更       │ │
│              │                          │ └─────────────┘ │
└──────────────┴──────────────────────────┴─────────────────┘
```

### 3.2 布局变化

| 区域 | 原方案 | 新方案 |
|------|--------|--------|
| **Header** | 标题 + surface 切换 + 模式 | 保持 + 右侧 `[模式]` Badge |
| **Left** | RunControl (下拉 + 按钮 + 消息) | Case 分组折叠树 (纯列表) |
| **Middle 顶部** | — | 新增 Step/Run/Reset 行内按钮组 |
| **Middle 底部-消息** | Left 栏内 | 移到 Conversation 下方 |
| **Right** | Inspector (JSON) | 事件详情卡片 (结构化 UI) |

### 3.3 控制与消息位置变化

- Step / Run All / Reset 按钮 → 移到 BusinessState 上方行内
- 手动消息输入框 + 发送按钮 → 移到 Conversation 下方
- 左栏释放出完整垂直空间给 Case 树

## 4. 左侧: Case 分组树组件

### 4.1 数据来源

后端 `config.case_catalog` 已包含全部 82 个 case 的序列化数据 (`all_cases`)。前端按 `subset` + `category` 字段动态构建分组树，无需新增 API。

### 4.2 分组层次

```
Level 1: subset (数据集)
  └─ Level 2: category (类别)
      └─ Case 条目
```

| 数据集 | 组 | Case 数 |
|--------|----|---------|
| 🧪 **基础集** generalized_mvp | 🔐 身份认证 auth | 1 |
| | 📋 订单查询 lookup | 1 |
| | ✅ 取消订单 cancel | 1 |
| | 🛡️ 写保护 guard | 12 |
| | 🔄 确认流程 confirmation | 5 |
| | 🤝 转接 transfer | 2 |
| | 📦 修改商品 modify_items | 1 |
| | 💳 修改支付 modify_payment | 1 |
| | 📮 修改地址 modify_address | 2 |
| | ↩️ 换货 exchange | 2 |
| | 📤 退货 return | 2 |
| 🧬 **Synthetic 世界** synthetic_seeded_v1 | 🚚 配送修改 modify_shipping | 6 |
| | 📞 转接 transfer | 1 |
| 🧠 **泛化集** generalization | ✅ 取消订单 cancel | 9 |
| | 🛡️ 写保护 guard | 6 |
| | 🚚 配送修改 modify_shipping | 15 |
| | 📞 转接 transfer | 15 |

### 4.3 Case 条目展示字段

每个 case 条目在树中显示为多行信息卡片：

```
  ┌─ 取消待处理订单
  │   意图: 取消订单 · 工具: cancel_pending_order
  │   消息: 3条 · 策略: order_lifecycle
  │   预期: 写操作成功 · 订单状态: pending → cancelled
```

**展示字段优先级**：

| 行 | 字段 | 类型 | 说明 |
|----|------|------|------|
| 标题 | `title` | 加粗主行 | 中文标题 |
| L1 | `expected_intent` + `expected_tool_names[0]` | 次要信息行 | 意图标签和工具名 |
| L2 | `message_count` + `expected_order_status` | 次要信息行 | 消息数和预期订单状态 |
| L3 | `policy_area` / `expected_guard_block_reason` | 次要信息行 | 策略领域或阻止原因 |
| L4 | `subset` + `scenario_family` / `capability` | 次要信息行 | 子集和场景能力 |

### 4.4 交互设计

| 交互 | 行为 |
|------|------|
| 点击分组标题 | 展开/折叠该分组 |
| 点击 case 行 | 选中 case + 调用 `selectCase` API |
| 选中状态 | 左边框蓝色高亮 + 浅蓝背景色 |
| 未选中 | 无特殊样式 |
| 滚动 | 左栏 `overflow-y-auto` 独立滚动 |
| 分组初始状态 | 全部展开 |

- 去掉当前「演示/全部」切换按钮
- 去掉模式选择器（当前仅 LLM 模式，后续如需再添加）
- Step/Run/Reset 按钮移到中间区域

### 4.5 底部当前选中摘要

固定在左栏底部，展示选中 case 的关键字段：

```
  当前: 取消待处理订单
  意图: 取消 · 工具: cancel_pending_order · 3 条消息
```

## 5. 右侧: 事件详情卡片

### 5.1 通用卡片结构

所有卡片共享相同的容器样式：

```
┌──────────────────────────────┐
│ [Icon] 标题          权重标签 │  ← 头部
│ ──────────────────────────── │
│                              │
│  字段行/区块                  │  ← 内容区
│                              │
└──────────────────────────────┘
```

### 5.2 Tool Call 卡片

适用事件: `kind === "tool_call"`，数据来自 `ToolCallRecord` 序列化

```
┌──────────────────────────────────┐
│ 🔧 工具调用               ● 关键 │
│ ──────────────────────────────── │
│                                  │
│  工具名   cancel_pending_order    │
│  状态     ✅ 成功                 │
│                                  │
│ ── 参数 ──                        │
│   order_id    ORD-001            │
│   user_id     user_abc123        │
│   reason      "不想要了"          │
│                                  │
│ ── 结果 ──                        │
│   订单 #ORD-001 已成功取消         │
│   退款金额: ¥299.00               │
│   执行时间: 1.2s                  │
│                                  │
│ ── DB Hash ──                    │
│   a1b2c3d4 → e5f6g7h8           │
└──────────────────────────────────┘
```

**阻止状态变体**:

```
│  状态     🔒 已阻止               │
│ ── 阻止原因 ──                    │
│   ⚠️ 写保护拦截                    │
│   订单 #ORD-001 状态为             │
│   "processed"，不允许修改地址       │
```

**渲染规则**:
- `status === "blocked"` → 显示阻塞原因区块（红色警告样式），不显示结果
- `status === "error"` → 显示错误消息区块（红色错误样式），不显示结果
- `status === "success"` → 显示结果区块
- `arguments` 渲染为键值对表格，非 JSON
- `observation` 如为 dict 则提取关键字段展示，如为 string 直接展示
- `tool_kind` 显示为标签（read/write）
- `before_db_hash` / `after_db_hash` 仅在两者不同时展示（表示数据库有变更）

### 5.3 Step 卡片

适用事件: `kind === "step"`，数据来自 `AgentStep.detail` 序列化

```
┌──────────────────────────────────┐
│ ⚙️ 管道步骤               ● 关键 │
│ ──────────────────────────────── │
│                                  │
│  步骤     策略判断                 │
│  状态     ✅ 正常                  │
│                                  │
│ ── 决策 ──                       │
│   允许取消待处理订单                │
│   理由: 订单状态为 pending          │
│   策略领域: order_lifecycle        │
└──────────────────────────────────┘
```

**分节点展示**:

| Step 节点 | 卡片标题 | 展示字段 |
|-----------|---------|---------|
| `receive_message` | 接收消息 | content |
| `preflight_identity` | 预检身份 | method, user_id / name+zip |
| `preflight_confirmation` | 预检确认 | resolution |
| `intent_and_slot_extractor` | 意图和槽位提取 | intent, slots 关键字段 |
| `policy_reasoner` | 策略判断 | decision, explanation, reasoning |
| `write_action_guard` | 写保护 | reason, block_context 关键字段 |
| `action_planner` | 动作规划 | planned_action, arguments |
| `tool_executor` | 工具执行 | tool_name, status |
| `tool_execute` | 工具执行 | tool_name, status |
| `pending_set` | 待确认操作 | tool_name |
| `llm_reason` | LLM 推理 | finish_reason |
| `provider_unavailable` | Provider 不可用 | (无额外字段) |
| `consecutive_failures_limit` | 连续失败 | (无额外字段) |
| `finalize` | 结束 | (无额外字段) |
| 通用兜底 | 未知步骤 | detail 各字段逐行展示 |

### 5.4 Message 卡片

适用事件: `kind === "message"`，数据来自 `Message` 序列化

```
┌──────────────────────────────────┐
│ 💬 消息                  ○ 辅助  │
│ ──────────────────────────────── │
│                                  │
│  角色      User                   │
│  时间      2025-06-20 14:30:22    │
│                                  │
│ ── 内容 ──                        │
│   "你好，我想取消我的订单"          │
└──────────────────────────────────┘
```

**渲染规则**:
- `role` 显示为中文标签（User / Assistant / Tool / System）
- `content` 直接展示
- `created_at` 格式化显示
- `name` 可选字段

### 5.5 Write Audit 卡片

适用事件: `kind === "write_audit"`，数据来自 `audit_logs` 条目序列化

```
┌──────────────────────────────────┐
│ 📝 写入审计               ● 关键 │
│ ──────────────────────────────── │
│                                  │
│  操作      cancel_pending_order   │
│  状态      ✅ 已完成               │
│                                  │
│ ── 变更 ──                        │
│   订单 ORD-001                    │
│   状态: pending → cancelled       │
│   退款: ¥299.00                   │
│                                  │
│ ── DB Hash ──                    │
│   a1b2c3d4 → e5f6g7h8           │
└──────────────────────────────────┘
```

### 5.6 Guard Blocks 处理

`guard_blocks` 不再单独展示。阻止操作已在 timeline 中以 `status: "blocked"` 的 `tool_call` 事件呈现，可与 Tool Call 卡片一同展示。

## 6. 组件架构

### 6.1 新增/修改组件

| 组件 | 类型 | 说明 |
|------|------|------|
| `CaseTree` | 新增 | 左侧分组折叠树，替代 RunControl 中的 case 列表 |
| `CaseTreeGroup` | 新增 | 单个分组（可折叠） |
| `CaseTreeItem` | 新增 | 单个 case 条目（多行信息） |
| `EventDetailPanel` | 新增 | 右侧事件详情容器，路由到不同卡片 |
| `ToolCallCard` | 新增 | 工具调用详情卡片 |
| `StepCard` | 新增 | 管道步骤详情卡片 |
| `MessageCard` | 新增 | 消息详情卡片 |
| `WriteAuditCard` | 新增 | 写入审计详情卡片 |
| `StatusBadge` | 已有 | 状态 Badge (复用) |

### 6.2 修改现有组件

| 组件 | 修改 |
|------|------|
| `RunControl` | 移除 case 列表 + 演示/全部切换 + 模式选择；保留 Step/Run/Reset 按钮和手动消息，但按钮改为纯行内传递到父组件 |
| `App` | 调整 `demo-layout` 布局；Step/Run/Reset 按钮转移到 BusinessState 上方；手动消息转移到 Conversation 下方；引入 `CaseTree` 和 `EventDetailPanel` |
| `Inspector` | 替换为 `EventDetailPanel` |

### 6.3 新增工具函数

| 函数 | 说明 |
|------|------|
| `buildCaseTree(catalog)` | 将 `all_cases` 按 `subset` + `category` 分组，返回树结构 |
| `renderDetail(event)` | 根据 `event.kind` 分发到对应的卡片组件 |
| `formatArgs(args)` | 将 arguments dict 渲染为键值对列表（非 JSON） |
| `extractObservation(obs)` | 从 observation 中提取关键字段展示 |

### 6.4 分组树数据结构

```typescript
interface CaseTreeNode {
  key: string;
  label: string;
  emoji: string;
  subset: string;
  children: CaseTreeGroup[];
}

interface CaseTreeGroup {
  category: string;
  label: string;
  emoji: string;
  cases: WorkbenchCase[];
}
```

## 7. 数据流

```
1. 页面加载 → fetchConfig() → config.case_catalog.all_cases
2. buildCaseTree() → 按 subset+categories 分组 → 渲染左侧树
3. 用户点击 case → onSelectCase(caseId) → API selectCase
4. API 返回 snapshot → 更新 timeline + messages + business
5. 用户点击 timeline 事件 → setSelectedEventId
6. EventDetailPanel → 根据 event.kind 选择卡片 → renderDetail(event)
```

## 8. 不变部分

以下功能和组件保持不变：

- **Header**: 标题、surface 切换（Demo/AgentOps）、主题切换
- **BusinessState**: 业务状态上下文卡片（已结构良好，无须改动）
- **Conversation**: 对话消息列表（已结构良好，无须改动）
- **Timeline**: 管道时间线可视化（已结构良好，无须改动）
- **Bottom summary bar**: 选中事件的状态摘要（Timeline 组件底部部分）
- **API 层**: server 端不变，前端仅消费已有 API

## 9. 样式说明

- 使用项目已有设计语言：Tailwind CSS、`border-slate-200` 卡片边框、`bg-[#f4f6f8]` 背景
- 卡片容器: `border rounded-lg bg-white p-3` 浅色 / `dark:bg-slate-800 dark:border-slate-700` 暗色
- 状态 Badge: 复用 `StatusBadge` 组件
- 分组折叠: 使用 CSS `details/summary` 或简单 state toggle + transition
- 选中高亮: 左边框 + 背景色，不做大幅视觉变动

## 10. 未纳入范围

- AgentOps surface 的界面优化（后续迭代）
- 后端 case 分组数据的结构调整（前端动态分组即可）
- case 搜索功能（后续根据需求添加）
- case 排序、过滤（后续根据需求添加）
- 性能优化（大规模数据虚拟滚动等）

## 11. 实现顺序

1. 创建 `buildCaseTree` 工具函数 + `CaseTree` / `CaseTreeGroup` / `CaseTreeItem` 组件
2. 修改 `App.tsx` 布局：左栏替换为 CaseTree，控制按钮迁移
3. 创建卡片组件：`ToolCallCard` → `StepCard` → `MessageCard` → `WriteAuditCard`
4. 创建 `EventDetailPanel` 替换 `Inspector`
5. 对接左栏选中事件与右侧详情联动
6. 移除旧代码：RunControl 中的 case 列表、Inspector JSON 展示、guard_blocks 独立展示
7. 测试验证