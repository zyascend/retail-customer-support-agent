import { useRef, useEffect } from "react";
import { StatusBadge } from "./StatusBadge";
import { eventLabel, timelineKindLabel } from "../labels";
import type { TimelineEvent } from "../types";

interface TimelineProps {
  events: TimelineEvent[];
  selectedEventId: string | null;
  onSelectEvent: (eventId: string) => void;
}

const PIPELINE_NODES = [
  "receive_message",
  "conversation_gate",
  "identity_resolver",
  "intent_and_slot_extractor",
  "context_loader",
  "policy_reasoner",
  "action_planner",
  "write_action_guard",
  "tool_executor",
  "observation_reducer",
  "response_generator",
  "run_logger",
];

function nodeIndex(label: string): number {
  return PIPELINE_NODES.indexOf(label);
}

export function Timeline({
  events,
  selectedEventId,
  onSelectEvent,
}: TimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to latest when events change
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollLeft = scrollRef.current.scrollWidth;
    }
  }, [events.length]);

  // Group events by turn: a turn starts at receive_message or at a user message
  const turns = groupByTurn(events);
  if (turns.length === 0) {
    return (
      <section className="panel timeline-panel" aria-label="时间线">
        <div className="panel-header">
          <div>
            <div className="panel-kicker">时间线</div>
            <h2>管道执行</h2>
          </div>
          <span className="count-label">{events.length}</span>
        </div>
        <div className="empty-state">暂无时间线事件。</div>
      </section>
    );
  }

  return (
    <section className="panel timeline-panel" aria-label="时间线">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">时间线</div>
          <h2>管道执行</h2>
        </div>
        <span className="count-label">{events.length}</span>
      </div>

      <div className="timeline-horizontal" ref={scrollRef}>
        <div className="timeline-track">
          {/* Node header row */}
          <div className="timeline-node-header">
            {PIPELINE_NODES.map((node) => (
              <div key={node} className="timeline-node-label" title={eventLabel(node)}>
                {eventLabel(node)}
              </div>
            ))}
          </div>

          {/* Turn rows */}
          {turns.map((turn, turnIdx) => {
            const turnLabel =
              turn[0]?.kind === "message"
                ? `第 ${turnIdx + 1} 轮`
                : `动作 ${turnIdx + 1}`;
            return (
              <div key={turnIdx} className="timeline-turn">
                <div className="timeline-turn-label">{turnLabel}</div>
                <div className="timeline-turn-track">
                  {PIPELINE_NODES.map((node, ni) => {
                    const step = findStep(turn, node);
                    return (
                      <div
                        key={node}
                        className={
                          "timeline-node-slot" +
                          (step ? " has-event" : "") +
                          (step && step.id === selectedEventId ? " selected" : "")
                        }
                        title={step ? eventLabel(step.label) : ""}
                        onClick={() => step && onSelectEvent(step.id)}
                      >
                        {/* Connector line */}
                        {ni > 0 && (
                          <div
                            className={
                              "timeline-connector" +
                              (hasEventBefore(turn, PIPELINE_NODES, ni)
                                ? " active"
                                : "")
                            }
                          />
                        )}
                        {/* Node dot */}
                        <div
                          className={
                            "timeline-node-dot" +
                            (step
                              ? " status-" + (nodeStatus(step.status) || "neutral")
                              : "")
                          }
                        />
                        {/* Tool calls below */}
                        {step && step.kind === "tool_call" && (
                          <div className="timeline-tool-label">
                            {truncate(step.summary || step.label, 12)}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Selected event summary bar */}
      {selectedEventId && (
        <div className="timeline-footer">
          {(() => {
            const evt = events.find((e) => e.id === selectedEventId);
            if (!evt) return null;
            return (
              <>
                <StatusBadge
                  label={evt.status}
                  tone={statusTone(evt.status)}
                />
                <span className="timeline-footer-label">
                  {eventLabel(evt.label || evt.kind)}
                </span>
                <span className="timeline-footer-summary">
                  {evt.summary || timelineKindLabel(evt.kind)}
                </span>
              </>
            );
          })()}
        </div>
      )}
    </section>
  );
}

// ── helpers ──

function groupByTurn(events: TimelineEvent[]): TimelineEvent[][] {
  const turns: TimelineEvent[][] = [];
  let current: TimelineEvent[] = [];
  for (const event of events) {
    const label = event.label || "";
    if (label === "receive_message" || event.kind === "message") {
      if (current.length > 0) {
        turns.push(current);
      }
      current = [event];
    } else {
      current.push(event);
    }
  }
  if (current.length > 0) turns.push(current);
  return turns;
}

function findStep(
  turn: TimelineEvent[],
  node: string,
): TimelineEvent | undefined {
  // First, exact match
  const exact = turn.find((e) => e.label === node);
  if (exact) return exact;
  // Fallback: tool calls map to tool_executor
  if (node === "tool_executor") {
    const tool = turn.find((e) => e.kind === "tool_call");
    if (tool) return tool;
  }
  // Fallback: message maps to receive_message
  if (node === "receive_message") {
    const msg = turn.find((e) => e.kind === "message");
    if (msg) return msg;
  }
  return undefined;
}

function hasEventBefore(
  turn: TimelineEvent[],
  nodes: string[],
  currentIdx: number,
): boolean {
  for (let i = 0; i < currentIdx; i++) {
    if (findStep(turn, nodes[i])) return true;
  }
  return false;
}

function nodeStatus(status: string | null): string {
  const s = (status || "").toLowerCase();
  if (["ok", "success", "complete", "completed", "passed"].includes(s))
    return "good";
  if (["blocked", "warning", "pending", "skipped"].includes(s)) return "warn";
  if (["error", "failed", "failure"].includes(s)) return "bad";
  return "neutral";
}

function statusTone(
  status: string | null,
): "neutral" | "good" | "warn" | "bad" {
  return nodeStatus(status) as "neutral" | "good" | "warn" | "bad";
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 1) + "…";
}
