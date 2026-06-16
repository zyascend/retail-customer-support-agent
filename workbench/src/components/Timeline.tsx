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
      <section className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3 max-h-[260px] flex flex-col overflow-hidden" aria-label="时间线">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <div className="mb-0.5 text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">时间线</div>
            <h2 className="m-0 text-base leading-tight text-[#182230] dark:text-white">管道执行</h2>
          </div>
        </div>
        <div className="border border-dashed border-slate-300 dark:border-slate-600 rounded-lg text-slate-500 dark:text-slate-400 p-3.5 text-sm">暂无时间线事件。</div>
      </section>
    );
  }

  const selectedEvent = events.find((e) => e.id === selectedEventId);

  return (
    <section className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3 max-h-[260px] flex flex-col overflow-hidden" aria-label="时间线">
      <div className="flex items-start justify-between gap-3 mb-3 shrink-0">
        <div>
          <div className="mb-0.5 text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">时间线</div>
          <h2 className="m-0 text-base leading-tight text-[#182230] dark:text-white">管道执行</h2>
        </div>
        <span className="inline-flex items-center rounded-full bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 text-xs font-extrabold leading-none whitespace-nowrap px-2 py-1.5">
          {events.length}
        </span>
      </div>

      <div className="overflow-x-auto overflow-y-hidden pb-1.5 pt-2.5 shrink-0" ref={scrollRef}>
        <div className="flex items-center gap-0 min-w-max h-14 px-4">
          {events.map((event, i) => {
            const isSelected = event.id === selectedEventId;
            const tone = dotStatus(event.status);
            const shape = kindShape(event.kind);
            const colorClass = markerColor(tone);
            const shapeClass = markerShape(shape);
            return (
              <button
                key={event.id}
                className={
                  "flex items-center gap-0 shrink-0 relative bg-none border-0 p-0 cursor-pointer transition-shadow duration-200 " +
                  (isSelected ? "z-[2]" : "") +
                  (event.weight === "secondary" ? " opacity-40" : "")
                }
                title={eventLabel(event.label) + (event.summary ? " — " + event.summary : "")}
                onClick={() => onSelectEvent(event.id)}
                type="button"
              >
                {i > 0 && <span className="w-9 h-[2px] shrink-0 bg-slate-200 dark:bg-slate-600 rounded-full" />}
                <span
                  className={
                    "shrink-0 relative " + shapeClass + " " + colorClass +
                    (isSelected ? " ring-[3px] ring-blue-500 ring-offset-[3px] ring-offset-white dark:ring-offset-slate-800" : "")
                  }
                />
                <span className={"absolute top-full left-1/2 -translate-x-1/2 mt-1 text-[10px] font-semibold whitespace-nowrap pointer-events-none " + labelColor(shape)}>
                  {abbreviate(eventLabel(event.label))}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {selectedEvent && (
        <div className="flex items-center gap-2 mt-5 pt-2.5 border-t border-slate-200 dark:border-slate-700 shrink-0">
          <StatusBadge label={selectedEvent.status} tone={statusTone(selectedEvent.status)} />
          <span className="text-[#182230] dark:text-white text-sm font-bold">
            {eventLabel(selectedEvent.label || selectedEvent.kind)}
          </span>
          <span className="text-slate-500 dark:text-slate-400 text-xs ml-auto overflow-hidden text-ellipsis whitespace-nowrap">
            {selectedEvent.summary || ""}
          </span>
        </div>
      )}

      {/* Legend */}
      <div className="flex gap-4.5 mt-3 pt-2 border-t border-slate-200 dark:border-slate-700 shrink-0">
        <span className="flex items-center gap-1.5 text-[11px] font-bold text-blue-500">
          <span className="inline-block w-3 h-3 rounded-full shrink-0 bg-blue-500" />
          管道节点
        </span>
        <span className="flex items-center gap-1.5 text-[11px] font-bold text-purple-500">
          <span className="inline-block w-[10px] h-[10px] shrink-0 rotate-45 rounded-[3px] bg-purple-500" />
          工具调用
        </span>
        <span className="flex items-center gap-1.5 text-[11px] font-bold text-slate-500">
          <span className="inline-block w-3 h-3 shrink-0 rounded-[3px] bg-slate-500" />
          消息
        </span>
        <span className="flex items-center gap-1.5 text-[11px] font-bold text-amber-500">
          <span className="inline-block w-3 h-3 shrink-0 rounded-[3px_8px_3px_8px] bg-amber-500" />
          写入审计
        </span>
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

function markerColor(tone: string): string {
  switch (tone) {
    case "good": return "bg-green-600";
    case "warn": return "bg-amber-500";
    case "bad": return "bg-red-500";
    default: return "bg-slate-400 dark:bg-slate-500";
  }
}

function markerShape(shape: string): string {
  switch (shape) {
    case "step": return "w-4 h-4 rounded-full";
    case "tool": return "w-[13px] h-[13px] rotate-45 rounded-[3px]";
    case "msg": return "w-4 h-4 rounded-[3px]";
    case "audit": return "w-4 h-4 rounded-[3px_10px_3px_10px]";
    default: return "w-4 h-4 rounded-full";
  }
}

function labelColor(shape: string): string {
  switch (shape) {
    case "step": return "text-blue-500";
    case "tool": return "text-purple-500";
    case "msg": return "text-slate-500";
    case "audit": return "text-amber-500";
    default: return "text-slate-500";
  }
}

const ABBREV: Record<string, string> = {
  receive_message: "接收",
  preflight_identity: "身份",
  provider_unavailable: "转人工",
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
