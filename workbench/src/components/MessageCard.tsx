import React from "react";
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
        {!!detail?.created_at && (
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-xs font-extrabold tracking-normal text-slate-500 dark:text-slate-400 shrink-0 w-12">时间</span>
            <span className="text-sm text-[#182230] dark:text-white">{detail?.created_at as string}</span>
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
                {detail?.content as string}
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