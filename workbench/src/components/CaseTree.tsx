import { useMemo, useState } from "react";
import { buildCaseTree } from "../caseTreeUtils";
import { intentLabel } from "../labels";
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
        aria-expanded={expanded}
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
        aria-expanded={expanded}
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

function CaseTreeItem({ caseData, isSelected, onSelect }: CaseTreeItemProps) {
  return (
    <button
      className={
        "w-full text-left border-0 bg-transparent px-2 py-1.5 pl-[11px] rounded-md cursor-pointer transition-colors duration-100 " +
        (isSelected
          ? "bg-blue-50 dark:bg-blue-900/20 border-l-[3px] border-l-blue-500"
          : "hover:bg-slate-50 dark:hover:bg-slate-700/20")
      }
      onClick={() => onSelect(caseData.case_id)}
      type="button"
    >
      <div className="text-sm font-semibold text-[#182230] dark:text-white leading-tight truncate">
        {caseData.title}
      </div>
      <div className="text-[11px] text-slate-500 dark:text-slate-400 leading-tight mt-0.5 truncate">
        {intentLabel(caseData.expected_intent)}
        {caseData.expected_tool_names.length > 0 && ` · ${caseData.expected_tool_names[0]}`}
      </div>
      <div className="text-[11px] text-slate-400 dark:text-slate-500 leading-tight mt-px truncate">
        {caseData.message_count}条消息
        {caseData.policy_area && ` · ${policyAreaLabel(caseData.policy_area)}`}
        {caseData.expected_guard_block_reason && ` · 阻止: ${caseData.expected_guard_block_reason}`}
      </div>
      {caseData.subset && caseData.scenario_family && (
        <div className="text-[11px] text-slate-400 dark:text-slate-500 leading-tight mt-px truncate">
          {caseData.subset} · {caseData.scenario_family || caseData.capability || ""}
        </div>
      )}
    </button>
  );
}

// ── Label helpers ──
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
