import { useState } from "react";
import type { FormEvent } from "react";

import type {
  AgentOpsReportCaseSummary,
  AgentOpsReportDetail,
  AgentOpsReportSummary,
} from "../agentopsTypes";

interface AgentOpsBrowserProps {
  busy: boolean;
  error: string | null;
  failureOnly: boolean;
  reportLoading: boolean;
  reports: AgentOpsReportSummary[];
  reportsLoading: boolean;
  selectedCaseId: string | null;
  selectedReport: AgentOpsReportDetail | null;
  visibleCases: AgentOpsReportCaseSummary[];
  onFailureOnlyChange: (next: boolean) => void;
  onOpenTracePath: (path: string) => Promise<void>;
  onSelectCase: (caseId: string) => Promise<void>;
  onSelectReport: (runId: string) => Promise<void>;
}

export function AgentOpsBrowser({
  busy,
  error,
  failureOnly,
  reportLoading,
  reports,
  reportsLoading,
  selectedCaseId,
  selectedReport,
  visibleCases,
  onFailureOnlyChange,
  onOpenTracePath,
  onSelectCase,
  onSelectReport,
}: AgentOpsBrowserProps) {
  const [tracePath, setTracePath] = useState("");

  function handleTraceSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void onOpenTracePath(tracePath);
  }

  return (
    <section className="panel agentops-browser" aria-label="报告与案例浏览">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">AgentOps</div>
          <h2>报告与案例</h2>
        </div>
        <span className="count-label">
          {reportsLoading ? "加载中" : `${reports.length} 份报告`}
        </span>
      </div>

      {error ? (
        <div className="error-banner inline-error" role="alert">
          {error}
        </div>
      ) : null}

      <label className="field">
        <span>评估报告</span>
        <select
          disabled={reportsLoading || reports.length === 0}
          onChange={(event) => void onSelectReport(event.target.value)}
          value={selectedReport?.run_id || ""}
        >
          <option value="" disabled>
            {reportsLoading ? "正在加载报告" : "选择报告"}
          </option>
          {reports.map((report) => (
            <option key={report.run_id} value={report.run_id}>
              {report.run_id} · {report.subset || "未分组"} · 失败{" "}
              {report.fail_count}
            </option>
          ))}
        </select>
      </label>

      {reports.length > 0 ? (
        <div className="agentops-report-picker" aria-label="报告列表">
          {reports.slice(0, 5).map((report) => (
            <button
              className={
                "agentops-report-card" +
                (selectedReport?.run_id === report.run_id ? " selected" : "")
              }
              disabled={reportLoading}
              key={report.run_id}
              onClick={() => void onSelectReport(report.run_id)}
              type="button"
            >
              <strong>{report.run_id}</strong>
              <span>
                {report.provider || "未知服务商"} · {report.model || "未知模型"}
              </span>
              <small>
                {report.pass_count} 通过 / {report.fail_count} 失败
              </small>
            </button>
          ))}
        </div>
      ) : null}

      <SelectedReportFacts report={selectedReport} reportLoading={reportLoading} />

      <form className="agentops-trace-form" onSubmit={handleTraceSubmit}>
        <label className="field">
          <span>直接打开 Trace</span>
          <input
            onChange={(event) => setTracePath(event.target.value)}
            placeholder="粘贴 Trace 文件绝对路径"
            type="text"
            value={tracePath}
          />
        </label>
        <button className="button" disabled={busy || !tracePath.trim()} type="submit">
          打开 Trace
        </button>
      </form>

      <div className="agentops-case-toolbar">
        <label className="checkbox-row">
          <input
            checked={failureOnly}
            disabled={!selectedReport}
            onChange={(event) => onFailureOnlyChange(event.target.checked)}
            type="checkbox"
          />
          <span>仅显示失败案例</span>
        </label>
        <span className="count-label">
          {selectedReport ? `${visibleCases.length} 个案例` : "未选择报告"}
        </span>
      </div>

      <CaseList
        busy={busy}
        cases={visibleCases}
        selectedCaseId={selectedCaseId}
        selectedReport={selectedReport}
        onSelectCase={onSelectCase}
      />
    </section>
  );
}

function SelectedReportFacts({
  report,
  reportLoading,
}: {
  report: AgentOpsReportDetail | null;
  reportLoading: boolean;
}) {
  if (reportLoading) {
    return <div className="empty-state">正在加载选中报告...</div>;
  }

  if (!report) {
    return <div className="empty-state">选择一份报告后显示运行元数据。</div>;
  }

  return (
    <dl className="agentops-report-facts">
      <div>
        <dt>数据集</dt>
        <dd>{report.subset || "未记录"}</dd>
      </div>
      <div>
        <dt>服务商</dt>
        <dd>{report.provider || "未记录"}</dd>
      </div>
      <div>
        <dt>模型</dt>
        <dd>{report.model || "未记录"}</dd>
      </div>
      <div>
        <dt>创建时间</dt>
        <dd>{formatDateTime(report.created_at)}</dd>
      </div>
    </dl>
  );
}

function CaseList({
  busy,
  cases,
  selectedCaseId,
  selectedReport,
  onSelectCase,
}: {
  busy: boolean;
  cases: AgentOpsReportCaseSummary[];
  selectedCaseId: string | null;
  selectedReport: AgentOpsReportDetail | null;
  onSelectCase: (caseId: string) => Promise<void>;
}) {
  if (!selectedReport) {
    return <div className="empty-state">先选择报告，再查看案例列表。</div>;
  }

  if (cases.length === 0) {
    return (
      <div className="empty-state">
        当前过滤条件下没有案例。可以关闭“仅显示失败案例”查看全部案例。
      </div>
    );
  }

  return (
    <div className="case-list" aria-label="案例列表">
      {cases.map((item) => (
        <button
          className={
            "case-list-item" +
            (item.passed ? "" : " is-failing") +
            (selectedCaseId === item.case_id ? " selected" : "")
          }
          disabled={busy}
          key={item.case_id}
          onClick={() => void onSelectCase(item.case_id)}
          type="button"
        >
          <span className={item.passed ? "case-result passed" : "case-result failed"}>
            {item.passed ? "通过" : "失败"}
          </span>
          <strong>{item.case_id}</strong>
          <span>{caseSummary(item)}</span>
          <small>
            {item.trace_artifact_path ? "已关联 Trace" : "未记录 Trace 路径"}
          </small>
        </button>
      ))}
    </div>
  );
}

function caseSummary(item: AgentOpsReportCaseSummary): string {
  if (item.root_cause || item.failure_label) {
    return [item.root_cause, item.failure_label].filter(Boolean).join(" / ");
  }

  return item.passed ? "评估通过" : "未记录失败原因";
}

function formatDateTime(value: string): string {
  if (!value) {
    return "未记录";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("zh-CN", { hour12: false });
}
