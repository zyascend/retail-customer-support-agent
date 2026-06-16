import { errorLabel, eventLabel } from "../labels";
import type { TimelineEvent, WorkbenchSnapshot } from "../types";

interface InspectorProps {
  event: TimelineEvent | null;
  snapshot: WorkbenchSnapshot;
}

export function Inspector({ event, snapshot }: InspectorProps) {
  return (
    <section className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3" aria-label="检查器">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="mb-0.5 text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">检查器</div>
          <h2 className="m-0 text-base leading-tight text-[#182230] dark:text-white">{event ? eventLabel(event.label) : "事件详情"}</h2>
        </div>
      </div>

      {snapshot.last_error ? (
        <div className="grid gap-1 mb-3 border border-red-200 dark:border-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-900 dark:text-red-300 p-2.5 text-sm" role="alert">
          <strong>{errorLabel(snapshot.last_error.code)}</strong>
          <span>{snapshot.last_error.message}</span>
        </div>
      ) : null}

      <dl className="grid gap-2 m-0">
        <div className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-[#f8fafc] dark:bg-slate-700/30 p-2">
          <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">Trace 文件</dt>
          <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{snapshot.trace_artifact_path || "尚未写入"}</dd>
        </div>
        <div className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-[#f8fafc] dark:bg-slate-700/30 p-2">
          <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">当前事件</dt>
          <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{event?.id || "无"}</dd>
        </div>
      </dl>

      <div className="grid gap-1.5 mt-3">
        <div className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">事件详情</div>
        <pre className="max-h-60 m-0 overflow-auto border border-slate-200 dark:border-slate-700 rounded-lg bg-[#0f172a] dark:bg-[#020617] text-[#dbeafe] dark:text-[#e2e8f0] p-2.5 font-mono text-xs leading-relaxed">{formatJson(event?.detail ?? null)}</pre>
      </div>

      <div className="grid gap-1.5 mt-3">
        <div className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">阻止记录</div>
        <pre className="max-h-60 m-0 overflow-auto border border-slate-200 dark:border-slate-700 rounded-lg bg-[#0f172a] dark:bg-[#020617] text-[#dbeafe] dark:text-[#e2e8f0] p-2.5 font-mono text-xs leading-relaxed">{formatJson(snapshot.guard_blocks)}</pre>
      </div>
    </section>
  );
}

function formatJson(value: unknown): string {
  return JSON.stringify(value ?? null, null, 2);
}
