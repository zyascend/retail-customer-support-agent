import type { WorkbenchSnapshot } from "../types";

export function Conversation({ snapshot }: { snapshot: WorkbenchSnapshot }) {
  return (
    <section className="panel conversation-panel" aria-label="Conversation">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">Conversation</div>
          <h2>Transcript</h2>
        </div>
        <span className="count-label">{snapshot.messages.length}</span>
      </div>

      {snapshot.messages.length ? (
        <ol className="message-list">
          {snapshot.messages.map((message, index) => (
            <li className={`message-row role-${message.role}`} key={`${index}-${message.role}`}>
              <div className="message-meta">
                <span>{message.role}</span>
                {message.created_at ? <time>{message.created_at}</time> : null}
              </div>
              <p>{message.content}</p>
            </li>
          ))}
        </ol>
      ) : (
        <div className="empty-state">No messages yet.</div>
      )}
    </section>
  );
}
