import { ClockCountdown } from "@phosphor-icons/react";
import { actionLabel, intentLabel, statusLabel } from "../labels";
import type { WorkbenchSnapshot } from "../types";

interface BusinessStateProps {
  snapshot: WorkbenchSnapshot;
  busy: boolean;
  onConfirm: () => void;
  onDeny: () => void;
  onChange: () => void;
}

export function BusinessState({
  snapshot,
  busy,
  onConfirm,
  onDeny,
  onChange,
}: BusinessStateProps) {
  const { business, compat, pending_action: pendingAction } = snapshot;

  return (
    <section className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3" aria-label="业务状态">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="mb-0.5 text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">业务状态</div>
          <h2 className="m-0 text-base leading-tight text-[#182230] dark:text-white">上下文</h2>
        </div>
        <span
          className={
            "inline-flex items-center rounded-full text-xs font-extrabold leading-none whitespace-nowrap px-2 py-1.5 border " +
            (business.db_changed
              ? "border-[#f6c453] bg-[#fff8db] dark:bg-[#2a2416] text-[#7a4b00] dark:text-[#fde68a]"
              : "border-slate-300 dark:border-slate-600 bg-[#f8fafc] dark:bg-slate-800 text-slate-600 dark:text-slate-400")
          }
        >
          数据库{business.db_changed ? "已变更" : "未变更"}
        </span>
      </div>

      <dl className="grid grid-cols-4 border-y border-slate-200 dark:border-slate-700 mb-3">
        <div className="min-w-0 px-2.5 py-2 border-r border-slate-200 dark:border-slate-700 last:border-r-0">
          <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">用户</dt>
          <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{business.authenticated_user_id || "未认证"}</dd>
        </div>
        <div className="min-w-0 px-2.5 py-2 border-r border-slate-200 dark:border-slate-700 last:border-r-0">
          <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">订单</dt>
          <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{business.active_order_id || "无"}</dd>
        </div>
        <div className="min-w-0 px-2.5 py-2 border-r border-slate-200 dark:border-slate-700 last:border-r-0">
          <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">意图</dt>
          <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{intentLabel(compat.current_intent)}</dd>
        </div>
        <div className="min-w-0 px-2.5 py-2">
          <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">确认状态</dt>
          <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{statusLabel(business.confirmation_status)}</dd>
        </div>
      </dl>

      <div className="grid gap-1.5 mt-3">
        <div className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">兼容槽位</div>
        <pre className="max-h-60 m-0 overflow-auto border border-slate-200 dark:border-slate-700 rounded-lg bg-[#0f172a] dark:bg-[#020617] text-[#dbeafe] dark:text-[#e2e8f0] p-2.5 font-mono text-xs leading-relaxed">{formatJson(compat.slots)}</pre>
      </div>

      {pendingAction ? (
        <section className="mt-3 border border-[#f6c453] dark:border-amber-600/50 rounded-lg bg-[#fffdf2] dark:bg-[#2a2416] p-3" aria-label="待确认操作">
          <div className="flex items-center gap-2 -mx-3 -mt-3 mb-2.5 rounded-t-lg bg-amber-500 text-white px-3 py-2 text-sm font-bold">
            <ClockCountdown aria-hidden="true" size={18} weight="bold" className="text-white" />
            <span className="tracking-wide">需要用户确认才能执行</span>
          </div>
          <div className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">待确认操作</div>
          <h3 className="m-0 mt-1 text-sm leading-tight text-[#182230] dark:text-white">{actionLabel(pendingAction.action_name)}</h3>
          <p className="m-0 mt-1.5 text-slate-600 dark:text-slate-400 text-sm leading-relaxed">{pendingAction.user_facing_summary}</p>
          <pre className="max-h-60 m-0 mt-2 overflow-auto border border-slate-200 dark:border-slate-700 rounded-lg bg-[#0f172a] dark:bg-[#020617] text-[#dbeafe] dark:text-[#e2e8f0] p-2.5 font-mono text-xs leading-relaxed">{formatJson(pendingAction.arguments)}</pre>
          <div className="flex flex-wrap gap-2 mt-2.5">
            <button
              className="inline-flex items-center justify-center gap-1.5 min-h-9 border border-slate-800 dark:border-slate-200 rounded-lg bg-slate-800 dark:bg-white text-white dark:text-slate-900 px-2.5 py-2 text-sm font-bold leading-none whitespace-nowrap cursor-pointer transition-colors duration-150 active:translate-y-px disabled:opacity-62 disabled:cursor-not-allowed"
              disabled={busy}
              onClick={onConfirm}
              type="button"
            >
              确认
            </button>
            <button
              className="inline-flex items-center justify-center gap-1.5 min-h-9 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2.5 py-2 text-sm font-bold leading-none whitespace-nowrap cursor-pointer transition-colors duration-150 active:translate-y-px disabled:opacity-62 disabled:cursor-not-allowed"
              disabled={busy}
              onClick={onDeny}
              type="button"
            >
              拒绝
            </button>
            <button
              className="inline-flex items-center justify-center gap-1.5 min-h-9 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2.5 py-2 text-sm font-bold leading-none whitespace-nowrap cursor-pointer transition-colors duration-150 active:translate-y-px disabled:opacity-62 disabled:cursor-not-allowed"
              disabled={busy}
              onClick={onChange}
              type="button"
            >
              修改
            </button>
          </div>
        </section>
      ) : (
        <div className="border border-dashed border-slate-300 dark:border-slate-600 rounded-lg text-slate-500 dark:text-slate-400 p-3.5 text-sm">暂无待确认操作。</div>
      )}
    </section>
  );
}

function formatJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}
