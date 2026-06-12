import { Play, RotateCcw, Send, StepForward } from "lucide-react";
import { useMemo, useState } from "react";
import type {
  CaseCatalog,
  WorkbenchMode,
  WorkbenchSnapshot,
} from "../types";

interface RunControlProps {
  catalog: CaseCatalog;
  snapshot: WorkbenchSnapshot;
  llmAvailable: boolean;
  busy: boolean;
  onSelectCase: (caseId: string) => void;
  onStep: () => void;
  onRunAll: () => void;
  onReset: () => void;
  onSendMessage: (message: string) => void;
  onModeChange: (mode: WorkbenchMode) => void;
}

export function RunControl({
  catalog,
  snapshot,
  llmAvailable,
  busy,
  onSelectCase,
  onStep,
  onRunAll,
  onReset,
  onSendMessage,
  onModeChange,
}: RunControlProps) {
  const [showAll, setShowAll] = useState(false);
  const [manualMessage, setManualMessage] = useState("");
  const cases = showAll ? catalog.all_cases : catalog.demo_cases;

  const selectedCaseId = useMemo(() => {
    const fallback = cases[0]?.case_id || "";
    if (!snapshot.selected_case_id) {
      return fallback;
    }

    return cases.some((workbenchCase) => workbenchCase.case_id === snapshot.selected_case_id)
      ? snapshot.selected_case_id
      : fallback;
  }, [cases, snapshot.selected_case_id]);

  const canSend = manualMessage.trim().length > 0 && !busy;

  function handleSend() {
    const nextMessage = manualMessage.trim();
    if (!nextMessage) {
      return;
    }

    onSendMessage(nextMessage);
    setManualMessage("");
  }

  return (
    <section className="panel run-control" aria-label="Run control">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">Run Control</div>
          <h2>Session</h2>
        </div>
        <div className="segmented-control" aria-label="Case list scope">
          <button
            aria-pressed={!showAll}
            className={!showAll ? "active" : ""}
            disabled={busy}
            onClick={() => setShowAll(false)}
            type="button"
          >
            Demo
          </button>
          <button
            aria-pressed={showAll}
            className={showAll ? "active" : ""}
            disabled={busy}
            onClick={() => setShowAll(true)}
            type="button"
          >
            All
          </button>
        </div>
      </div>

      <label className="field">
        <span>Mode</span>
        <select
          disabled={busy}
          onChange={(event) => onModeChange(event.target.value as WorkbenchMode)}
          value={snapshot.mode}
        >
          <option value="deterministic">Deterministic</option>
          <option disabled={!llmAvailable} value="llm">
            LLM{llmAvailable ? "" : " unavailable"}
          </option>
        </select>
      </label>

      <label className="field">
        <span>Case</span>
        <select
          disabled={busy || cases.length === 0}
          onChange={(event) => onSelectCase(event.target.value)}
          value={selectedCaseId}
        >
          {cases.map((workbenchCase) => (
            <option key={workbenchCase.case_id} value={workbenchCase.case_id}>
              {workbenchCase.title}
            </option>
          ))}
        </select>
      </label>

      <div className="control-row">
        <button
          className="button button-primary"
          disabled={busy || !snapshot.run_controls.can_step}
          onClick={onStep}
          type="button"
        >
          <StepForward aria-hidden="true" size={16} />
          <span>Step</span>
        </button>
        <button
          className="button"
          disabled={busy || !snapshot.run_controls.can_run_all}
          onClick={onRunAll}
          type="button"
        >
          <Play aria-hidden="true" size={16} />
          <span>Run all</span>
        </button>
        <button
          className="button"
          disabled={busy || !snapshot.run_controls.can_reset}
          onClick={onReset}
          type="button"
        >
          <RotateCcw aria-hidden="true" size={16} />
          <span>Reset</span>
        </button>
      </div>

      <div className="manual-message">
        <label className="field">
          <span>Manual user message</span>
          <textarea
            disabled={busy}
            onChange={(event) => setManualMessage(event.target.value)}
            placeholder="Type a customer reply..."
            rows={4}
            value={manualMessage}
          />
        </label>
        <button
          className="button button-primary send-button"
          disabled={!canSend}
          onClick={handleSend}
          type="button"
        >
          <Send aria-hidden="true" size={16} />
          <span>Send</span>
        </button>
      </div>
    </section>
  );
}
