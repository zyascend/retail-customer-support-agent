import { useEffect, useRef, useState } from "react";
import {
  createSession,
  fetchConfig,
  resetSession,
  runAll,
  selectCase,
  sendMessage,
  stepSession,
} from "./api";
import { BusinessState } from "./components/BusinessState";
import { Conversation } from "./components/Conversation";
import { Inspector } from "./components/Inspector";
import { RunControl } from "./components/RunControl";
import { Timeline } from "./components/Timeline";
import type {
  WorkbenchConfig,
  WorkbenchMode,
  WorkbenchSnapshot,
} from "./types";

export function App() {
  const [config, setConfig] = useState<WorkbenchConfig | null>(null);
  const [snapshot, setSnapshot] = useState<WorkbenchSnapshot | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busyRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    fetchConfig()
      .then(async (nextConfig) => {
        if (cancelled) {
          return;
        }

        setConfig(nextConfig);
        const firstCase = nextConfig.case_catalog.demo_cases[0]?.case_id;
        const nextSnapshot = await createSession(
          nextConfig.default_mode,
          firstCase,
        );

        if (cancelled) {
          return;
        }

        setSnapshot(nextSnapshot);
        setSelectedEventId(nextSnapshot.timeline.at(-1)?.id || null);
      })
      .catch((exc: Error) => {
        if (!cancelled) {
          setError(exc.message);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  async function mutate(action: () => Promise<WorkbenchSnapshot>): Promise<boolean> {
    if (busyRef.current) {
      return false;
    }

    busyRef.current = true;
    setBusy(true);
    setError(null);

    try {
      const nextSnapshot = await action();
      setSnapshot(nextSnapshot);
      setSelectedEventId((currentEventId) => {
        if (
          currentEventId &&
          nextSnapshot.timeline.some((event) => event.id === currentEventId)
        ) {
          return currentEventId;
        }

        return nextSnapshot.timeline.at(-1)?.id || null;
      });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Workbench request failed");
      return false;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }

    return true;
  }

  const selectedCase = config?.case_catalog.all_cases.find(
    (workbenchCase) => workbenchCase.case_id === snapshot?.selected_case_id,
  );
  const activeEvent =
    snapshot?.timeline.find((event) => event.id === selectedEventId) ||
    (snapshot?.timeline.length ? snapshot.timeline[snapshot.timeline.length - 1] : null);

  function handleSelectCase(caseId: string) {
    if (!snapshot || caseId === snapshot.selected_case_id) {
      return;
    }

    return mutate(() => selectCase(snapshot.session_id, caseId));
  }

  function handleStep() {
    if (!snapshot) {
      return;
    }

    return mutate(() => stepSession(snapshot.session_id));
  }

  function handleRunAll() {
    if (!snapshot) {
      return;
    }

    return mutate(() => runAll(snapshot.session_id));
  }

  function handleReset() {
    if (!snapshot) {
      return;
    }

    return mutate(() =>
      resetSession(snapshot.session_id, snapshot.selected_case_id || undefined, snapshot.mode),
    );
  }

  function handleSendMessage(message: string) {
    if (!snapshot) {
      return false;
    }

    return mutate(() => sendMessage(snapshot.session_id, message));
  }

  function handleModeChange(mode: WorkbenchMode) {
    if (!snapshot || mode === snapshot.mode) {
      return;
    }

    return mutate(() =>
      resetSession(snapshot.session_id, snapshot.selected_case_id || undefined, mode),
    );
  }

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

      {config && snapshot ? (
        <section className="dashboard-grid" aria-label="Workbench dashboard">
          <RunControl
            busy={busy}
            catalog={config.case_catalog}
            llmAvailable={config.llm_available}
            onModeChange={handleModeChange}
            onReset={handleReset}
            onRunAll={handleRunAll}
            onSelectCase={handleSelectCase}
            onSendMessage={handleSendMessage}
            onStep={handleStep}
            snapshot={snapshot}
          />
          <BusinessState
            busy={busy}
            onChange={() => handleSendMessage("change")}
            onConfirm={() => handleSendMessage("yes")}
            onDeny={() => handleSendMessage("no")}
            snapshot={snapshot}
          />
          <Conversation snapshot={snapshot} />
          <Timeline
            events={snapshot.timeline}
            onSelectEvent={setSelectedEventId}
            selectedEventId={activeEvent?.id || null}
          />
          <Inspector event={activeEvent} snapshot={snapshot} />
        </section>
      ) : (
        <section className="loading-shell" aria-live="polite">
          Loading workbench...
        </section>
      )}
    </main>
  );
}
