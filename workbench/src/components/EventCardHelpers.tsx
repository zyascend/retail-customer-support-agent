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