import { actionLabel, intentLabel, statusLabel } from "../labels";
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
    <section className="panel business-state" aria-label="业务状态">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">业务状态</div>
          <h2>上下文</h2>
        </div>
        <span className={business.db_changed ? "change-flag changed" : "change-flag"}>
          数据库{business.db_changed ? "已变更" : "未变更"}
        </span>
      </div>

      <dl className="fact-grid">
        <div>
          <dt>用户</dt>
          <dd>{business.authenticated_user_id || "未认证"}</dd>
        </div>
        <div>
          <dt>订单</dt>
          <dd>{business.active_order_id || "无"}</dd>
        </div>
        <div>
          <dt>意图</dt>
          <dd>{intentLabel(business.current_intent)}</dd>
        </div>
        <div>
          <dt>确认状态</dt>
          <dd>{statusLabel(business.confirmation_status)}</dd>
        </div>
      </dl>

      <div className="json-section">
        <div className="section-label">槽位</div>
        <pre>{formatJson(business.slots)}</pre>
      </div>

      {pendingAction ? (
        <section className="pending-action" aria-label="待确认操作">
          <div className="pending-action-banner">
            <span className="pending-action-icon">⏳</span>
            <span className="pending-action-prompt">需要用户确认才能执行</span>
          </div>
          <div className="section-label">待确认操作</div>
          <h3>{actionLabel(pendingAction.action_name)}</h3>
          <p>{pendingAction.user_facing_summary}</p>
          <pre>{formatJson(pendingAction.arguments)}</pre>
          <div className="control-row compact">
            <button
              className="button button-primary"
              disabled={busy}
              onClick={onConfirm}
              type="button"
            >
              确认
            </button>
            <button className="button" disabled={busy} onClick={onDeny} type="button">
              拒绝
            </button>
            <button className="button" disabled={busy} onClick={onChange} type="button">
              修改
            </button>
          </div>
        </section>
      ) : (
        <div className="empty-state">暂无待确认操作。</div>
      )}
    </section>
  );
}

function formatJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}
