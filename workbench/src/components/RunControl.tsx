import { Play, RotateCcw, Send, StepForward } from "lucide-react";
import { useMemo, useState } from "react";
import { modeLabel } from "../labels";
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
  onSendMessage: (message: string) => void | boolean | Promise<void | boolean>;
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

  const caseOptions = useMemo(() => {
    if (!snapshot.selected_case_id) {
      return cases;
    }

    const hasSelectedCase = cases.some(
      (workbenchCase) => workbenchCase.case_id === snapshot.selected_case_id,
    );
    if (hasSelectedCase) {
      return cases;
    }

    const selectedCase = catalog.all_cases.find(
      (workbenchCase) => workbenchCase.case_id === snapshot.selected_case_id,
    );
    if (!selectedCase) {
      return cases;
    }

    return [selectedCase, ...cases];
  }, [catalog.all_cases, cases, snapshot.selected_case_id]);

  const selectedCaseId = snapshot.selected_case_id || caseOptions[0]?.case_id || "";
  const hasSelectedCaseOption = caseOptions.some(
    (workbenchCase) => workbenchCase.case_id === selectedCaseId,
  );
  const hasAnyCaseOption = caseOptions.length > 0 || Boolean(selectedCaseId);

  const canSend = manualMessage.trim().length > 0 && !busy;

  async function handleSend() {
    const nextMessage = manualMessage.trim();
    if (!nextMessage) {
      return;
    }

    const sent = await onSendMessage(nextMessage);
    if (sent !== false) {
      setManualMessage("");
    }
  }

  return (
    <section className="panel run-control" aria-label="运行控制">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">运行控制</div>
          <h2>会话</h2>
        </div>
        <div className="segmented-control" aria-label="案例范围">
          <button
            aria-pressed={!showAll}
            className={!showAll ? "active" : ""}
            disabled={busy}
            onClick={() => setShowAll(false)}
            type="button"
          >
            演示
          </button>
          <button
            aria-pressed={showAll}
            className={showAll ? "active" : ""}
            disabled={busy}
            onClick={() => setShowAll(true)}
            type="button"
          >
            全部
          </button>
        </div>
      </div>

      <label className="field">
        <span>模式</span>
        <select
          disabled={busy}
          onChange={(event) => onModeChange(event.target.value as WorkbenchMode)}
          value={snapshot.mode}
        >
          <option disabled={!llmAvailable} value="llm">
            {llmAvailable ? modeLabel("llm") : "LLM 不可用"}
          </option>
        </select>
      </label>

      <label className="field">
        <span>案例</span>
        <select
          disabled={busy || !hasAnyCaseOption}
          onChange={(event) => onSelectCase(event.target.value)}
          value={selectedCaseId}
        >
          {selectedCaseId && !hasSelectedCaseOption ? (
            <option value={selectedCaseId}>{selectedCaseId}</option>
          ) : null}
          {showAll
            ? caseOptions.map((workbenchCase) => (
                <option key={workbenchCase.case_id} value={workbenchCase.case_id}>
                  {workbenchCase.title}
                </option>
              ))
            : catalog.groups.map((group) => (
                <optgroup key={group.key} label={`${group.emoji} ${group.label}`}>
                  {group.case_ids.map((caseId) => {
                    const workbenchCase = caseOptions.find(
                      (c) => c.case_id === caseId,
                    );
                    if (!workbenchCase) {
                      return null;
                    }
                    return (
                      <option key={caseId} value={caseId}>
                        {workbenchCase.title}
                      </option>
                    );
                  })}
                </optgroup>
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
          <span>单步执行</span>
        </button>
        <button
          className="button"
          disabled={busy || !snapshot.run_controls.can_run_all}
          onClick={onRunAll}
          type="button"
        >
          <Play aria-hidden="true" size={16} />
          <span>运行全部</span>
        </button>
        <button
          className="button"
          disabled={busy || !snapshot.run_controls.can_reset}
          onClick={onReset}
          type="button"
        >
          <RotateCcw aria-hidden="true" size={16} />
          <span>重置</span>
        </button>
      </div>

      <div className="manual-message">
        <label className="field">
          <span>手动用户消息</span>
          <textarea
            disabled={busy}
            onChange={(event) => setManualMessage(event.target.value)}
            placeholder="输入客户回复..."
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
          <span>发送</span>
        </button>
      </div>
    </section>
  );
}
