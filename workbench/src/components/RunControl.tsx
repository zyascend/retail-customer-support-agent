import { ArrowCounterClockwise, PaperPlaneTilt, Play, SkipForward } from "@phosphor-icons/react";
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
    <section className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3" aria-label="运行控制">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="mb-0.5 text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">运行控制</div>
          <h2 className="m-0 text-base leading-tight text-[#182230] dark:text-white">会话</h2>
        </div>
        <div className="grid grid-cols-2 overflow-hidden rounded-lg border border-slate-300 dark:border-slate-600 bg-slate-100 dark:bg-slate-800" aria-label="案例范围">
          <button
            aria-pressed={!showAll}
            className={
              "min-w-[56px] border-0 px-2.5 py-1.5 text-sm font-bold cursor-pointer transition-colors duration-150 " +
              (!showAll
                ? "bg-slate-800 dark:bg-white text-white dark:text-slate-900"
                : "bg-transparent text-slate-600 dark:text-slate-400 hover:text-slate-800 dark:hover:text-white")
            }
            disabled={busy}
            onClick={() => setShowAll(false)}
            type="button"
          >
            演示
          </button>
          <button
            aria-pressed={showAll}
            className={
              "min-w-[56px] border-0 px-2.5 py-1.5 text-sm font-bold cursor-pointer transition-colors duration-150 " +
              (showAll
                ? "bg-slate-800 dark:bg-white text-white dark:text-slate-900"
                : "bg-transparent text-slate-600 dark:text-slate-400 hover:text-slate-800 dark:hover:text-white")
            }
            disabled={busy}
            onClick={() => setShowAll(true)}
            type="button"
          >
            全部
          </button>
        </div>
      </div>

      <label className="grid gap-1.5 mb-3">
        <span className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">模式</span>
        <select
          className="w-full min-w-0 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-[#182230] dark:text-white px-2.5 py-2 focus:outline-2 focus:outline-blue-500 focus:outline-offset-2 disabled:opacity-62 disabled:cursor-not-allowed"
          disabled={busy}
          onChange={(event) => onModeChange(event.target.value as WorkbenchMode)}
          value={snapshot.mode}
        >
          <option disabled={!llmAvailable} value="llm">
            {llmAvailable ? modeLabel("llm") : "LLM 不可用"}
          </option>
        </select>
      </label>

      <label className="grid gap-1.5 mb-3">
        <span className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">案例</span>
        <select
          className="w-full min-w-0 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-[#182230] dark:text-white px-2.5 py-2 focus:outline-2 focus:outline-blue-500 focus:outline-offset-2 disabled:opacity-62 disabled:cursor-not-allowed"
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
                <optgroup key={group.key} label={group.label}>
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

      <div className="flex flex-wrap gap-2">
        <button
          className="inline-flex items-center justify-center gap-1.5 min-h-9 border border-slate-800 dark:border-slate-200 rounded-lg bg-slate-800 dark:bg-white text-white dark:text-slate-900 px-2.5 py-2 text-sm font-bold leading-none whitespace-nowrap cursor-pointer transition-colors duration-150 active:translate-y-px disabled:opacity-62 disabled:cursor-not-allowed"
          disabled={busy || !snapshot.run_controls.can_step}
          onClick={onStep}
          type="button"
        >
          <SkipForward aria-hidden="true" size={16} weight="bold" />
          <span>单步执行</span>
        </button>
        <button
          className="inline-flex items-center justify-center gap-1.5 min-h-9 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2.5 py-2 text-sm font-bold leading-none whitespace-nowrap cursor-pointer transition-colors duration-150 active:translate-y-px disabled:opacity-62 disabled:cursor-not-allowed"
          disabled={busy || !snapshot.run_controls.can_run_all}
          onClick={onRunAll}
          type="button"
        >
          <Play aria-hidden="true" size={16} weight="bold" />
          <span>运行全部</span>
        </button>
        <button
          className="inline-flex items-center justify-center gap-1.5 min-h-9 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2.5 py-2 text-sm font-bold leading-none whitespace-nowrap cursor-pointer transition-colors duration-150 active:translate-y-px disabled:opacity-62 disabled:cursor-not-allowed"
          disabled={busy || !snapshot.run_controls.can_reset}
          onClick={onReset}
          type="button"
        >
          <ArrowCounterClockwise aria-hidden="true" size={16} weight="bold" />
          <span>重置</span>
        </button>
      </div>

      <div className="mt-3.5 border-t border-slate-200 dark:border-slate-700 pt-3">
        <label className="grid gap-1.5 mb-3">
          <span className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">手动用户消息</span>
          <textarea
            className="w-full min-w-0 min-h-24 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-[#182230] dark:text-white px-2.5 py-2 resize-y focus:outline-2 focus:outline-blue-500 focus:outline-offset-2 disabled:opacity-62 disabled:cursor-not-allowed"
            disabled={busy}
            onChange={(event) => setManualMessage(event.target.value)}
            placeholder="输入客户回复..."
            rows={4}
            value={manualMessage}
          />
        </label>
        <button
          className="w-full inline-flex items-center justify-center gap-1.5 min-h-9 border border-slate-800 dark:border-slate-200 rounded-lg bg-slate-800 dark:bg-white text-white dark:text-slate-900 px-2.5 py-2 text-sm font-bold leading-none whitespace-nowrap cursor-pointer transition-colors duration-150 active:translate-y-px disabled:opacity-62 disabled:cursor-not-allowed"
          disabled={!canSend}
          onClick={handleSend}
          type="button"
        >
          <PaperPlaneTilt aria-hidden="true" size={16} weight="bold" />
          <span>发送</span>
        </button>
      </div>
    </section>
  );
}
