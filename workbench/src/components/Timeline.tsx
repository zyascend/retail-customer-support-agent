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
            const tone = dotStatus(event.status);
            const shape = kindShape(event.kind);
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
                {i > 0 && <span className="timeline-segment" />}
                <span className={"timeline-marker marker-" + shape + " marker-" + tone} />
                <span className={"timeline-dot-label label-" + shape}>
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

      {/* Legend */}
      <div className="timeline-legend">
        <span className="legend-item"><span className="legend-marker marker-step" /> 管道节点</span>
        <span className="legend-item"><span className="legend-marker marker-tool" /> 工具调用</span>
        <span className="legend-item"><span className="legend-marker marker-msg" /> 消息</span>
        <span className="legend-item"><span className="legend-marker marker-audit" /> 写入审计</span>
      </div>
    </section>
  );
}

// ── helpers ──

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

function kindShape(kind: string): string {
  if (kind === "tool_call") return "tool";
  if (kind === "write_audit") return "audit";
  if (kind === "message") return "msg";
  return "step";
}

const ABBREV: Record<string, string> = {
  receive_message: "接收",
  conversation_gate: "会话",
  identity_resolver: "身份",
  intent_and_slot_extractor: "意图",
  context_loader: "上下文",
  policy_reasoner: "策略",
  action_planner: "规划",
  write_action_guard: "护栏",
  tool_executor: "工具",
  observation_reducer: "归纳",
  response_generator: "回复",
  run_logger: "记录",
};

function abbreviate(label: string): string {
  return ABBREV[label] || label.slice(0, 4);
}
