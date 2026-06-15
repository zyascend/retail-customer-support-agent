import { requestJson } from "./api";
import type {
  AgentOpsCaseDetail,
  AgentOpsReportDetail,
  AgentOpsReportSummary,
  AgentOpsTraceDetail,
} from "./agentopsTypes";

export function listAgentOpsReports(): Promise<AgentOpsReportSummary[]> {
  return requestJson<AgentOpsReportSummary[]>("/api/agentops/reports");
}

export function getAgentOpsReport(
  runId: string,
): Promise<AgentOpsReportDetail> {
  return requestJson<AgentOpsReportDetail>(
    `/api/agentops/reports/${encodeURIComponent(runId)}`,
  );
}

export function getAgentOpsCase(
  runId: string,
  caseId: string,
): Promise<AgentOpsCaseDetail> {
  return requestJson<AgentOpsCaseDetail>(
    `/api/agentops/reports/${encodeURIComponent(runId)}/cases/${encodeURIComponent(
      caseId,
    )}`,
  );
}

export function getAgentOpsTraceByPath(
  path: string,
): Promise<AgentOpsTraceDetail> {
  return requestJson<AgentOpsTraceDetail>(
    `/api/agentops/traces/by-path?path=${encodeURIComponent(path)}`,
  );
}
