import { statusLabel } from "../labels";

export function StatusBadge({
  label,
  tone = "neutral",
}: {
  label: string | null | undefined;
  tone?: "neutral" | "good" | "warn" | "bad";
}) {
  return (
    <span className={`status-badge status-${tone}`}>{statusLabel(label)}</span>
  );
}
