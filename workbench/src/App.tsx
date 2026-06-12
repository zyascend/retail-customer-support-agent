import { useEffect, useState } from "react";
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
  TimelineEvent,
  WorkbenchConfig,
  WorkbenchMode,
  WorkbenchSnapshot,
} from "./types";

export function App() {
  const [config, setConfig] = useState<WorkbenchConfig | null>(null);
  const [snapshot, setSnapshot] = useState<WorkbenchSnapshot | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<TimelineEvent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        setSelectedEvent(nextSnapshot.timeline.at(-1) || null);
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

  async function mutate(action: () => Promise<WorkbenchSnapshot>) {
    setBusy(true);
    setError(null);

    try {
      const nextSnapshot = await action();
      setSnapshot(nextSnapshot);
      setSelectedEvent((currentEvent) => {
        if (
          currentEvent &&
          nextSnapshot.timeline.some((event) => event.id === currentEvent.id)
        ) {
          return currentEvent;
        }

        return nextSnapshot.timeline.at(-1) || null;
      });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Workbench request failed");
    } finally {
      setBusy(false);
    }
  }

  const selectedCase = config?.case_catalog.all_cases.find(
    (workbenchCase) => workbenchCase.case_id === snapshot?.selected_case_id,
  );
  const activeEvent =
    selectedEvent ||
    (snapshot?.timeline.length ? snapshot.timeline[snapshot.timeline.length - 1] : null);

  function handleSelectCase(caseId: string) {
    if (!snapshot || caseId === snapshot.selected_case_id) {
      return;
    }

    mutate(() => selectCase(snapshot.session_id, caseId));
  }

  function handleStep() {
    if (!snapshot) {
      return;
    }

    mutate(() => stepSession(snapshot.session_id));
  }

  function handleRunAll() {
    if (!snapshot) {
      return;
    }

    mutate(() => runAll(snapshot.session_id));
  }

  function handleReset() {
    if (!snapshot) {
      return;
    }

    mutate(() =>
      resetSession(snapshot.session_id, snapshot.selected_case_id || undefined, snapshot.mode),
    );
  }

  function handleSendMessage(message: string) {
    if (!snapshot) {
      return;
    }

    mutate(() => sendMessage(snapshot.session_id, message));
  }

  function handleModeChange(mode: WorkbenchMode) {
    if (!snapshot || mode === snapshot.mode) {
      return;
    }

    mutate(() =>
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
            onChange={() => handleSendMessage("change")}
            onConfirm={() => handleSendMessage("yes")}
            onDeny={() => handleSendMessage("no")}
            snapshot={snapshot}
          />
          <Conversation snapshot={snapshot} />
          <Timeline
            events={snapshot.timeline}
            onSelectEvent={setSelectedEvent}
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
