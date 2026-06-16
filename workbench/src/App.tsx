import { useEffect, useRef, useState } from "react";
import { Moon, Sun } from "@phosphor-icons/react";
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
import { AgentOpsWorkspace } from "./components/AgentOpsWorkspace";
import { Inspector } from "./components/Inspector";
import { RunControl } from "./components/RunControl";
import { Timeline } from "./components/Timeline";
import { modeLabel } from "./labels";
import type {
  WorkbenchConfig,
  WorkbenchMode,
  WorkbenchSnapshot,
} from "./types";

type WorkbenchSurface = "demo" | "agentops";

export function App() {
  const [surface, setSurface] = useState<WorkbenchSurface>("demo");
  const [config, setConfig] = useState<WorkbenchConfig | null>(null);
  const [snapshot, setSnapshot] = useState<WorkbenchSnapshot | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const busyRef = useRef(false);

  function toggleDark() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  }

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
      setError(exc instanceof Error ? exc.message : "工作台请求失败");
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
    <main className="min-h-dvh flex flex-col bg-[#f4f6f8] dark:bg-slate-950 text-[#172033] dark:text-slate-100">
      <header className="topbar-layout flex items-center justify-between gap-4 px-5 py-4 border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
        <div>
          <h1 className="m-0 text-xl font-bold leading-tight text-[#182230] dark:text-white">
            零售客服工作台
          </h1>
          <p className="mt-1 m-0 text-slate-500 dark:text-slate-400 text-sm">
            {surface === "demo"
              ? "零售客服 Agent 演示面板"
              : "AgentOps 运行报告与 Trace 调试台"}
          </p>
        </div>
        <div className="flex items-center justify-end gap-2.5 min-w-0">
          <nav className="inline-flex overflow-hidden rounded-full border border-slate-300 dark:border-slate-600 bg-slate-100 dark:bg-slate-800 p-0.5" aria-label="工作台工作面">
            <button
              className={
                "border-0 rounded-full bg-transparent px-3 py-1.5 text-sm font-bold cursor-pointer transition-colors duration-150 " +
                (surface === "demo"
                  ? "bg-white dark:bg-white text-slate-900 dark:text-slate-900 shadow-sm"
                  : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-white")
              }
              onClick={() => setSurface("demo")}
              type="button"
            >
              Demo
            </button>
            <button
              className={
                "border-0 rounded-full bg-transparent px-3 py-1.5 text-sm font-bold cursor-pointer transition-colors duration-150 " +
                (surface === "agentops"
                  ? "bg-white dark:bg-white text-slate-900 dark:text-slate-900 shadow-sm"
                  : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-white")
              }
              onClick={() => setSurface("agentops")}
              type="button"
            >
              AgentOps
            </button>
          </nav>
          <button
            aria-label={dark ? "切换到亮色模式" : "切换到暗色模式"}
            className="inline-flex items-center justify-center w-9 h-9 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors duration-150 cursor-pointer"
            onClick={toggleDark}
            type="button"
          >
            {dark ? <Sun size={16} weight="bold" /> : <Moon size={16} weight="bold" />}
          </button>
          {surface === "demo" ? (
            <>
              <span className="max-w-[280px] overflow-hidden text-ellipsis whitespace-nowrap text-slate-600 dark:text-slate-400 text-sm font-semibold">
                {selectedCase?.title || "正在加载案例"}
              </span>
              <span className="rounded-full border border-slate-300 dark:border-slate-600 px-2.5 py-1.5 bg-slate-100 dark:bg-slate-800 text-sm font-bold capitalize text-slate-600 dark:text-slate-300">
                {modeLabel(snapshot?.mode || config?.default_mode)}
              </span>
            </>
          ) : (
            <span className="rounded-full border border-slate-300 dark:border-slate-600 px-2.5 py-1.5 bg-slate-100 dark:bg-slate-800 text-sm font-bold capitalize text-slate-600 dark:text-slate-300">
              只读分析
            </span>
          )}
        </div>
      </header>

      {surface === "demo" ? (
        <>
          {error ? (
            <div className="mx-3 mt-3 border border-red-200 dark:border-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-900 dark:text-red-300 p-2.5 text-sm">
              {error}
            </div>
          ) : null}

          {config && snapshot ? (
            <div className="demo-layout flex flex-1 overflow-hidden p-3 pt-3 gap-3">
              {/* Left: RunControl */}
              <aside className="w-64 shrink-0 overflow-y-auto">
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
              </aside>

              {/* Middle: BusinessState + Conversation + Timeline */}
              <main className="flex-1 flex flex-col overflow-hidden gap-3 min-w-0">
                <BusinessState
                  busy={busy}
                  onChange={() => handleSendMessage("change")}
                  onConfirm={() => handleSendMessage("yes")}
                  onDeny={() => handleSendMessage("no")}
                  snapshot={snapshot}
                />
                <div className="flex-1 flex flex-col overflow-hidden min-h-0">
                  <Conversation snapshot={snapshot} />
                </div>
                <div className="shrink-0">
                  <Timeline
                    events={snapshot.timeline}
                    onSelectEvent={setSelectedEventId}
                    selectedEventId={activeEvent?.id || null}
                  />
                </div>
              </main>

              {/* Right: Inspector (可折叠) */}
              <aside
                className={
                  "shrink-0 overflow-hidden transition-all duration-200 ease-in-out " +
                  (activeEvent && snapshot.timeline.length > 0
                    ? "w-72 opacity-100"
                    : "w-0 opacity-0")
                }
              >
                <div className="w-72">
                  <Inspector event={activeEvent} snapshot={snapshot} />
                </div>
              </aside>
            </div>
          ) : (
            <section
              className="m-3 border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 p-6"
              aria-live="polite"
            >
              正在加载工作台...
            </section>
          )}
        </>
      ) : (
        <AgentOpsWorkspace />
      )}
    </main>
  );
}
