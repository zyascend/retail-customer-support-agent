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
    <section className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3 flex flex-col gap-3 max-h-[calc(100dvh-98px)] overflow-hidden" aria-label="报告与案例浏览">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="mb-0.5 text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">AgentOps</div>
          <h2 className="m-0 text-base leading-tight text-[#182230] dark:text-white">报告与案例</h2>
        </div>
        <span className="inline-flex items-center rounded-full bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 text-xs font-extrabold leading-none whitespace-nowrap px-2 py-1.5">
          {reportsLoading ? "加载中" : `${reports.length} 份报告`}
        </span>
      </div>

      {error ? (
        <div className="m-0 border border-red-200 dark:border-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-900 dark:text-red-300 p-2.5 text-sm" role="alert">
          {error}
        </div>
      ) : null}

      <label className="grid gap-1.5">
        <span className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">评估报告</span>
        <select
          className="w-full min-w-0 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-[#182230] dark:text-white px-2.5 py-2 focus:outline-2 focus:outline-blue-500 focus:outline-offset-2 disabled:opacity-62 disabled:cursor-not-allowed"
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
        <div className="grid gap-2 max-h-[208px] overflow-auto" aria-label="报告列表">
          {reports.slice(0, 5).map((report) => (
            <button
              className={
                "w-full min-w-0 text-left grid gap-1 border rounded-lg p-2.5 cursor-pointer transition-shadow duration-200 disabled:opacity-62 disabled:cursor-not-allowed " +
                (selectedReport?.run_id === report.run_id
                  ? "border-blue-500 shadow-[0_0_0_2px_rgba(37,99,235,0.14)] dark:shadow-[0_0_0_2px_rgba(59,130,246,0.3)] bg-white dark:bg-slate-800"
                  : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-600")
              }
              disabled={reportLoading}
              key={report.run_id}
              onClick={() => void onSelectReport(report.run_id)}
              type="button"
            >
              <strong className="overflow-hidden text-ellipsis whitespace-nowrap text-[#182230] dark:text-white text-sm">{report.run_id}</strong>
              <span className="min-w-0 break-anywhere text-slate-500 dark:text-slate-400 text-xs font-bold">
                {report.provider || "未知服务商"} · {report.model || "未知模型"}
              </span>
              <small className="min-w-0 break-anywhere text-slate-500 dark:text-slate-400 text-xs font-bold">
                {report.pass_count} 通过 / {report.fail_count} 失败
              </small>
            </button>
          ))}
        </div>
      ) : null}

      <SelectedReportFacts report={selectedReport} reportLoading={reportLoading} />

      <form className="grid gap-2" onSubmit={handleTraceSubmit}>
        <label className="grid gap-1.5">
          <span className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">直接打开 Trace</span>
          <input
            className="w-full min-w-0 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-[#182230] dark:text-white px-2.5 py-2 focus:outline-2 focus:outline-blue-500 focus:outline-offset-2 disabled:opacity-62 disabled:cursor-not-allowed"
            onChange={(event) => setTracePath(event.target.value)}
            placeholder="粘贴 Trace 文件绝对路径"
            type="text"
            value={tracePath}
          />
        </label>
        <button
          className="inline-flex items-center justify-center gap-1.5 min-h-9 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2.5 py-2 text-sm font-bold leading-none whitespace-nowrap cursor-pointer transition-colors duration-150 active:translate-y-px disabled:opacity-62 disabled:cursor-not-allowed"
          disabled={busy || !tracePath.trim()}
          type="submit"
        >
          打开 Trace
        </button>
      </form>

      <div className="flex items-center justify-between gap-2">
        <label className="flex items-center gap-2 min-w-0 text-slate-700 dark:text-slate-300 text-sm font-bold">
          <input
            className="w-auto min-w-auto"
            checked={failureOnly}
            disabled={!selectedReport}
            onChange={(event) => onFailureOnlyChange(event.target.checked)}
            type="checkbox"
          />
          <span>仅显示失败案例</span>
        </label>
        <span className="inline-flex items-center rounded-full bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 text-xs font-extrabold leading-none whitespace-nowrap px-2 py-1.5">
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
    return <div className="border border-dashed border-slate-300 dark:border-slate-600 rounded-lg text-slate-500 dark:text-slate-400 p-3.5 text-sm">正在加载选中报告...</div>;
  }

  if (!report) {
    return <div className="border border-dashed border-slate-300 dark:border-slate-600 rounded-lg text-slate-500 dark:text-slate-400 p-3.5 text-sm">选择一份报告后显示运行元数据。</div>;
  }

  return (
    <dl className="grid grid-cols-2 gap-2 m-0">
      <div className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-[#f8fafc] dark:bg-slate-700/30 p-2">
        <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">数据集</dt>
        <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{report.subset || "未记录"}</dd>
      </div>
      <div className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-[#f8fafc] dark:bg-slate-700/30 p-2">
        <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">服务商</dt>
        <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{report.provider || "未记录"}</dd>
      </div>
      <div className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-[#f8fafc] dark:bg-slate-700/30 p-2">
        <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">模型</dt>
        <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{report.model || "未记录"}</dd>
      </div>
      <div className="min-w-0 border border-slate-200 dark:border-slate-700 rounded-lg bg-[#f8fafc] dark:bg-slate-700/30 p-2">
        <dt className="text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">创建时间</dt>
        <dd className="mt-1 break-anywhere text-[#182230] dark:text-white text-sm font-bold">{formatDateTime(report.created_at)}</dd>
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
    return <div className="border border-dashed border-slate-300 dark:border-slate-600 rounded-lg text-slate-500 dark:text-slate-400 p-3.5 text-sm">先选择报告，再查看案例列表。</div>;
  }

  if (cases.length === 0) {
    return (
      <div className="border border-dashed border-slate-300 dark:border-slate-600 rounded-lg text-slate-500 dark:text-slate-400 p-3.5 text-sm">
        当前过滤条件下没有案例。可以关闭"仅显示失败案例"查看全部案例。
      </div>
    );
  }

  return (
    <div className="grid gap-2 min-h-0 overflow-auto" aria-label="案例列表">
      {cases.map((item) => (
        <button
          className={
            "w-full min-w-0 text-left grid gap-1.5 border rounded-lg p-2.5 cursor-pointer relative transition-shadow duration-200 disabled:opacity-62 disabled:cursor-not-allowed " +
            (item.passed ? "" : "border-red-200 dark:border-red-800 bg-red-50/50 dark:bg-red-950/20") +
            " " +
            (selectedCaseId === item.case_id
              ? "border-blue-500 shadow-[0_0_0_2px_rgba(37,99,235,0.14)] dark:shadow-[0_0_0_2px_rgba(59,130,246,0.3)]"
              : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-600")
          }
          disabled={busy}
          key={item.case_id}
          onClick={() => void onSelectCase(item.case_id)}
          type="button"
        >
          <span
            className={
              "justify-self-start rounded-full px-1.5 py-1 text-[11px] font-black leading-none " +
              (item.passed
                ? "bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300"
                : "bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300")
            }
          >
            {item.passed ? "通过" : "失败"}
          </span>
          <strong className="overflow-hidden text-ellipsis whitespace-nowrap text-[#182230] dark:text-white text-sm">{item.case_id}</strong>
          <span className="min-w-0 break-anywhere text-slate-500 dark:text-slate-400 text-xs font-bold">{caseSummary(item)}</span>
          <small className="min-w-0 break-anywhere text-slate-500 dark:text-slate-400 text-xs font-bold">
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
