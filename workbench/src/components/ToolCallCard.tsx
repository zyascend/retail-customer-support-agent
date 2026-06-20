import React from "react";
import { StatusBadge } from "./StatusBadge";
import { InfoRow, EventWeightBadge, statusLabel, statusTone, formatValue, SectionBlock } from "./EventCardHelpers";
import type { TimelineEvent } from "../types";

interface ToolCallCardProps {
  event: TimelineEvent;
}

export function ToolCallCard({ event }: ToolCallCardProps) {
  const detail = event.detail as Record<string, unknown> | null;
  if (!detail) {
    return (
      <div className="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3">
        <p className="text-slate-500 dark:text-slate-400 text-sm m-0">工具调用无详情数据</p>
      </div>
    );
  }

  const toolName = (detail.tool_name as string) || event.label;
  const status = event.status || (detail.status as string) || "";
  const toolKind = (detail.tool_kind as string) || "";
  const args = detail.arguments as Record<string, unknown> | undefined;
  const observation = detail.observation;
  const errorMsg = detail.error as string | undefined;
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
          <SectionBlock title="参数">
            {Object.entries(args).map(([key, value]) => (
              <div key={key} className="flex gap-2 text-xs py-0.5">
                <span className="text-slate-500 dark:text-slate-400 shrink-0 font-medium">{key}</span>
                <span className="text-[#182230] dark:text-white break-all">{formatValue(value)}</span>
              </div>
            ))}
          </SectionBlock>
        )}

        {status === "blocked" && (
          <>
            <div className="text-xs font-extrabold tracking-normal text-red-500 dark:text-red-400 mt-1">⚠️ 阻止原因</div>
            <div className="border border-red-200 dark:border-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-900 dark:text-red-300 p-2.5 text-xs">
              {errorMsg || "写保护拦截"}
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
            <div className="border border-red-200 dark:border-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-900 dark:text-red-300 p-2.5 text-xs">
              {errorMsg || "执行错误"}
            </div>
          </>
        )}

        {(status === "success" || status === "ok") && !!observation && (
          <SectionBlock title="结果">
            {renderObservation(observation)}
          </SectionBlock>
        )}

        {/* Show observation even for non-standard statuses */}
        {!["blocked", "error"].includes(status) && !["success", "ok"].includes(status) && !!observation && (
          <SectionBlock title="结果">
            {renderObservation(observation)}
          </SectionBlock>
        )}

        {!!detail.before_db_hash && !!detail.after_db_hash && detail.before_db_hash !== detail.after_db_hash && (
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

function renderObservation(obs: unknown): React.ReactNode {
  if (obs === null || obs === undefined) return <span className="text-slate-400 italic">无返回数据</span>;
  if (typeof obs === "string") return <span>{obs}</span>;
  if (typeof obs === "object" && !Array.isArray(obs)) {
    const entries = Object.entries(obs as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-slate-400 italic">空结果</span>;
    return (
      <div className="grid gap-0.5">
        {entries.filter(([_, v]) => v !== null).map(([k, v]) => (
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