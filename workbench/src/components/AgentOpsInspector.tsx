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
    <section className="panel inspector-panel agentops-inspector" aria-label="AgentOps 检查器">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">检查器</div>
          <h2>{event ? eventLabel(event.label) : "调试详情"}</h2>
        </div>
        <span className="count-label">
          {caseLoading || traceLoading ? "加载中" : trace ? "已载入" : "空"}
        </span>
      </div>

      <dl className="inspector-facts">
        <div>
          <dt>案例</dt>
          <dd>{selectedCase?.case_id || "未绑定案例"}</dd>
        </div>
        <div>
          <dt>Trace</dt>
          <dd>{trace?.trace_id || "未打开"}</dd>
        </div>
        <div>
          <dt>当前事件</dt>
          <dd>{event?.id || "未选择"}</dd>
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
    <div className="json-section agentops-inspector-section">
      <div className="section-label">{label}</div>
      {hasValue(value) ? (
        <pre>{formatJson(value)}</pre>
      ) : (
        <div className="empty-state subtle">{emptyText}</div>
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
