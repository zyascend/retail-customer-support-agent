export type WorkbenchMode = "deterministic" | "llm";

export interface WorkbenchCase {
  case_id: string;
  title: string;
  category: string;
  message_count: number;
  messages: Array<{ role: string; content: string }>;
  expected_user_id: string | null;
  expected_intent: string;
  expected_order_status: string | null;
  expected_confirmation_status: string | null;
  expected_guard_block_reason: string | null;
  expected_no_write: boolean;
  expected_tool_names: string[];
  expected_assistant_contains: string | null;
}

export interface CaseGroup {
  key: string;
  label: string;
  emoji: string;
  case_ids: string[];
}

export interface CaseCatalog {
  subset: string;
  demo_case_ids: string[];
  demo_cases: WorkbenchCase[];
  all_cases: WorkbenchCase[];
  groups: CaseGroup[];
}

export interface WorkbenchConfig {
  default_mode: WorkbenchMode;
  llm_available: boolean;
  model: string;
  case_catalog: CaseCatalog;
}

export interface TimelineEvent {
  id: string;
  kind: "message" | "step" | "tool_call" | "write_audit";
  label: string;
  status: string | null;
  timestamp: string | null;
  summary: string | null;
  detail: unknown;
  source_index: number;
  weight: "primary" | "secondary";
}

export interface WorkbenchError {
  code: string;
  message: string;
  recoverable: boolean;
  details?: Record<string, unknown>;
}

export interface WorkbenchSnapshot {
  session_id: string;
  mode: WorkbenchMode;
  llm_available: boolean;
  selected_case_id: string | null;
  script_cursor: number;
  script_message_count: number;
  run_controls: {
    can_step: boolean;
    can_run_all: boolean;
    can_reset: boolean;
  };
  messages: Array<{ role: string; content: string; created_at?: string }>;
  business: {
    authenticated_user_id: string | null;
    auth_method: string | null;
    active_user_identity: unknown;
    active_order_id: string | null;
    current_intent: string;
    slots: Record<string, unknown>;
    confirmation_status: string;
    db_changed: boolean;
    initial_db_hash: string | null;
    current_db_hash: string | null;
    write_locks: string[];
  };
  pending_action: null | {
    action_name: string;
    arguments: Record<string, unknown>;
    user_facing_summary: string;
  };
  policy_decision: unknown;
  tool_results: unknown[];
  timeline: TimelineEvent[];
  audit_logs: unknown[];
  guard_blocks: unknown[];
  trace_artifact_path: string | null;
  last_error: WorkbenchError | null;
}
