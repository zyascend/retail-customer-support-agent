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
