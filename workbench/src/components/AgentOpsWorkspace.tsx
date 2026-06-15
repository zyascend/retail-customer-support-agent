import { useEffect, useMemo, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import {
  getAgentOpsCase,
  getAgentOpsReport,
  getAgentOpsTraceByPath,
  listAgentOpsReports,
} from "../agentopsApi";
import type {
  AgentOpsCaseDetail,
  AgentOpsReportDetail,
  AgentOpsReportSummary,
  AgentOpsTraceDetail,
} from "../agentopsTypes";
import type { TimelineEvent } from "../types";
import { AgentOpsBrowser } from "./AgentOpsBrowser";
import { AgentOpsInspector } from "./AgentOpsInspector";
import { Timeline } from "./Timeline";

export function AgentOpsWorkspace() {
  const [reports, setReports] = useState<AgentOpsReportSummary[]>([]);
  const [selectedReport, setSelectedReport] =
    useState<AgentOpsReportDetail | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [selectedCase, setSelectedCase] = useState<AgentOpsCaseDetail | null>(
    null,
  );
  const [selectedTrace, setSelectedTrace] =
    useState<AgentOpsTraceDetail | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [failureOnly, setFailureOnly] = useState(true);
  const [reportsLoading, setReportsLoading] = useState(true);
  const [reportLoading, setReportLoading] = useState(false);
  const [caseLoading, setCaseLoading] = useState(false);
  const [traceLoading, setTraceLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const reportRequestRef = useRef(0);
  const caseRequestRef = useRef(0);
  const traceRequestRef = useRef(0);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    setReportsLoading(true);
    listAgentOpsReports()
      .then((nextReports) => {
        if (cancelled || !mountedRef.current) {
          return;
        }

        setReports(nextReports);
        setError(null);

        const firstReport = nextReports[0];
        if (firstReport) {
          void handleSelectReport(firstReport.run_id);
        }
      })
      .catch((exc) => {
        if (!cancelled && mountedRef.current) {
          setError(errorMessage(exc, "AgentOps 报告列表加载失败"));
        }
      })
      .finally(() => {
        if (!cancelled && mountedRef.current) {
          setReportsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSelectReport(runId: string): Promise<void> {
    const requestId = reportRequestRef.current + 1;
    reportRequestRef.current = requestId;
    caseRequestRef.current += 1;
    traceRequestRef.current += 1;

    setReportLoading(true);
    setCaseLoading(false);
    setTraceLoading(false);
    setError(null);
    setFailureOnly(true);
    setSelectedReport(null);
    setSelectedCaseId(null);
    setSelectedCase(null);
    setSelectedTrace(null);
    setSelectedEventId(null);

    try {
      const report = await getAgentOpsReport(runId);
      if (!isCurrent(reportRequestRef, requestId, mountedRef)) {
        return;
      }

      setSelectedReport(report);
    } catch (exc) {
      if (isCurrent(reportRequestRef, requestId, mountedRef)) {
        setError(errorMessage(exc, "AgentOps 报告加载失败"));
      }
    } finally {
      if (isCurrent(reportRequestRef, requestId, mountedRef)) {
        setReportLoading(false);
      }
    }
  }

  async function handleSelectCase(caseId: string): Promise<void> {
    if (!selectedReport) {
      return;
    }

    const runId = selectedReport.run_id;
    const caseRequestId = caseRequestRef.current + 1;
    const traceRequestId = traceRequestRef.current + 1;
    caseRequestRef.current = caseRequestId;
    traceRequestRef.current = traceRequestId;

    setCaseLoading(true);
    setTraceLoading(false);
    setError(null);
    setSelectedCaseId(caseId);
    setSelectedCase(null);
    setSelectedTrace(null);
    setSelectedEventId(null);

    try {
      const detail = await getAgentOpsCase(runId, caseId);
      if (!isCurrent(caseRequestRef, caseRequestId, mountedRef)) {
        return;
      }

      setSelectedCase(detail);

      if (!detail.trace_artifact_path) {
        return;
      }

      setTraceLoading(true);
      const trace = await getAgentOpsTraceByPath(detail.trace_artifact_path);
      if (
        !isCurrent(caseRequestRef, caseRequestId, mountedRef) ||
        !isCurrent(traceRequestRef, traceRequestId, mountedRef)
      ) {
        return;
      }

      setSelectedTrace(trace);
      setSelectedEventId(selectInitialTraceEvent(trace.timeline));
    } catch (exc) {
      if (isCurrent(caseRequestRef, caseRequestId, mountedRef)) {
        setError(errorMessage(exc, "AgentOps 案例或 Trace 加载失败"));
      }
    } finally {
      if (isCurrent(caseRequestRef, caseRequestId, mountedRef)) {
        setCaseLoading(false);
      }
      if (isCurrent(traceRequestRef, traceRequestId, mountedRef)) {
        setTraceLoading(false);
      }
    }
  }

  async function handleOpenTracePath(path: string): Promise<void> {
    const tracePath = path.trim();
    if (!tracePath) {
      setError("请输入 Trace 文件绝对路径。");
      return;
    }

    const traceRequestId = traceRequestRef.current + 1;
    traceRequestRef.current = traceRequestId;
    caseRequestRef.current += 1;

    setTraceLoading(true);
    setCaseLoading(false);
    setError(null);
    setSelectedCaseId(null);
    setSelectedCase(null);
    setSelectedTrace(null);
    setSelectedEventId(null);

    try {
      const trace = await getAgentOpsTraceByPath(tracePath);
      if (!isCurrent(traceRequestRef, traceRequestId, mountedRef)) {
        return;
      }

      setSelectedTrace(trace);
      setSelectedEventId(selectInitialTraceEvent(trace.timeline));
    } catch (exc) {
      if (isCurrent(traceRequestRef, traceRequestId, mountedRef)) {
        setError(errorMessage(exc, "Trace 加载失败"));
      }
    } finally {
      if (isCurrent(traceRequestRef, traceRequestId, mountedRef)) {
        setTraceLoading(false);
      }
    }
  }

  const visibleCases = useMemo(() => {
    if (!selectedReport) {
      return [];
    }

    return selectedReport.cases.filter((item) =>
      failureOnly ? !item.passed : true,
    );
  }, [failureOnly, selectedReport]);

  const activeEvent =
    selectedTrace?.timeline.find((event) => event.id === selectedEventId) ||
    selectedTrace?.timeline.at(-1) ||
    null;

  return (
    <section className="agentops-grid" aria-label="AgentOps 调试台">
      <AgentOpsBrowser
        busy={reportsLoading || reportLoading || caseLoading || traceLoading}
        error={error}
        failureOnly={failureOnly}
        onFailureOnlyChange={setFailureOnly}
        onOpenTracePath={handleOpenTracePath}
        onSelectCase={handleSelectCase}
        onSelectReport={handleSelectReport}
        reportLoading={reportLoading}
        reports={reports}
        reportsLoading={reportsLoading}
        selectedCaseId={selectedCaseId}
        selectedReport={selectedReport}
        visibleCases={visibleCases}
      />

      <div className="agentops-timeline-column">
        <section className="panel agentops-trace-card" aria-label="Trace 摘要">
          <div className="panel-header">
            <div>
              <div className="panel-kicker">Trace</div>
              <h2>{selectedTrace?.trace_id || "尚未打开 Trace"}</h2>
            </div>
            <span className="count-label">
              {traceLoading
                ? "加载中"
                : selectedTrace
                  ? `${selectedTrace.timeline.length} 个事件`
                  : "等待选择"}
            </span>
          </div>
          <dl className="agentops-trace-facts">
            <div>
              <dt>Trace 文件</dt>
              <dd>{selectedTrace?.trace_artifact_path || "选择案例或输入路径后显示"}</dd>
            </div>
            <div>
              <dt>当前事件</dt>
              <dd>{activeEvent?.id || "未选择"}</dd>
            </div>
          </dl>
        </section>

        <Timeline
          events={selectedTrace?.timeline || []}
          onSelectEvent={setSelectedEventId}
          selectedEventId={activeEvent?.id || null}
        />
      </div>

      <AgentOpsInspector
        caseLoading={caseLoading}
        event={activeEvent}
        selectedCase={selectedCase}
        trace={selectedTrace}
        traceLoading={traceLoading}
      />
    </section>
  );
}

function isCurrent(
  ref: MutableRefObject<number>,
  requestId: number,
  mountedRef: MutableRefObject<boolean>,
): boolean {
  return mountedRef.current && ref.current === requestId;
}

function selectInitialTraceEvent(events: TimelineEvent[]): string | null {
  const failureEvent = [...events]
    .reverse()
    .find(
      (event) =>
        isProblemStatus(event.status) ||
        (event.kind === "tool_call" && isProblemStatus(event.status)),
    );

  return failureEvent?.id || events.at(-1)?.id || null;
}

function isProblemStatus(status: string | null): boolean {
  return ["blocked", "error", "failed", "failure"].includes(
    (status || "").toLowerCase(),
  );
}

function errorMessage(exc: unknown, fallback: string): string {
  return exc instanceof Error ? exc.message : fallback;
}
