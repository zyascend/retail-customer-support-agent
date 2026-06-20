import React from "react";
import { StatusBadge } from "./StatusBadge";
import { CardHeader, EventWeightBadge, InfoRow, statusLabel, statusTone, formatValue, SectionBlock } from "./EventCardHelpers";
import type { TimelineEvent } from "../types";

interface WriteAuditCardProps {
  event: TimelineEvent;
}

export function WriteAuditCard({ event }: WriteAuditCardProps) {
  const detail = event.detail as Record<string, unknown> | null;

  if (!detail) {
    return (
      <div className="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3">
        <CardHeader icon="📝" title="写入审计" weight={event.weight} />
        <p className="text-slate-500 dark:text-slate-400 text-sm m-0">无详情数据</p>
      </div>
    );
  }

  const status = event.status || (detail.status as string) || "";
  const actionName = (detail.action_name as string) || (detail.tool_name as string) || event.label;

  // Extract change-related fields (exclude metadata fields)
  const metadataKeys = ["action_name", "tool_name", "status", "timestamp", "created_at", "before_db_hash", "after_db_hash", "idempotency_key", "resource_lock"];
  const changeEntries = Object.entries(detail).filter(([k]) => !metadataKeys.includes(k));

  return (
    <div className="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3">
      <div className="flex items-center justify-between gap-2 mb-2.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="shrink-0">📝</span>
          <h3 className="m-0 text-sm font-bold text-[#182230] dark:text-white truncate">写入审计</h3>
        </div>
        <EventWeightBadge weight={event.weight} />
      </div>

      <div className="grid gap-2">
        <InfoRow label="操作" value={actionName} />
        {status && <InfoRow label="状态" value={<StatusBadge label={statusLabel(status)} tone={statusTone(status)} />} />}

        {changeEntries.length > 0 && (
          <SectionBlock title="变更">
            {changeEntries.map(([key, value]) => (
              <div key={key} className="flex gap-2 text-xs py-0.5">
                <span className="text-slate-500 dark:text-slate-400 shrink-0 font-medium">{key}</span>
                <span className="text-[#182230] dark:text-white break-all">{formatValue(value)}</span>
              </div>
            ))}
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