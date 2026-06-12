import { errorLabel, eventLabel } from "../labels";
import type { TimelineEvent, WorkbenchSnapshot } from "../types";

interface InspectorProps {
  event: TimelineEvent | null;
  snapshot: WorkbenchSnapshot;
}

export function Inspector({ event, snapshot }: InspectorProps) {
  return (
    <section className="panel inspector-panel" aria-label="检查器">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">检查器</div>
          <h2>{event ? eventLabel(event.label) : "事件详情"}</h2>
        </div>
      </div>

      {snapshot.last_error ? (
        <div className="last-error" role="alert">
          <strong>{errorLabel(snapshot.last_error.code)}</strong>
          <span>{snapshot.last_error.message}</span>
        </div>
      ) : null}

      <dl className="inspector-facts">
        <div>
          <dt>Trace 文件</dt>
          <dd>{snapshot.trace_artifact_path || "尚未写入"}</dd>
        </div>
        <div>
          <dt>当前事件</dt>
          <dd>{event?.id || "无"}</dd>
        </div>
      </dl>

      <div className="json-section">
        <div className="section-label">事件详情</div>
        <pre>{formatJson(event?.detail ?? null)}</pre>
      </div>

      <div className="json-section">
        <div className="section-label">阻止记录</div>
        <pre>{formatJson(snapshot.guard_blocks)}</pre>
      </div>
    </section>
  );
}

function formatJson(value: unknown): string {
  return JSON.stringify(value ?? null, null, 2);
}
