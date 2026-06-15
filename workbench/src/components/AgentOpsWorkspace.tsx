import { useEffect, useState } from "react";
import { listAgentOpsReports } from "../agentopsApi";
import type { AgentOpsReportSummary } from "../agentopsTypes";

export function AgentOpsWorkspace() {
  const [reports, setReports] = useState<AgentOpsReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    listAgentOpsReports()
      .then((nextReports) => {
        if (cancelled) {
          return;
        }

        setReports(nextReports);
        setError(null);
      })
      .catch((exc) => {
        if (!cancelled) {
          setError(exc instanceof Error ? exc.message : "AgentOps 请求失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="agentops-placeholder" aria-label="AgentOps 工作面">
      <div className="panel agentops-placeholder-card">
        <div className="panel-header">
          <div>
            <div className="panel-kicker">AgentOps</div>
            <h2>运行报告工作面</h2>
          </div>
          <span className="count-label">
            {loading ? "加载中" : `${reports.length} 份报告`}
          </span>
        </div>

        <p>
          这里是 AgentOps 浏览器和 Trace 检查器的占位工作区。Task 5 会在这个边界内补齐完整的报告浏览和案例检查体验。
        </p>

        {error ? <div className="error-banner compact">{error}</div> : null}

        {!loading && !error && reports.length === 0 ? (
          <div className="empty-state">尚未发现 AgentOps 运行报告。</div>
        ) : null}

        {reports.length > 0 ? (
          <ul className="agentops-report-list" aria-label="AgentOps 报告列表">
            {reports.map((report) => (
              <li key={report.run_id}>
                <strong>{report.run_id}</strong>
                <span>
                  {report.subset} · {report.pass_count} 通过 / {report.fail_count} 失败
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );
}
