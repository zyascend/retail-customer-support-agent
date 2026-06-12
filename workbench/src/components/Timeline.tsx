import { StatusBadge } from "./StatusBadge";
import { eventLabel, timelineKindLabel } from "../labels";
import type { TimelineEvent } from "../types";

interface TimelineProps {
  events: TimelineEvent[];
  selectedEventId: string | null;
  onSelectEvent: (eventId: string) => void;
}

export function Timeline({
  events,
  selectedEventId,
  onSelectEvent,
}: TimelineProps) {
  return (
    <section className="panel timeline-panel" aria-label="时间线">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">时间线</div>
          <h2>事件</h2>
        </div>
        <span className="count-label">{events.length}</span>
      </div>

      {events.length ? (
        <ol className="timeline-list">
          {events.map((event) => {
            const isSelected = event.id === selectedEventId;
            return (
              <li key={event.id}>
                <button
                  aria-current={isSelected ? "true" : undefined}
                  className={isSelected ? "timeline-row selected" : "timeline-row"}
                  onClick={() => onSelectEvent(event.id)}
                  type="button"
                >
                  <span className="timeline-main">
                    <span className="timeline-title">
                      {eventLabel(event.label || event.kind)}
                    </span>
                    <span className="timeline-summary">
                      {event.summary || "暂无摘要"}
                    </span>
                  </span>
                  <span className="timeline-meta">
                    <StatusBadge label={event.status} tone={toneForStatus(event.status)} />
                    <span>{timelineKindLabel(event.kind)}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="empty-state">暂无时间线事件。</div>
      )}
    </section>
  );
}

function toneForStatus(status: string | null): "neutral" | "good" | "warn" | "bad" {
  const normalized = status?.toLowerCase() || "";
  if (["ok", "success", "complete", "completed", "passed"].includes(normalized)) {
    return "good";
  }
  if (["blocked", "warning", "pending", "skipped"].includes(normalized)) {
    return "warn";
  }
  if (["error", "failed", "failure"].includes(normalized)) {
    return "bad";
  }
  return "neutral";
}
