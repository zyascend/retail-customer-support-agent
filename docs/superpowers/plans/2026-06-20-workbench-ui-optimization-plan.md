# Workbench 界面优化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化零售客服工作台界面 — 左侧 Case 列表改为全量分组折叠树，右侧 Inspector 改为事件类型定制信息卡片，两侧面板可收起。

**Architecture:** 前端纯 UI 改造，后端 API 不变。新增 7 个 React 组件（CaseTree + 5 个事件卡片 + EventDetailPanel + CollapseButton）。`RunControl` 从左侧移除，step/run/reset 按钮迁至中间区顶部，手动消息输入迁至 Conversation 下方。`Inspector.tsx` 删除替换为 `EventDetailPanel`。

**Tech Stack:** React 18 + TypeScript + Vite + Tailwind CSS + @phosphor-icons/react

---

## 文件清单

### 新增文件
| 文件 | 职责 |
|------|------|
| `workbench/src/caseTreeUtils.ts` | 分组树构建函数、subset/category 中文标签映射 |
| `workbench/src/components/CaseTree.tsx` | 左侧分组折叠树组件（含 CaseTreeGroup、CaseTreeItem） |
| `workbench/src/components/CollapseButton.tsx` | 通用面板收起/展开按钮 |
| `workbench/src/components/ToolCallCard.tsx` | tool_call 事件详情卡片 |
| `workbench/src/components/StepCard.tsx` | step 事件详情卡片 |
| `workbench/src/components/MessageCard.tsx` | message 事件详情卡片 |
| `workbench/src/components/WriteAuditCard.tsx` | write_audit 事件详情卡片 |
| `workbench/src/components/EventDetailPanel.tsx` | 右侧事件详情容器，路由到对应卡片 |

### 修改文件
| 文件 | 变更 |
|------|------|
| `workbench/src/types.ts` | 添加 `CaseTreeNode` / `CaseTreeCategory` / 事件 Detail 类型 |
| `workbench/src/App.tsx` | 布局改造、控制迁移、引入新组件 |
| `workbench/src/components/RunControl.tsx` | 移除 case 列表/模式选择/演示切换，仅保留手动消息输入 |

### 删除文件
| 文件 | 理由 |
|------|------|
| `workbench/src/components/Inspector.tsx` | 替换为 EventDetailPanel |

---

## 任务分解

### Task 0: 创建功能分支

- [ ] **Step 1: 从 main 创建 feature 分支**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent
git checkout main && git pull
git checkout -b feat/workbench-ui-optimization
```

Expected: 切换到新分支 `feat/workbench-ui-optimization`

---

### Task 1: 添加 Case 树类型和分组工具函数

**Files:**
- Create: `workbench/src/caseTreeUtils.ts`
- Modify: `workbench/src/types.ts`

- [ ] **Step 1: 在 types.ts 添加分组树相关类型**

在 `CaseCatalog` 接口之后添加：

```typescript
// ── Case Tree ──

export interface CaseTreeCategory {
  key: string;
  label: string;
  emoji: string;
  cases: WorkbenchCase[];
}

export interface CaseTreeNode {
  key: string;
  label: string;
  emoji: string;
  categories: CaseTreeCategory[];
}
```

- [ ] **Step 2: 创建 caseTreeUtils.ts**

```typescript
import type { CaseTreeNode, CaseTreeCategory, WorkbenchCase } from "./types";

// Subset → Chinese label + emoji
export const SUBSET_META: Record<string, { label: string; emoji: string }> = {
  generalized_mvp: { label: "基础集", emoji: "🧪" },
  synthetic_seeded_v1: { label: "Synthetic 世界", emoji: "🧬" },
  generalization: { label: "泛化集", emoji: "🧠" },
};

// Category → Chinese label + emoji
export const CATEGORY_META: Record<string, { label: string; emoji: string }> = {
  auth: { label: "身份认证", emoji: "🔐" },
  lookup: { label: "订单查询", emoji: "📋" },
  cancel: { label: "取消订单", emoji: "✅" },
  guard: { label: "写保护", emoji: "🛡️" },
  confirmation: { label: "确认流程", emoji: "🔄" },
  transfer: { label: "转接", emoji: "📞" },
  modify_items: { label: "修改商品", emoji: "📦" },
  modify_payment: { label: "修改支付", emoji: "💳" },
  modify_address: { label: "修改地址", emoji: "📮" },
  modify_shipping: { label: "配送修改", emoji: "🚚" },
  exchange: { label: "换货", emoji: "↩️" },
  return: { label: "退货", emoji: "📤" },
};

export function buildCaseTree(allCases: WorkbenchCase[]): CaseTreeNode[] {
  // Group by subset
  const bySubset = new Map<string, WorkbenchCase[]>();
  for const c of allCases {
    const key = c.subset || "other";
    if (!bySubset.has(key)) bySubset.set(key, []);
    bySubset.get(key)!.push(c);
  }

  const tree: CaseTreeNode[] = [];
  for (const [subsetKey, cases] of bySubset) {
    // Group cases within subset by category
    const byCategory = new Map<string, WorkbenchCase[]>();
    for (const c of cases) {
      const catKey = c.category || "other";
      if (!byCategory.has(catKey)) byCategory.set(catKey, []);
      byCategory.get(catKey)!.push(c);
    }

    const categories: CaseTreeCategory[] = [];
    for (const [catKey, catCases] of byCategory) {
      const meta = CATEGORY_META[catKey] || { label: catKey, emoji: "📁" };
      categories.push({
        key: catKey,
        label: meta.label,
        emoji: meta.emoji,
        cases: catCases,
      });
    }

    // Sort categories
    const categoryOrder = Object.keys(CATEGORY_META);
    categories.sort((a, b) => {
      const ia = categoryOrder.indexOf(a.key);
      const ib = categoryOrder.indexOf(b.key);
      return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
    });

    const subsetMeta = SUBSET_META[subsetKey] || { label: subsetKey, emoji: "📦" };
    tree.push({
      key: subsetKey,
      label: subsetMeta.label,
      emoji: subsetMeta.emoji,
      categories,
    });
  }

  // Sort subsets: generalized_mvp first, then synthetic, then others
  const subsetOrder = ["generalized_mvp", "synthetic_seeded_v1"];
  tree.sort((a, b) => {
    const ia = subsetOrder.indexOf(a.key);
    const ib = subsetOrder.indexOf(b.key);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });

  return tree;
}
```

Note: Fix the `for const` to `for (const`. Write the file with correct syntax.

```typescript
// Syntax corrections for the above:
export function buildCaseTree(allCases: WorkbenchCase[]): CaseTreeNode[] {
  const bySubset = new Map<string, WorkbenchCase[]>();
  for (const c of allCases) {
    const key = c.subset || "other";
    if (!bySubset.has(key)) bySubset.set(key, []);
    bySubset.get(key)!.push(c);
  }
  // ... rest as above
}
```

- [ ] **Step 3: Commit**

```bash
git add workbench/src/types.ts workbench/src/caseTreeUtils.ts
git commit -m "feat: add case tree types and grouping utilities"
```

---

### Task 2: 创建 CaseTree 组件

**Files:**
- Create: `workbench/src/components/CaseTree.tsx`

- [ ] **Step 1: 实现 CaseTree 组件（含 CaseTreeGroup、CaseTreeItem）**

```tsx
import { useMemo, useState } from "react";
import { buildCaseTree, CATEGORY_META } from "../caseTreeUtils";
import type { CaseCatalog, CaseTreeCategory, CaseTreeNode, WorkbenchCase } from "../types";

interface CaseTreeProps {
  catalog: CaseCatalog;
  selectedCaseId: string | null;
  onSelectCase: (caseId: string) => void;
}

export function CaseTree({ catalog, selectedCaseId, onSelectCase }: CaseTreeProps) {
  const tree = useMemo(() => buildCaseTree(catalog.all_cases), [catalog.all_cases]);
  const selectedCase = catalog.all_cases.find((c) => c.case_id === selectedCaseId);

  return (
    <section className="min-w-0 h-full flex flex-col border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800" aria-label="案例列表">
      <div className="px-3 py-2.5 border-b border-slate-200 dark:border-slate-700">
        <h2 className="m-0 text-base leading-tight text-[#182230] dark:text-white font-bold">
          案例
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto px-1 py-1">
        {tree.map((node) => (
          <CaseTreeGroup
            key={node.key}
            node={node}
            selectedCaseId={selectedCaseId}
            onSelectCase={onSelectCase}
          />
        ))}
        {tree.length === 0 && (
          <div className="border border-dashed border-slate-300 dark:border-slate-600 rounded-lg text-slate-500 dark:text-slate-400 p-3.5 m-2 text-sm">
            暂无案例。
          </div>
        )}
      </div>

      {selectedCase && (
        <div className="shrink-0 px-3 py-2 border-t border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
          <div className="text-xs text-slate-500 dark:text-slate-400 font-extrabold tracking-normal mb-0.5">当前</div>
          <div className="text-sm font-bold text-[#182230] dark:text-white truncate">{selectedCase.title}</div>
          <div className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
            {intentLabel(selectedCase.expected_intent)} · {selectedCase.message_count}条消息
            {selectedCase.expected_tool_names.length > 0 && ` · ${selectedCase.expected_tool_names[0]}`}
          </div>
        </div>
      )}
    </section>
  );
}

// ── Sub-components ──

interface CaseTreeGroupProps {
  node: CaseTreeNode;
  selectedCaseId: string | null;
  onSelectCase: (caseId: string) => void;
}

function CaseTreeGroup({ node, selectedCaseId, onSelectCase }: CaseTreeGroupProps) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="mb-1">
      <button
        className="flex items-center gap-1.5 w-full px-2 py-1.5 text-sm font-bold text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50 rounded-md cursor-pointer border-0 bg-transparent text-left transition-colors duration-100"
        onClick={() => setExpanded(!expanded)}
        type="button"
      >
        <span className="text-xs text-slate-400 shrink-0 w-3">
          {expanded ? "▼" : "▶"}
        </span>
        <span className="shrink-0">{node.emoji}</span>
        <span className="flex-1 truncate">{node.label}</span>
        <span className="text-xs text-slate-400 font-normal shrink-0">
          {node.categories.reduce((sum, cat) => sum + cat.cases.length, 0)}
        </span>
      </button>

      {expanded && (
        <div className="ml-1 pl-1 border-l-2 border-slate-200 dark:border-slate-700">
          {node.categories.map((category) => (
            <CaseTreeCategoryGroup
              key={category.key}
              category={category}
              selectedCaseId={selectedCaseId}
              onSelectCase={onSelectCase}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface CaseTreeCategoryGroupProps {
  category: CaseTreeCategory;
  selectedCaseId: string | null;
  onSelectCase: (caseId: string) => void;
}

function CaseTreeCategoryGroup({ category, selectedCaseId, onSelectCase }: CaseTreeCategoryGroupProps) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="mb-0.5">
      <button
        className="flex items-center gap-1 w-full px-2 py-1 text-xs font-semibold text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700/30 rounded-md cursor-pointer border-0 bg-transparent text-left transition-colors duration-100"
        onClick={() => setExpanded(!expanded)}
        type="button"
      >
        <span className="text-[10px] text-slate-400 shrink-0 w-2.5">
          {expanded ? "▼" : "▶"}
        </span>
        <span className="shrink-0">{category.emoji}</span>
        <span className="ml-0.5 flex-1 truncate">{category.label}</span>
        <span className="text-[10px] text-slate-400 font-normal">{category.cases.length}</span>
      </button>

      {expanded && (
        <div className="ml-2">
          {category.cases.map((c) => (
            <CaseTreeItem
              key={c.case_id}
              caseData={c}
              isSelected={c.case_id === selectedCaseId}
              onSelect={onSelectCase}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface CaseTreeItemProps {
  caseData: WorkbenchCase;
  isSelected: boolean;
  onSelect: (caseId: string) => void;
}

function CaseTreeItem({ caseData: c, isSelected, onSelect }: CaseTreeItemProps) {
  return (
    <button
      className={
        "w-full text-left border-0 bg-transparent px-2 py-1.5 rounded-md cursor-pointer transition-colors duration-100 " +
        (isSelected
          ? "bg-blue-50 dark:bg-blue-900/20 shadow-[inset_3px_0_0_0] shadow-blue-500"
          : "hover:bg-slate-50 dark:hover:bg-slate-700/20")
      }
      onClick={() => onSelect(c.case_id)}
      type="button"
    >
      <div className="text-sm font-semibold text-[#182230] dark:text-white leading-tight truncate">
        {c.title}
      </div>
      <div className="text-[11px] text-slate-500 dark:text-slate-400 leading-tight mt-0.5 truncate">
        {intentLabel(c.expected_intent)}
        {c.expected_tool_names.length > 0 && ` · ${c.expected_tool_names[0]}`}
      </div>
      <div className="text-[11px] text-slate-400 dark:text-slate-500 leading-tight mt-px truncate">
        {c.message_count}条消息
        {c.policy_area && ` · ${policyAreaLabel(c.policy_area)}`}
        {c.expected_guard_block_reason && ` · 阻止: ${c.expected_guard_block_reason}`}
      </div>
      {c.subset && c.scenario_family && (
        <div className="text-[11px] text-slate-400 dark:text-slate-500 leading-tight mt-px truncate">
          {c.subset} · {c.scenario_family || c.capability || ""}
        </div>
      )}
    </button>
  );
}

// ── Label helpers ──

function intentLabel(intent: string): string {
  const map: Record<string, string> = {
    lookup: "查询订单",
    cancel_order: "取消订单",
    modify_order_address: "修改地址",
    return_items: "退货",
    exchange_items: "换货",
    transfer: "转人工",
    unknown: "未知",
  };
  return map[intent] || intent;
}

function policyAreaLabel(area: string): string {
  const map: Record<string, string> = {
    shipping: "配送",
    coupon: "优惠券",
    order_lifecycle: "订单生命周期",
    order_status: "订单状态",
    inventory: "库存",
    authentication: "认证",
    payment_method: "支付方式",
    confirmation: "确认",
    user_profile: "用户信息",
    return_items: "退货",
    exchange_items: "换货",
    transfer: "转接",
  };
  return map[area] || area;
}
```

- [ ] **Step 2: Commit**

```bash
git add workbench/src/components/CaseTree.tsx
git commit -m "feat: add CaseTree component with grouped case list"
```

---

### Task 3: 创建 CollapseButton 组件

**Files:**
- Create: `workbench/src/components/CollapseButton.tsx`

- [ ] **Step 1: 实现 CollapseButton**

```tsx
import { CaretLeft, CaretRight } from "@phosphor-icons/react";

interface CollapseButtonProps {
  collapsed: boolean;
  side: "left" | "right";
  onToggle: () => void;
  ariaLabel: string;
}

export function CollapseButton({ collapsed, side, onToggle, ariaLabel }: CollapseButtonProps) {
  const Icon = collapsed
    ? (side === "left" ? CaretRight : CaretLeft)
    : (side === "left" ? CaretLeft : CaretRight);

  const positionClass = side === "left"
    ? "right-0 translate-x-1/2"
    : "left-0 -translate-x-1/2";

  return (
    <button
      aria-label={ariaLabel}
      className={
        "absolute top-1/2 -translate-y-1/2 z-10 " + positionClass + " " +
        "inline-flex items-center justify-center w-5 h-10 border border-slate-300 dark:border-slate-600 " +
        "rounded-full bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 " +
        "hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-700 dark:hover:text-slate-200 " +
        "cursor-pointer transition-colors duration-150 shadow-sm"
      }
      onClick={onToggle}
      type="button"
    >
      <Icon size={12} weight="bold" />
    </button>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add workbench/src/components/CollapseButton.tsx
git commit -m "feat: add CollapseButton component for side panel toggle"
```

---

### Task 4: 创建事件详情卡片组件

**Files:**
- Create: `workbench/src/components/ToolCallCard.tsx`
- Create: `workbench/src/components/StepCard.tsx`
- Create: `workbench/src/components/MessageCard.tsx`
- Create: `workbench/src/components/WriteAuditCard.tsx`

This task has 4 sub-steps, one per card component.

- [ ] **Step 1: 创建 ToolCallCard**

```tsx
import { StatusBadge } from "./StatusBadge";
import type { TimelineEvent } from "../types";

interface ToolCallCardProps {
  event: TimelineEvent;
}

export function ToolCallCard({ event }: ToolCallCardProps) {
  const detail = event.detail as Record<string, unknown> | null;
  if (!detail) {
    return <EmptyCard kind="tool_call" />;
  }

  const toolName = detail.tool_name as string || event.label;
  const status = event.status || (detail.status as string) || "";
  const toolKind = detail.tool_kind as string || "";
  const args = detail.arguments as Record<string, unknown> | undefined;
  const observation = detail.observation;
  const error = detail.error as string | undefined;
  const blockContext = detail.block_context as Record<string, unknown> | undefined;

  return (
    <div className="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3">
      <div className="flex items-center justify-between gap-2 mb-2.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="shrink-0">🔧</span>
          <h3 className="m-0 text-sm font-bold text-[#182230] dark:text-white truncate">工具调用</h3>
        </div>
        <EventWeightBadge weight={event.weight} />
      </div>

      <div className="grid gap-2">
        <InfoRow label="工具名" value={toolName} />
        <InfoRow label="状态" value={<StatusBadge label={statusLabel(status)} tone={statusTone(status)} />} />
        {toolKind && <InfoRow label="类型" value={toolKind === "write" ? "写入" : toolKind === "read" ? "读取" : toolKind} />}

        {args && Object.keys(args).length > 0 && (
          <>
            <div className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 mt-1">参数</div>
            <div className="bg-[#f8fafc] dark:bg-slate-700/30 rounded-lg p-2 border border-slate-200 dark:border-slate-700">
              {Object.entries(args).map(([key, value]) => (
                <div key={key} className="flex gap-2 text-xs py-0.5">
                  <span className="text-slate-500 dark:text-slate-400 shrink-0 font-medium">{key}</span>
                  <span className="text-[#182230] dark:text-white break-all">{formatValue(value)}</span>
                </div>
              ))}
            </div>
          </>
        )}

        {status === "blocked" && (
          <>
            <div className="text-xs font-extrabold tracking-normal text-red-500 dark:text-red-400 mt-1">
              ⚠️ 阻止原因
            </div>
            <div className="border border-red-200 dark:border-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-900 dark:text-red-300 p-2.5 text-xs">
              {error || "写保护拦截"}
              {blockContext && Object.keys(blockContext).length > 0 && (
                <div className="mt-1 text-red-700 dark:text-red-400">
                  {Object.entries(blockContext).map(([k, v]) => (
                    <div key={k} className="flex gap-2">
                      <span className="font-medium">{k}:</span>
                      <span>{formatValue(v)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {status === "error" && (
          <>
            <div className="text-xs font-extrabold tracking-normal text-red-500 dark:text-red-400 mt-1">❌ 错误</div>
            <div className="border border-red-200 dark:border-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-900 dark:text-red-300 p-2.5 text-xs">{error || "执行错误"}</div>
          </>
        )}

        {status === "success" && observation && (
          <>
            <div className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 mt-1">结果</div>
            <div className="bg-[#f8fafc] dark:bg-slate-700/30 rounded-lg p-2 border border-slate-200 dark:border-slate-700 text-xs text-[#182230] dark:text-white">
              {renderObservation(observation)}
            </div>
          </>
        )}

        {detail.before_db_hash && detail.after_db_hash && detail.before_db_hash !== detail.after_db_hash && (
          <>
            <div className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 mt-1">DB Hash</div>
            <div className="text-xs text-slate-500 dark:text-slate-400 font-mono truncate">
              {(detail.before_db_hash as string).slice(0, 8)} → {(detail.after_db_hash as string).slice(0, 8)}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Shared helpers ──

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 shrink-0 w-12">{label}</span>
      <div className="text-sm text-[#182230] dark:text-white min-w-0 truncate">{value}</div>
    </div>
  );
}

function EventWeightBadge({ weight }: { weight: string }) {
  return (
    <span className={
      "shrink-0 inline-flex items-center rounded-full text-[10px] font-extrabold leading-none whitespace-nowrap px-1.5 py-1 " +
      (weight === "primary"
        ? "bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400"
        : "bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400")
    }>
      {weight === "primary" ? "● 关键" : "○ 辅助"}
    </span>
  );
}

function EmptyCard({ kind }: { kind: string }) {
  return (
    <div className="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3">
      <p className="text-slate-500 dark:text-slate-400 text-sm m-0">{kind} 事件无详情数据</p>
    </div>
  );
}

function statusLabel(status: string): string {
  const successStatuses = ["ok", "success", "completed", "complete", "passed"];
  if (successStatuses.includes(status)) return "正常";
  if (status === "blocked") return "已阻止";
  if (status === "error" || status === "failed") return "错误";
  return status;
}

function statusTone(status: string): "neutral" | "good" | "warn" | "bad" {
  const s = status.toLowerCase();
  if (["ok", "success", "completed", "complete", "passed"].includes(s)) return "good";
  if (["blocked", "warning", "pending", "skipped"].includes(s)) return "warn";
  if (["error", "failed", "failure"].includes(s)) return "bad";
  return "neutral";
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function renderObservation(obs: unknown): React.ReactNode {
  if (obs === null || obs === undefined) return <span className="text-slate-400 italic">无返回数据</span>;
  if (typeof obs === "string") return <span>{obs}</span>;
  if (typeof obs === "object" && !Array.isArray(obs)) {
    const entries = Object.entries(obs as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-slate-400 italic">空结果</span>;
    return (
      <div className="grid gap-0.5">
        {entries.map(([k, v]) => (
          <div key={k} className="flex gap-2">
            <span className="text-slate-500 dark:text-slate-400 font-medium shrink-0">{k}</span>
            <span className="text-[#182230] dark:text-white break-all">{formatValue(v)}</span>
          </div>
        ))}
      </div>
    );
  }
  return <span>{String(obs)}</span>;
}
```

- [ ] **Step 2: 创建 StepCard**

```tsx
import { StatusBadge } from "./StatusBadge";
import type { TimelineEvent } from "../types";

interface StepCardProps {
  event: TimelineEvent;
}

const STEP_NODE_LABELS: Record<string, string> = {
  receive_message: "接收消息",
  preflight_identity: "预检身份",
  preflight_confirmation: "预检确认",
  intent_and_slot_extractor: "意图和槽位提取",
  policy_reasoner: "策略判断",
  write_action_guard: "写保护",
  action_planner: "动作规划",
  tool_executor: "工具执行",
  tool_execute: "工具执行",
  pending_set: "待确认操作",
  llm_reason: "LLM 推理",
  provider_unavailable: "Provider 不可用",
  consecutive_failures_limit: "连续失败",
  finalize: "结束",
  conversation_gate: "会话确认",
  context_loader: "上下文加载",
  observation_reducer: "结果归纳",
  response_generator: "回复生成",
  run_logger: "运行记录",
  runtime_error: "运行错误",
};

export function StepCard({ event }: StepCardProps) {
  const detail = event.detail as Record<string, unknown> | null;
  const nodeLabel = STEP_NODE_LABELS[event.label] || event.label;
  const status = event.status || "ok";

  if (!detail) {
    return (
      <div className="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3">
        <CardHeader title="管道步骤" weight={event.weight} />
        <InfoRow label="步骤" value={nodeLabel} />
        <InfoRow label="状态" value={<StatusBadge label={statusLabel(status)} tone={statusTone(status)} />} />
      </div>
    );
  }

  // Determine display sections based on node type
  const sections = getStepSections(event.label, detail);

  return (
    <div className="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3">
      <CardHeader title="管道步骤" weight={event.weight} />

      <div className="grid gap-2">
        <InfoRow label="步骤" value={nodeLabel} />
        <InfoRow label="状态" value={<StatusBadge label={statusLabel(status)} tone={statusTone(status)} />} />

        {sections.map((section, i) => (
          <div key={i}>
            <div className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 mt-1">
              {section.title}
            </div>
            <div className="bg-[#f8fafc] dark:bg-slate-700/30 rounded-lg p-2 border border-slate-200 dark:border-slate-700">
              {section.entries.map(([key, value]) => (
                <div key={key} className="flex gap-2 text-xs py-0.5">
                  <span className="text-slate-500 dark:text-slate-400 shrink-0 font-medium">{key}</span>
                  <span className="text-[#182230] dark:text-white break-all">{String(value ?? "-")}</span>
                </div>
              ))}
            </div>
          </div>
        ))}

        {/* Fallback: show any detail keys not in known sections */}
        {renderFallbackKeys(event.label, detail, sections)}
      </div>
    </div>
  );
}

function getStepSections(node: string, detail: Record<string, unknown>): Array<{ title: string; entries: Array<[string, unknown]> }> {
  switch (node) {
    case "receive_message":
      return [{ title: "内容", entries: Object.entries({ content: detail.content }) }];
    case "preflight_identity":
      return [{ title: "身份信息", entries: Object.entries(detail).filter(([k]) => k !== "status") }];
    case "preflight_confirmation":
      return [{ title: "确认结果", entries: [["resolution", detail.resolution]] }];
    case "intent_and_slot_extractor":
      return [
        { title: "提取结果", entries: Object.entries(detail).filter(([_, v]) => v !== null && v !== undefined) },
      ];
    case "policy_reasoner":
      return [
        { title: "决策", entries: Object.entries(detail).filter(([_, v]) => v !== null && v !== undefined) },
      ];
    case "write_action_guard":
      return [
        { title: "保护判断", entries: Object.entries(detail).filter(([_, v]) => v !== null && v !== undefined) },
      ];
    default:
      return [{ title: "详情", entries: Object.entries(detail).filter(([_, v]) => v !== null && v !== undefined) }];
  }
}

const KNOWN_KEYS = new Set(["status"]);

function renderFallbackKeys(
  node: string,
  detail: Record<string, unknown>,
  sections: Array<{ title: string; entries: Array<[string, unknown]> }>
): React.ReactNode {
  const coveredKeys = new Set(sections.flatMap((s) => s.entries.map(([k]) => k)));
  const fallback = Object.entries(detail).filter(
    ([k, v]) => !coveredKeys.has(k) && !KNOWN_KEYS.has(k) && v !== null && v !== undefined
  );
  if (fallback.length === 0) return null;

  return (
    <div>
      <div className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 mt-1">其他</div>
      <div className="bg-[#f8fafc] dark:bg-slate-700/30 rounded-lg p-2 border border-slate-200 dark:border-slate-700">
        {fallback.map(([key, value]) => (
          <div key={key} className="flex gap-2 text-xs py-0.5">
            <span className="text-slate-500 dark:text-slate-400 shrink-0 font-medium">{key}</span>
            <span className="text-[#182230] dark:text-white break-all">{String(value ?? "-")}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Reuse InfoRow, EventWeightBadge, EmptyCard, statusLabel, statusTone from ToolCallCard
// (In implementation, shared helpers go to a separate utils file or are repeated)

function CardHeader({ title, weight }: { title: string; weight: string }) {
  return (
    <div className="flex items-center justify-between gap-2 mb-2.5">
      <div className="flex items-center gap-1.5 min-w-0">
        <span className="shrink-0">⚙️</span>
        <h3 className="m-0 text-sm font-bold text-[#182230] dark:text-white truncate">{title}</h3>
      </div>
      <EventWeightBadge weight={weight} />
    </div>
  );
}

// Import these from a shared module in actual implementation
function statusLabel(status: string): string {
  const ok = ["ok", "success", "completed", "complete", "passed"];
  if (ok.includes(status)) return "正常";
  if (status === "blocked") return "已阻止";
  if (status === "error" || status === "failed") return "错误";
  return status;
}

function statusTone(status: string): "neutral" | "good" | "warn" | "bad" {
  const s = status.toLowerCase();
  if (["ok", "success", "completed", "complete", "passed"].includes(s)) return "good";
  if (["blocked", "warning", "pending", "skipped"].includes(s)) return "warn";
  if (["error", "failed", "failure"].includes(s)) return "bad";
  return "neutral";
}
```

- [ ] **Step 3: 创建 MessageCard**

```tsx
import type { TimelineEvent } from "../types";

interface MessageCardProps {
  event: TimelineEvent;
}

export function MessageCard({ event }: MessageCardProps) {
  const detail = event.detail as Record<string, unknown> | null;

  return (
    <div className="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3">
      <div className="flex items-center justify-between gap-2 mb-2.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="shrink-0">💬</span>
          <h3 className="m-0 text-sm font-bold text-[#182230] dark:text-white truncate">消息</h3>
        </div>
        <span className="shrink-0 inline-flex items-center rounded-full text-[10px] font-extrabold leading-none whitespace-nowrap px-1.5 py-1 bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400">
          ○ 辅助
        </span>
      </div>

      <div className="grid gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 shrink-0 w-12">角色</span>
          <span className={
            "text-sm font-bold leading-tight " +
            (detail?.role === "assistant" ? "text-blue-600 dark:text-blue-400" :
             detail?.role === "user" ? "text-green-600 dark:text-green-400" : "")
          }>
            {roleLabel(detail?.role as string || event.label)}
          </span>
        </div>
        {detail?.created_at && (
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 shrink-0 w-12">时间</span>
            <span className="text-sm text-[#182230] dark:text-white">{detail.created_at as string}</span>
          </div>
        )}
        {(detail?.content as string) && (
          <>
            <div className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 mt-1">内容</div>
            <div className={
              "border rounded-lg p-2.5 text-sm leading-relaxed " +
              (detail?.role === "assistant"
                ? "border-blue-100 dark:border-blue-900/40 bg-blue-50/50 dark:bg-blue-950/30"
                : detail?.role === "user"
                  ? "border-green-100 dark:border-green-900/40 bg-green-50/30 dark:bg-green-950/20"
                  : "border-slate-200 dark:border-slate-700 bg-[#fbfcfe] dark:bg-slate-800/50")
            }>
              <p className="m-0 break-anywhere text-[#253044] dark:text-slate-200">
                {detail.content as string}
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function roleLabel(role: string): string {
  const map: Record<string, string> = { user: "用户", assistant: "助手", tool: "工具", system: "系统" };
  return map[role] || role;
}
```

- [ ] **Step 4: 创建 WriteAuditCard**

```tsx
import { StatusBadge } from "./StatusBadge";
import type { TimelineEvent } from "../types";

interface WriteAuditCardProps {
  event: TimelineEvent;
}

export function WriteAuditCard({ event }: WriteAuditCardProps) {
  const detail = event.detail as Record<string, unknown> | null;

  if (!detail) {
    return (
      <div className="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3">
        <div className="flex items-center gap-1.5 mb-2.5">
          <span>📝</span>
          <h3 className="m-0 text-sm font-bold text-[#182230] dark:text-white">写入审计</h3>
        </div>
        <p className="text-slate-500 dark:text-slate-400 text-sm m-0">无详情数据</p>
      </div>
    );
  }

  const status = event.status || (detail.status as string) || "";
  const actionName = detail.action_name as string || detail.tool_name as string || event.label;

  // Extract change-related fields
  const changeEntries = Object.entries(detail).filter(
    ([k]) => !["action_name", "tool_name", "status", "timestamp", "created_at", "before_db_hash", "after_db_hash", "idempotency_key", "resource_lock"].includes(k)
  );

  return (
    <div className="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3">
      <div className="flex items-center justify-between gap-2 mb-2.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="shrink-0">📝</span>
          <h3 className="m-0 text-sm font-bold text-[#182230] dark:text-white truncate">写入审计</h3>
        </div>
        <span className="shrink-0 inline-flex items-center rounded-full text-[10px] font-extrabold leading-none whitespace-nowrap px-1.5 py-1 bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
          ● 关键
        </span>
      </div>

      <div className="grid gap-2">
        <InfoRow label="操作" value={actionName} />
        {status && <InfoRow label="状态" value={<StatusBadge label={statusLabel(status)} tone={statusTone(status)} />} />}

        {changeEntries.length > 0 && (
          <>
            <div className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 mt-1">变更</div>
            <div className="bg-[#f8fafc] dark:bg-slate-700/30 rounded-lg p-2 border border-slate-200 dark:border-slate-700">
              {changeEntries.map(([key, value]) => (
                <div key={key} className="flex gap-2 text-xs py-0.5">
                  <span className="text-slate-500 dark:text-slate-400 shrink-0 font-medium">{key}</span>
                  <span className="text-[#182230] dark:text-white break-all">{formatValue(value)}</span>
                </div>
              ))}
            </div>
          </>
        )}

        {detail.before_db_hash && detail.after_db_hash && detail.before_db_hash !== detail.after_db_hash && (
          <>
            <div className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 mt-1">DB Hash</div>
            <div className="text-xs text-slate-500 dark:text-slate-400 font-mono truncate">
              {(detail.before_db_hash as string).slice(0, 8)} → {(detail.after_db_hash as string).slice(0, 8)}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Import helpers from shared location
function statusLabel(status: string): string {
  const ok = ["ok", "success", "completed", "complete", "passed"];
  if (ok.includes(status)) return "正常";
  if (status === "blocked") return "已阻止";
  if (status === "error" || status === "failed") return "错误";
  return status;
}

function statusTone(status: string): "neutral" | "good" | "warn" | "bad" {
  const s = status.toLowerCase();
  if (["ok", "success", "completed", "complete", "passed"].includes(s)) return "good";
  if (["blocked", "warning", "pending", "skipped"].includes(s)) return "warn";
  if (["error", "failed", "failure"].includes(s)) return "bad";
  return "neutral";
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}
```

- [ ] **Step 5: 创建卡片共享工具文件**

**Files:**
- Create: `workbench/src/components/EventCardHelpers.tsx`

```tsx
import React from "react";

export function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 shrink-0 w-12">{label}</span>
      <div className="text-sm text-[#182230] dark:text-white min-w-0 truncate">{value}</div>
    </div>
  );
}

export function EventWeightBadge({ weight }: { weight: string }) {
  return (
    <span className={
      "shrink-0 inline-flex items-center rounded-full text-[10px] font-extrabold leading-none whitespace-nowrap px-1.5 py-1 " +
      (weight === "primary"
        ? "bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400"
        : "bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400")
    }>
      {weight === "primary" ? "● 关键" : "○ 辅助"}
    </span>
  );
}

export function CardHeader({ icon, title, weight }: { icon: string; title: string; weight: string }) {
  return (
    <div className="flex items-center justify-between gap-2 mb-2.5">
      <div className="flex items-center gap-1.5 min-w-0">
        <span className="shrink-0">{icon}</span>
        <h3 className="m-0 text-sm font-bold text-[#182230] dark:text-white truncate">{title}</h3>
      </div>
      <EventWeightBadge weight={weight} />
    </div>
  );
}

export function statusLabel(status: string): string {
  const ok = ["ok", "success", "completed", "complete", "passed"];
  if (ok.includes(status)) return "正常";
  if (status === "blocked") return "已阻止";
  if (status === "error" || status === "failed") return "错误";
  return status;
}

export function statusTone(status: string): "neutral" | "good" | "warn" | "bad" {
  const s = status.toLowerCase();
  if (["ok", "success", "completed", "complete", "passed"].includes(s)) return "good";
  if (["blocked", "warning", "pending", "skipped"].includes(s)) return "warn";
  if (["error", "failed", "failure"].includes(s)) return "bad";
  return "neutral";
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.join(", ");
  return JSON.stringify(value);
}

export function SectionBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <>
      <div className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 mt-1">{title}</div>
      <div className="bg-[#f8fafc] dark:bg-slate-700/30 rounded-lg p-2 border border-slate-200 dark:border-slate-700">
        {children}
      </div>
    </>
  );
}

export function KeyValueRows({ entries }: { entries: Array<[string, unknown]> }) {
  return (
    <>
      {entries.filter(([_, v]) => v !== null && v !== undefined).map(([key, value]) => (
        <div key={key} className="flex gap-2 text-xs py-0.5">
          <span className="text-slate-500 dark:text-slate-400 shrink-0 font-medium">{key}</span>
          <span className="text-[#182230] dark:text-white break-all">{formatValue(value)}</span>
        </div>
      ))}
    </>
  );
}
```

- [ ] **Step 6: 更新各卡片组件使用共享工具**

修改 `ToolCallCard.tsx`、`StepCard.tsx`、`MessageCard.tsx`、`WriteAuditCard.tsx`，将重复的 `InfoRow`、`statusLabel` 等函数替换为从 `./EventCardHelpers` 导入。

具体修改：
- ToolCallCard：导入 InfoRow、EventWeightBadge、statusLabel、statusTone、formatValue、SectionBlock
- StepCard：导入 InfoRow、CardHeader、statusLabel、statusTone、SectionBlock、KeyValueRows  
- MessageCard：直接使用行内代码（样式简单，无共享依赖）
- WriteAuditCard：导入 InfoRow、statusLabel、statusTone、formatValue、SectionBlock

- [ ] **Step 7: Commit**

```bash
git add workbench/src/components/ToolCallCard.tsx workbench/src/components/StepCard.tsx workbench/src/components/MessageCard.tsx workbench/src/components/WriteAuditCard.tsx workbench/src/components/EventCardHelpers.tsx
git commit -m "feat: add event detail card components (ToolCall, Step, Message, WriteAudit)"
```

---

### Task 5: 创建 EventDetailPanel

**Files:**
- Create: `workbench/src/components/EventDetailPanel.tsx`

- [ ] **Step 1: 实现 EventDetailPanel**

```tsx
import type { TimelineEvent, WorkbenchSnapshot } from "../types";
import { ToolCallCard } from "./ToolCallCard";
import { StepCard } from "./StepCard";
import { MessageCard } from "./MessageCard";
import { WriteAuditCard } from "./WriteAuditCard";

interface EventDetailPanelProps {
  event: TimelineEvent | null;
  snapshot: WorkbenchSnapshot;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export function EventDetailPanel({ event, snapshot, collapsed, onToggleCollapse }: EventDetailPanelProps) {
  return (
    <section
      className={
        "shrink-0 overflow-hidden transition-all duration-200 ease-in-out relative " +
        (collapsed ? "w-0 opacity-0" : "w-80 opacity-100")
      }
      aria-label="事件详情"
    >
      {/* Collapse button on left edge */}
      <button
        aria-label={collapsed ? "展开详情面板" : "收起详情面板"}
        className={
          "absolute top-1/2 -translate-y-1/2 z-10 " +
          (collapsed ? "-right-4" : "left-0 -translate-x-1/2") + " " +
          "inline-flex items-center justify-center w-5 h-10 border border-slate-300 dark:border-slate-600 " +
          "rounded-full bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 " +
          "hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-700 dark:hover:text-slate-200 " +
          "cursor-pointer transition-colors duration-150 shadow-sm"
        }
        onClick={onToggleCollapse}
        type="button"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          {collapsed ? (
            <polyline points="5,3 9,7 5,11" />
          ) : (
            <polyline points="7,3 3,7 7,11" />
          )}
        </svg>
      </button>

      <div className="w-80 h-full overflow-y-auto p-3 pl-5">
        {snapshot.last_error ? (
          <div className="mb-3 border border-red-200 dark:border-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-900 dark:text-red-300 p-2.5 text-sm" role="alert">
            <strong>{errorLabel(snapshot.last_error.code)}</strong>
            <p className="mt-1 m-0 text-xs">{snapshot.last_error.message}</p>
          </div>
        ) : null}

        {event ? (
          <EventCard event={event} />
        ) : (
          <div className="border border-dashed border-slate-300 dark:border-slate-600 rounded-lg text-slate-500 dark:text-slate-400 p-3.5 text-sm">
            {snapshot.timeline.length > 0
              ? "请选择时间线上的事件查看详情"
              : "暂无时间线事件"}
          </div>
        )}

        {/* Trace & Session info */}
        <div className="mt-3 p-2 border border-slate-200 dark:border-slate-700 rounded-lg bg-[#f8fafc] dark:bg-slate-700/30">
          <div className="text-[10px] font-extrabold tracking-normal text-slate-500 dark:text-slate-400 mb-1">Trace</div>
          <div className="text-xs text-slate-600 dark:text-slate-400 font-mono truncate">{snapshot.trace_artifact_path || "尚未写入"}</div>
          <div className="text-[10px] font-extrabold tracking-normal text-slate-500 dark:text-slate-400 mt-1.5 mb-0.5">Session</div>
          <div className="text-xs text-slate-600 dark:text-slate-400 font-mono truncate">{snapshot.session_id}</div>
        </div>
      </div>
    </section>
  );
}

function EventCard({ event }: { event: TimelineEvent }) {
  switch (event.kind) {
    case "tool_call":
      return <ToolCallCard event={event} />;
    case "step":
      return <StepCard event={event} />;
    case "message":
      return <MessageCard event={event} />;
    case "write_audit":
      return <WriteAuditCard event={event} />;
    default:
      return (
        <div className="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3">
          <p className="text-slate-500 dark:text-slate-400 text-sm m-0">未知事件类型: {event.kind}</p>
        </div>
      );
  }
}

function errorLabel(code: string): string {
  const map: Record<string, string> = {
    runtime_error: "运行出错",
    session_not_found: "会话不存在",
    case_not_found: "案例不存在",
    script_complete: "脚本已完成",
  };
  return map[code] || code;
}
```

- [ ] **Step 2: Commit**

```bash
git add workbench/src/components/EventDetailPanel.tsx
git commit -m "feat: add EventDetailPanel with routing to event cards"
```

---

### Task 6: 改造 App.tsx 布局

**Files:**
- Modify: `workbench/src/App.tsx`

- [ ] **Step 1: 重构 App.tsx**

主要变更：
1. 引入 `CaseTree`、`EventDetailPanel`、`CollapseButton`
2. 替换左侧 RunControl aside 为 CaseTree aside
3. 替换右侧 Inspector aside 为 EventDetailPanel
4. Step/Run/Reset 按钮移到 BusinessState 上方
5. 手动消息输入移到 Conversation 下方
6. 添加左右面板收缩状态管理
7. 去掉 mode selector 和 demo/all toggle（仅 LLM 模式）

```tsx
// 文件顶部导入变更
import { CaseTree } from "./components/CaseTree";
import { EventDetailPanel } from "./components/EventDetailPanel";
import { CollapseButton } from "./components/CollapseButton";
// 原有的 RunControl 导入可保留用于手动消息区域

// App 组件新增状态
const [leftCollapsed, setLeftCollapsed] = useState(false);
const [rightCollapsed, setRightCollapsed] = useState(false);

// demo-layout 区域改造:
{
  config && snapshot ? (
    <div className="demo-layout flex flex-1 overflow-hidden p-3 pt-3 gap-0 relative">
      {/* Left panel */}
      <aside
        className={
          "shrink-0 overflow-hidden transition-all duration-200 ease-in-out relative " +
          (leftCollapsed ? "w-0" : "w-[272px]")
        }
      >
        <div className="w-[272px] h-full overflow-hidden p-0">
          <CaseTree
            catalog={config.case_catalog}
            selectedCaseId={snapshot.selected_case_id}
            onSelectCase={handleSelectCase}
          />
        </div>
      </aside>
      <CollapseButton
        collapsed={leftCollapsed}
        side="left"
        onToggle={() => setLeftCollapsed(!leftCollapsed)}
        ariaLabel={leftCollapsed ? "展开案例列表" : "收起案例列表"}
      />

      {/* Middle */}
      <main className="flex-1 flex flex-col overflow-hidden gap-3 min-w-0 mx-3">
        {/* Step/Run/Reset buttons */}
        <div className="flex flex-wrap gap-2 shrink-0">
          <button
            className="inline-flex items-center justify-center gap-1.5 min-h-9 border border-slate-800 dark:border-slate-200 rounded-lg bg-slate-800 dark:bg-white text-white dark:text-slate-900 px-2.5 py-2 text-sm font-bold leading-none whitespace-nowrap cursor-pointer transition-colors duration-150 active:translate-y-px disabled:opacity-62 disabled:cursor-not-allowed"
            disabled={busy || !snapshot.run_controls.can_step}
            onClick={handleStep}
            type="button"
          >
            {busy ? (
              <SpinnerGap aria-hidden="true" size={16} weight="bold" className="animate-spin" />
            ) : (
              <SkipForward aria-hidden="true" size={16} weight="bold" />
            )}
            <span>
              {busy ? "执行中…" : snapshot.run_controls.can_step
                ? `单步执行 ${snapshot.script_cursor + 1}/${snapshot.script_message_count}`
                : "脚本已结束"}
            </span>
          </button>
          <button
            className="inline-flex items-center justify-center gap-1.5 min-h-9 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2.5 py-2 text-sm font-bold leading-none whitespace-nowrap cursor-pointer transition-colors duration-150 active:translate-y-px disabled:opacity-62 disabled:cursor-not-allowed"
            disabled={busy || !snapshot.run_controls.can_run_all}
            onClick={handleRunAll}
            type="button"
          >
            {busy ? (
              <SpinnerGap aria-hidden="true" size={16} weight="bold" className="animate-spin" />
            ) : (
              <Play aria-hidden="true" size={16} weight="bold" />
            )}
            <span>{busy ? "运行中…" : "运行全部"}</span>
          </button>
          <button
            className="inline-flex items-center justify-center gap-1.5 min-h-9 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2.5 py-2 text-sm font-bold leading-none whitespace-nowrap cursor-pointer transition-colors duration-150 active:translate-y-px disabled:opacity-62 disabled:cursor-not-allowed"
            disabled={busy || !snapshot.run_controls.can_reset}
            onClick={handleReset}
            type="button"
          >
            <ArrowCounterClockwise aria-hidden="true" size={16} weight="bold" />
            <span>重置</span>
          </button>
        </div>

        <BusinessState ... />
        
        <div className="flex-1 flex flex-col overflow-hidden min-h-0">
          <Conversation ... />
        </div>

        {/* Manual message input - moved from left panel */}
        <ManualMessageInput onSend={handleSendMessage} busy={busy} />

        <Timeline ... />
      </main>

      {/* Right panel */}
      <EventDetailPanel
        event={activeEvent}
        snapshot={snapshot}
        collapsed={rightCollapsed}
        onToggleCollapse={() => setRightCollapsed(!rightCollapsed)}
      />
    </div>
  ) : (
    // loading state
  )
}
```

需要新建一个 `ManualMessageInput` 行内组件或复用 RunControl 的手动消息部分。

```tsx
// 在 App.tsx 底部或独立为组件
function ManualMessageInput({ onSend, busy }: { onSend: (msg: string) => void | Promise<boolean | void>; busy: boolean }) {
  const [message, setMessage] = useState("");
  const canSend = message.trim().length > 0 && !busy;

  async function handleSend() {
    const next = message.trim();
    if (!next) return;
    const sent = await onSend(next);
    if (sent !== false) setMessage("");
  }

  return (
    <div className="shrink-0 flex gap-2 items-end">
      <textarea
        className="flex-1 min-w-0 min-h-[44px] max-h-24 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-[#182230] dark:text-white px-2.5 py-2 text-sm resize-y focus:outline-2 focus:outline-blue-500 focus:outline-offset-2 disabled:opacity-62 disabled:cursor-not-allowed"
        disabled={busy}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="输入客户回复..."
        rows={1}
        value={message}
      />
      <button
        className="shrink-0 inline-flex items-center justify-center gap-1.5 min-h-9 border border-slate-800 dark:border-slate-200 rounded-lg bg-slate-800 dark:bg-white text-white dark:text-slate-900 px-3 py-2 text-sm font-bold leading-none cursor-pointer transition-colors duration-150 active:translate-y-px disabled:opacity-62 disabled:cursor-not-allowed"
        disabled={!canSend}
        onClick={handleSend}
        type="button"
      >
        <PaperPlaneTilt size={16} weight="bold" />
        <span>发送</span>
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add workbench/src/App.tsx
git commit -m "refactor: restructure App layout - CaseTree left, EventDetailPanel right, controls in middle"
```

---

### Task 7: 清理旧代码

**Files:**
- Modify: `workbench/src/components/RunControl.tsx`
- Delete: `workbench/src/components/Inspector.tsx`

- [ ] **Step 1: 简化 RunControl**

RunControl 已不再需要渲染 case 列表、模式选择、演示切换。仅保留手动消息输入（但该功能已迁移到 App.tsx 的 ManualMessageInput）。RunControl 可以被完全删除，如果不需要保留任何逻辑。

```tsx
// RunControl.tsx — 整个文件可以移除（不再被 App.tsx 引用）
// 如果 App.tsx 已不再 import RunControl，删除此文件即可。
```

- [ ] **Step 2: 删除 Inspector.tsx**

```bash
rm workbench/src/components/Inspector.tsx
```

- [ ] **Step 3: 删除 RunControl.tsx**（确认 App.tsx 不再引用后）

```bash
rm workbench/src/components/RunControl.tsx
```

如果 App.tsx 或其他地方仍有引用，先移除 import 和引用。

- [ ] **Step 4: Commit**

```bash
git rm workbench/src/components/Inspector.tsx workbench/src/components/RunControl.tsx
git commit -m "refactor: remove Inspector and RunControl replaced by new components"
```

---

### Task 8: 验证构建

- [ ] **Step 1: TypeScript 编译检查**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent/workbench
npx tsc --noEmit
```

Expected: 无编译错误

- [ ] **Step 2: 本地运行确认**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent/workbench
npm run dev
```

访问 `http://localhost:5173`，确认：
1. 左侧展示全量 case 分组折叠树，点击可切换
2. 右侧点击 timeline 事件展示结构化卡片（无 JSON）
3. 左右面板收起/展开正常
4. Step/Run/Reset 按钮在中间区域顶部
5. 手动消息输入在 Conversation 下方
6. 暗色模式正常

- [ ] **Step 3: Commit 最终版本**

```bash
git add -A
git commit -m "feat: complete workbench UI optimization - case tree, event cards, collapsible panels"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: 每个 spec section 对应一个或多个 task
  - 左侧分组树: Task 1 + 2
  - 右侧事件卡片: Task 4 + 5
  - 面板收起: Task 3 + 6
  - 控制迁移: Task 6
  - Zero JSON: Task 4 各卡片无 `<pre>` 标签
- [x] **Placeholder scan**: 无 TBD/TODO/incomplete
- [x] **Type consistency**: `CaseTreeCategory`, `CaseTreeNode`, `TimelineEvent` 等类型名与 spec/types.ts 一致
- [x] **No hidden circular deps**: 组件依赖方向单一：EventDetailPanel → 卡片 → helpers

---

## 执行选择

Plan complete. 请选择执行方式：

1. **Subagent-Driven (推荐)** — 每个 Task 分配一个独立 subagent，review 后推进
2. **Inline Execution** — 在当前会话中逐个执行 task
