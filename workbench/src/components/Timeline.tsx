import { useRef, useEffect } from "react";
import { StatusBadge } from "./StatusBadge";
import { eventLabel } from "../labels";
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
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to latest
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollLeft = scrollRef.current.scrollWidth;
    }
  }, [events.length]);

  if (events.length === 0) {
    return (
      <section className="panel timeline-panel" aria-label="时间线">
        <div className="panel-header">
          <div>
            <div className="panel-kicker">时间线</div>
            <h2>管道执行</h2>
          </div>
        </div>
        <div className="empty-state">暂无时间线事件。</div>
      </section>
    );
  }

  const selectedEvent = events.find((e) => e.id === selectedEventId);

  return (
    <section className="panel timeline-panel" aria-label="时间线">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">时间线</div>
          <h2>管道执行</h2>
        </div>
        <span className="count-label">{events.length}</span>
      </div>

      <div className="timeline-strip" ref={scrollRef}>
        <div className="timeline-line">
          {events.map((event, i) => {
            const isSelected = event.id === selectedEventId;
            const dotTone = dotStatus(event.status);
            return (
              <button
                key={event.id}
                className={
                  "timeline-dot-wrap" +
                  (isSelected ? " selected" : "") +
                  (event.weight === "secondary" ? " secondary" : "")
                }
                title={eventLabel(event.label) + (event.summary ? " — " + event.summary : "")}
                onClick={() => onSelectEvent(event.id)}
                type="button"
              >
                {/* Connector to previous */}
                {i > 0 && <span className="timeline-segment" />}
                <span className={"timeline-dot dot-" + dotTone} />
                <span className="timeline-dot-label">
                  {abbreviate(eventLabel(event.label))}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {selectedEvent && (
        <div className="timeline-footer">
          <StatusBadge label={selectedEvent.status} tone={statusTone(selectedEvent.status)} />
          <span className="timeline-footer-label">
            {eventLabel(selectedEvent.label || selectedEvent.kind)}
          </span>
          <span className="timeline-footer-summary">
            {selectedEvent.summary || ""}
          </span>
        </div>
      )}
    </section>
  );
}

function dotStatus(status: string | null): string {
  const s = (status || "").toLowerCase();
  if (["ok", "success", "complete", "completed", "passed"].includes(s)) return "good";
  if (["blocked", "warning", "pending", "skipped"].includes(s)) return "warn";
  if (["error", "failed", "failure"].includes(s)) return "bad";
  return "neutral";
}

function statusTone(status: string | null): "neutral" | "good" | "warn" | "bad" {
  return dotStatus(status) as "neutral" | "good" | "warn" | "bad";
}

const ABBREV: Record<string, string> = {
  receive_message: "接收",
  conversation_gate: "会话确认",
  identity_resolver: "身份识别",
  intent_and_slot_extractor: "意图提取",
  context_loader: "上下文加载",
  policy_reasoner: "策略判断",
  action_planner: "动作规划",
  write_action_guard: "写入保护",
  tool_executor: "工具执行",
  observation_reducer: "结果归纳",
  response_generator: "回复生成",
  run_logger: "运行记录",
};

function abbreviate(label: string): string {
  return ABBREV[label] || label.slice(0, 6);
}
