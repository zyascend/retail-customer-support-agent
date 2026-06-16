import { eventLabel } from "../labels";
import type { AgentOpsCaseDetail, AgentOpsTraceDetail } from "../agentopsTypes";
import type { TimelineEvent } from "../types";

interface AgentOpsInspectorProps {
  caseLoading: boolean;
  event: TimelineEvent | null;
  selectedCase: AgentOpsCaseDetail | null;
  trace: AgentOpsTraceDetail | null;
  traceLoading: boolean;
}

export function AgentOpsInspector({
  caseLoading,
  event,
  selectedCase,
  trace,
  traceLoading,
}: AgentOpsInspectorProps) {
  const activeToolCall =
    event?.kind === "tool_call" && typeof event.source_index === "number"
      ? trace?.tool_calls[event.source_index] || null
      : null;
  const activeLlmResponse = selectLlmResponse(event, trace);

  return (
    <section className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3 max-h-[calc(100dvh-98px)] overflow-auto" aria-label="AgentOps 检查器">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="mb-0.5 text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">检查器</div>
          <h2 className="m-0 text-base leading-tight text-[#182230] dark:text-white">{event ? eventLabel(event.label) : "调试详情"}</h2>
        </div>
        <span className="inline-flex items-center rounded-full bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 text-xs font-extrabold leading-none whitespace-nowrap px-2 py-1.5">
          {caseLoading || traceLoading ? "加载中" : trace ? "已载入" : "空"}
        </span>
      </div>

      <dl className="grid gap-2 m-0 mb-3">
        <div className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-[#f8fafc] dark:bg-slate-700/30 p-2">
          <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">案例</dt>
          <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{selectedCase?.case_id || "未绑定案例"}</dd>
        </div>
        <div className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-[#f8fafc] dark:bg-slate-700/30 p-2">
          <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">Trace</dt>
          <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{trace?.trace_id || "未打开"}</dd>
        </div>
        <div className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-[#f8fafc] dark:bg-slate-700/30 p-2">
          <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">当前事件</dt>
          <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{event?.id || "未选择"}</dd>
        </div>
      </dl>

      <InspectorSection
        emptyText={
          trace
            ? "当前 Trace 没有关联可展示的 LLM 响应。"
            : "打开 Trace 后显示 LLM 响应。"
        }
        label="LLM Response"
        value={activeLlmResponse}
      />
      <InspectorSection
        emptyText={
          trace
            ? "选择工具调用事件后显示工具观测。"
            : "打开 Trace 后选择工具调用事件。"
        }
        label="Tool Observation"
        value={activeToolCall}
      />
      <InspectorSection
        emptyText={
          selectedCase
            ? "该案例没有记录 Guard Context。"
            : "选择报告案例后显示 Guard Context；直接打开 Trace 时不会伪造案例上下文。"
        }
        label="Guard Context"
        value={selectedCase?.guard_context}
      />
      <InspectorSection
        emptyText={
          selectedCase
            ? "该案例没有记录 DB Diff。"
            : "选择报告案例后显示 DB Diff；直接打开 Trace 时不会伪造断言差异。"
        }
        label="DB Diff"
        value={selectedCase?.db_assertion_diff}
      />
      <InspectorSection
        emptyText="打开 Trace 后显示路径、哈希和元数据。"
        label="Trace Metadata"
        value={trace ? traceMetadata(trace, event) : null}
      />
    </section>
  );
}

function InspectorSection({
  emptyText,
  label,
  value,
}: {
  emptyText: string;
  label: string;
  value: unknown;
}) {
  return (
    <div className="grid gap-1.5 mt-3">
      <div className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">{label}</div>
      {hasValue(value) ? (
        <pre className="max-h-60 m-0 overflow-auto border border-slate-200 dark:border-slate-700 rounded-lg bg-[#0f172a] dark:bg-[#020617] text-[#dbeafe] dark:text-[#e2e8f0] p-2.5 font-mono text-xs leading-relaxed">{formatJson(value)}</pre>
      ) : (
        <div className="bg-[#fbfcfe] dark:bg-slate-800/50 p-2.5 border border-dashed border-slate-300 dark:border-slate-600 rounded-lg text-slate-500 dark:text-slate-400 text-sm">{emptyText}</div>
      )}
    </div>
  );
}

function selectLlmResponse(
  event: TimelineEvent | null,
  trace: AgentOpsTraceDetail | null,
): unknown {
  if (!trace || trace.llm_responses.length === 0) {
    return null;
  }

  if (event?.label === "response_generator") {
    return trace.llm_responses.at(-1) || null;
  }

  if (trace.llm_responses.length === 1) {
    return trace.llm_responses[0];
  }

  return trace.llm_responses;
}

function traceMetadata(trace: AgentOpsTraceDetail, event: TimelineEvent | null) {
  return {
    trace_id: trace.trace_id,
    trace_artifact_path: trace.trace_artifact_path,
    db_hashes: trace.db_hashes,
    final_state: trace.final_state,
    metadata: trace.metadata,
    selected_event: event
      ? {
          id: event.id,
          kind: event.kind,
          label: event.label,
          status: event.status,
          summary: event.summary,
          detail: event.detail,
        }
      : null,
  };
}

function hasValue(value: unknown): boolean {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "string") {
    return value.trim().length > 0;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value).length > 0;
  }
  return true;
}

function formatJson(value: unknown): string {
  return JSON.stringify(value ?? null, null, 2);
}
