import type { TimelineEvent } from "./types";

export interface AgentOpsReportSummary {
  run_id: string;
  report_path: string;
  created_at: string;
  eval_backend: string;
  model: string;
  provider: string;
  subset: string;
  pass_count: number;
  fail_count: number;
  failure_case_count: number;
}

export interface AgentOpsReportCaseSummary {
  case_id: string;
  subset: string | null;
  passed: boolean;
  failure_label: string | null;
  root_cause: string | null;
  trace_artifact_path: string | null;
}

export interface AgentOpsReportDetail {
  run_id: string;
  report_path: string;
  created_at: string;
  eval_backend: string;
  model: string;
  provider: string;
  subset: string;
  baseline_metadata: Record<string, unknown>;
  metrics: Record<string, unknown>;
  cases: AgentOpsReportCaseSummary[];
}

export interface AgentOpsCaseDetail {
  case_id: string;
  run_id: string;
  subset: string | null;
  passed: boolean;
  failure_label: string | null;
  root_cause: string | null;
  trace_artifact_path: string | null;
  user_messages: string[];
  assistant_messages: string[];
  guard_context: Array<Record<string, unknown>>;
  db_assertion_diff: Record<string, unknown>;
  tool_calls: Array<Record<string, unknown>>;
  trace_summary: Record<string, unknown>;
  trace_detail: AgentOpsTraceDetail;
}

export interface AgentOpsTraceDetail {
  trace_id: string;
  trace_artifact_path: string;
  metadata: Record<string, unknown>;
  timeline: TimelineEvent[];
  turns: Array<Record<string, unknown>>;
  final_state: Record<string, unknown>;
  db_hashes: Record<string, unknown>;
  llm_responses: Array<Record<string, unknown>>;
  tool_calls: Array<Record<string, unknown>>;
}
