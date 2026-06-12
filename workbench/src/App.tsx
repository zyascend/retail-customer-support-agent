import { useEffect, useState } from "react";
import { createSession, fetchConfig } from "./api";
import type { WorkbenchConfig, WorkbenchSnapshot } from "./types";

export function App() {
  const [config, setConfig] = useState<WorkbenchConfig | null>(null);
  const [snapshot, setSnapshot] = useState<WorkbenchSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchConfig()
      .then(async (nextConfig) => {
        setConfig(nextConfig);
        const firstCase = nextConfig.case_catalog.demo_cases[0]?.case_id;
        setSnapshot(await createSession(nextConfig.default_mode, firstCase));
      })
      .catch((exc: Error) => setError(exc.message));
  }, []);

  const selectedCase = config?.case_catalog.all_cases.find(
    (workbenchCase) => workbenchCase.case_id === snapshot?.selected_case_id,
  );

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Retail Agent Workbench</h1>
          <p>Single-session Phase 4 operations dashboard</p>
        </div>
        <div className="topbar-status">
          <span className="case-label">{selectedCase?.title || "Loading case"}</span>
          <span className="mode-pill">
            {snapshot?.mode || config?.default_mode || "loading"}
          </span>
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      <section className="dashboard-grid" aria-label="Workbench dashboard">
        <aside className="panel">
          <div className="panel-kicker">Run Control</div>
          <p>Session controls load in Task 8.</p>
        </aside>
        <section className="panel">
          <div className="panel-kicker">Business State</div>
          <p>Customer, order, intent, and policy state load in Task 8.</p>
        </section>
        <section className="panel">
          <div className="panel-kicker">Conversation / Timeline</div>
          <p>Transcript and event timeline load in Task 8.</p>
        </section>
      </section>
    </main>
  );
}
