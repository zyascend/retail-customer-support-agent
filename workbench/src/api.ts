import type { WorkbenchConfig, WorkbenchMode, WorkbenchSnapshot } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  const payload = await response.json();

  if (!response.ok) {
    const message =
      payload?.error?.message || `Request failed: ${response.status}`;
    throw new Error(message);
  }

  return payload as T;
}

export function fetchConfig(): Promise<WorkbenchConfig> {
  return request<WorkbenchConfig>("/api/workbench/config");
}

export function createSession(
  mode: WorkbenchMode,
  caseId?: string,
): Promise<WorkbenchSnapshot> {
  return request<WorkbenchSnapshot>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ mode, case_id: caseId || null }),
  });
}

export function selectCase(
  sessionId: string,
  caseId: string,
): Promise<WorkbenchSnapshot> {
  return request<WorkbenchSnapshot>(`/api/sessions/${sessionId}/select-case`, {
    method: "POST",
    body: JSON.stringify({ case_id: caseId }),
  });
}

export function stepSession(sessionId: string): Promise<WorkbenchSnapshot> {
  return request<WorkbenchSnapshot>(`/api/sessions/${sessionId}/step`, {
    method: "POST",
  });
}

export function runAll(sessionId: string): Promise<WorkbenchSnapshot> {
  return request<WorkbenchSnapshot>(`/api/sessions/${sessionId}/run-all`, {
    method: "POST",
  });
}

export function sendMessage(
  sessionId: string,
  content: string,
): Promise<WorkbenchSnapshot> {
  return request<WorkbenchSnapshot>(`/api/sessions/${sessionId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function resetSession(
  sessionId: string,
  caseId?: string,
  mode?: WorkbenchMode,
): Promise<WorkbenchSnapshot> {
  return request<WorkbenchSnapshot>(`/api/sessions/${sessionId}/reset`, {
    method: "POST",
    body: JSON.stringify({ case_id: caseId || null, mode: mode || null }),
  });
}
