import type { TimelineEvent, WorkbenchSnapshot } from "../types";

interface InspectorProps {
  event: TimelineEvent | null;
  snapshot: WorkbenchSnapshot;
}

export function Inspector({ event, snapshot }: InspectorProps) {
  return (
    <section className="panel inspector-panel" aria-label="Inspector">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">Inspector</div>
          <h2>{event?.label || "Event Details"}</h2>
        </div>
      </div>

      {snapshot.last_error ? (
        <div className="last-error" role="alert">
          <strong>{snapshot.last_error.code}</strong>
          <span>{snapshot.last_error.message}</span>
        </div>
      ) : null}

      <dl className="inspector-facts">
        <div>
          <dt>Trace</dt>
          <dd>{snapshot.trace_artifact_path || "Not written"}</dd>
        </div>
        <div>
          <dt>Selected event</dt>
          <dd>{event?.id || "None"}</dd>
        </div>
      </dl>

      <div className="json-section">
        <div className="section-label">Event Detail</div>
        <pre>{formatJson(event?.detail ?? null)}</pre>
      </div>

      <div className="json-section">
        <div className="section-label">Guard Blocks</div>
        <pre>{formatJson(snapshot.guard_blocks)}</pre>
      </div>
    </section>
  );
}

function formatJson(value: unknown): string {
  return JSON.stringify(value ?? null, null, 2);
}
