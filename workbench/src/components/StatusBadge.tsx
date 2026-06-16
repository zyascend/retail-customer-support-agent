import { statusLabel } from "../labels";

export function StatusBadge({
  label,
  tone = "neutral",
}: {
  label: string | null | undefined;
  tone?: "neutral" | "good" | "warn" | "bad";
}) {
  const colorClass = {
    neutral: "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400",
    good: "bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300",
    warn: "bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300",
    bad: "bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300",
  }[tone];

  return (
    <span className={"inline-flex items-center rounded-full text-xs font-extrabold leading-none whitespace-nowrap px-1.5 py-1 " + colorClass}>
      {statusLabel(label)}
    </span>
  );
}
