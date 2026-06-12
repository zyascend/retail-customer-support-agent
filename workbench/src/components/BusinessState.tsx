import type { WorkbenchSnapshot } from "../types";

interface BusinessStateProps {
  snapshot: WorkbenchSnapshot;
  busy: boolean;
  onConfirm: () => void;
  onDeny: () => void;
  onChange: () => void;
}

export function BusinessState({
  snapshot,
  busy,
  onConfirm,
  onDeny,
  onChange,
}: BusinessStateProps) {
  const { business, pending_action: pendingAction } = snapshot;

  return (
    <section className="panel business-state" aria-label="Business state">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">Business State</div>
          <h2>Context</h2>
        </div>
        <span className={business.db_changed ? "change-flag changed" : "change-flag"}>
          DB {business.db_changed ? "changed" : "unchanged"}
        </span>
      </div>

      <dl className="fact-grid">
        <div>
          <dt>User</dt>
          <dd>{business.authenticated_user_id || "Unauthenticated"}</dd>
        </div>
        <div>
          <dt>Order</dt>
          <dd>{business.active_order_id || "None"}</dd>
        </div>
        <div>
          <dt>Intent</dt>
          <dd>{business.current_intent || "Unknown"}</dd>
        </div>
        <div>
          <dt>Confirmation</dt>
          <dd>{business.confirmation_status || "Unknown"}</dd>
        </div>
      </dl>

      <div className="json-section">
        <div className="section-label">Slots</div>
        <pre>{formatJson(business.slots)}</pre>
      </div>

      {pendingAction ? (
        <section className="pending-action" aria-label="Pending action">
          <div className="section-label">Pending Action</div>
          <h3>{pendingAction.action_name}</h3>
          <p>{pendingAction.user_facing_summary}</p>
          <pre>{formatJson(pendingAction.arguments)}</pre>
          <div className="control-row compact">
            <button
              className="button button-primary"
              disabled={busy}
              onClick={onConfirm}
              type="button"
            >
              Confirm
            </button>
            <button className="button" disabled={busy} onClick={onDeny} type="button">
              Deny
            </button>
            <button className="button" disabled={busy} onClick={onChange} type="button">
              Change
            </button>
          </div>
        </section>
      ) : (
        <div className="empty-state">No pending action.</div>
      )}
    </section>
  );
}

function formatJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}
