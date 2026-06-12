from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
SENSITIVE_KEYS = {
    "address",
    "email",
    "payment",
    "payment_method",
    "phone",
    "street",
    "zip",
    "zipcode",
}


@dataclass
class DashboardCase:
    case_id: str
    category: str
    trial: int
    passed: bool
    failure_label: Optional[str]
    failure_summary: Optional[str]
    duration_seconds: float
    trace_artifact_path: str
    replay_metadata: Dict[str, Any]
    metrics: Dict[str, Any]
    result: Dict[str, Any]
    trace: Dict[str, Any]
    trace_path: str


class DashboardBuilder:
    def __init__(self, *, redact: bool = True) -> None:
        self.redact = redact

    def build(self, report: Dict[str, Any], report_path: Path) -> Dict[str, Any]:
        cases = [
            self._build_case(result, report_path)
            for result in report.get("results", [])
        ]
        failure_counts = report.get("failure_analysis", {}).get(
            "failure_label_counts", {}
        )
        categories = sorted({case.category for case in cases})
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": "phase3.dashboard.v1",
            "report": {
                "eval_run_id": report.get("eval_run_id"),
                "subset": report.get("subset"),
                "trials": report.get("trials"),
                "model": report.get("model"),
                "agent_strategy": report.get("agent_strategy"),
                "dataset_root": report.get("dataset_root"),
                "dataset_db_path": report.get("dataset_db_path"),
                "code_commit": report.get("code_commit"),
                "metrics": report.get("metrics", {}),
                "failure_counts": failure_counts,
                "case_count": len(cases),
                "passed_count": sum(1 for case in cases if case.passed),
            },
            "categories": categories,
            "cases": [asdict(case) for case in cases],
        }

    def render_html(self, data: Dict[str, Any]) -> str:
        payload = json.dumps(data, ensure_ascii=True, sort_keys=True)
        payload = payload.replace("</", "<\\/")
        return DASHBOARD_TEMPLATE.replace("__DASHBOARD_DATA__", payload)

    def _build_case(self, result: Dict[str, Any], report_path: Path) -> DashboardCase:
        safe_result = self._redact_payload(result) if self.redact else result
        trace_path = self._resolve_trace_path(result, report_path)
        trace = self._read_trace(trace_path) if trace_path else {}
        return DashboardCase(
            case_id=str(safe_result.get("case_id", "")),
            category=str(safe_result.get("category", "")),
            trial=int(safe_result.get("trial", 0)),
            passed=bool(safe_result.get("passed")),
            failure_label=safe_result.get("failure_label"),
            failure_summary=safe_result.get("failure_summary"),
            duration_seconds=float(safe_result.get("duration_seconds", 0.0)),
            trace_artifact_path=str(safe_result.get("trace_artifact_path", "")),
            replay_metadata=dict(safe_result.get("replay_metadata", {})),
            metrics={
                "tool_call_count": safe_result.get("tool_call_count"),
                "successful_tool_calls": safe_result.get("successful_tool_calls"),
                "failed_tool_calls": safe_result.get("failed_tool_calls"),
                "blocked_tool_calls": safe_result.get("blocked_tool_calls"),
                "tool_errors": safe_result.get("tool_errors"),
                "guard_blocks": safe_result.get("guard_blocks"),
                "db_accuracy_passed": safe_result.get("db_accuracy_passed"),
                "db_accuracy_basis": safe_result.get("db_accuracy_basis"),
                "mutation_detected": safe_result.get("mutation_detected"),
                "unexpected_mutation": safe_result.get("unexpected_mutation"),
            },
            result=safe_result,
            trace=trace,
            trace_path=str(trace_path)
            if trace_path
            else str(safe_result.get("trace_artifact_path", "")),
        )

    def _resolve_trace_path(
        self, result: Dict[str, Any], report_path: Path
    ) -> Optional[Path]:
        raw_path = result.get("trace_artifact_path")
        if not raw_path:
            return None
        candidate = Path(str(raw_path)).expanduser()
        if candidate.exists():
            return candidate
        relative_to_report = (report_path.parent / candidate).resolve()
        if relative_to_report.exists():
            return relative_to_report
        return None

    def _read_trace(self, path: Path) -> Dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if self.redact:
            payload = self._redact_payload(payload)
        if isinstance(payload, dict):
            payload["timeline"] = self._build_timeline(payload)
        return payload if isinstance(payload, dict) else {}

    def _build_timeline(self, trace: Dict[str, Any]) -> list[Dict[str, Any]]:
        timeline: list[Dict[str, Any]] = []
        for index, message in enumerate(trace.get("messages", [])):
            timeline.append(
                {
                    "index": len(timeline),
                    "source": "message",
                    "label": message.get("role", "message"),
                    "status": "ok",
                    "detail": {
                        "content": message.get("content"),
                        "name": message.get("name"),
                        "created_at": message.get("created_at"),
                        "message_index": index,
                    },
                }
            )
        for index, step in enumerate(trace.get("steps", [])):
            timeline.append(
                {
                    "index": len(timeline),
                    "source": "step",
                    "label": step.get("node", "step"),
                    "status": step.get("status", "ok"),
                    "detail": step.get("detail", {}),
                    "step_index": index,
                }
            )
        for index, call in enumerate(trace.get("tool_calls", [])):
            timeline.append(
                {
                    "index": len(timeline),
                    "source": "tool_call",
                    "label": call.get("tool_name", "tool_call"),
                    "status": call.get("status", "unknown"),
                    "detail": call,
                    "tool_call_index": index,
                }
            )
        for index, check in enumerate(trace.get("policy_checks", [])):
            timeline.append(
                {
                    "index": len(timeline),
                    "source": "policy_check",
                    "label": check.get("decision", "policy_check"),
                    "status": "ok",
                    "detail": check,
                    "policy_check_index": index,
                }
            )
        for index, entry in enumerate(trace.get("write_audit_logs", [])):
            timeline.append(
                {
                    "index": len(timeline),
                    "source": "write_audit",
                    "label": entry.get("action_name") or entry.get("action") or "write_audit",
                    "status": "ok",
                    "detail": entry,
                    "write_audit_index": index,
                }
            )
        return timeline

    def _redact_payload(self, payload: Any, *, key: str = "") -> Any:
        if self._is_sensitive_key(key):
            if payload is None:
                return None
            return f"[redacted-{key}]"
        if isinstance(payload, dict):
            return {
                item_key: self._redact_payload(value, key=str(item_key))
                for item_key, value in payload.items()
            }
        if isinstance(payload, list):
            return [self._redact_payload(item, key=key) for item in payload]
        if isinstance(payload, str):
            value = EMAIL_RE.sub("[redacted-email]", payload)
            value = PHONE_RE.sub("[redacted-phone]", value)
            return value
        return payload

    def _is_sensitive_key(self, key: str) -> bool:
        normalized = key.lower().replace("-", "_")
        return any(part in normalized for part in SENSITIVE_KEYS)


def build_dashboard_data(
    report: Dict[str, Any], report_path: Path, *, redact: bool = True
) -> Dict[str, Any]:
    return DashboardBuilder(redact=redact).build(report, report_path)


def render_dashboard_html(data: Dict[str, Any]) -> str:
    return DashboardBuilder().render_html(data)


DASHBOARD_TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Phase 3 Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --panel-alt: #eef2f7;
      --text: #15202b;
      --muted: #52616f;
      --line: #d6dee8;
      --accent: #1d4ed8;
      --accent-soft: #dbeafe;
      --good: #0f766e;
      --bad: #b91c1c;
      --warn: #b45309;
      --shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
    }
    * { box-sizing: border-box; }
    body { margin: 0; font: 14px/1.45 system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }
    header { padding: 20px 24px 12px; border-bottom: 1px solid var(--line); background: #fff; position: sticky; top: 0; z-index: 2; }
    h1, h2, h3 { margin: 0; }
    h1 { font-size: 20px; }
    h2 { font-size: 15px; }
    h3 { font-size: 14px; }
    .subtle { color: var(--muted); font-size: 12px; }
    main { padding: 20px 24px 32px; display: grid; gap: 16px; }
    .summary { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
    .metric { background: var(--panel); border: 1px solid var(--line); box-shadow: var(--shadow); padding: 14px; border-radius: 8px; min-height: 80px; }
    .metric label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    .metric strong { display: block; font-size: 20px; }
    .layout { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 16px; align-items: start; }
    .panel { background: var(--panel); border: 1px solid var(--line); box-shadow: var(--shadow); border-radius: 8px; overflow: hidden; }
    .panel > .panel-head { padding: 12px 14px; border-bottom: 1px solid var(--line); background: var(--panel-alt); display: flex; gap: 8px; align-items: center; justify-content: space-between; }
    .panel > .panel-body { padding: 14px; }
    .filters { display: grid; gap: 10px; }
    .filters input, .filters select { width: 100%; border: 1px solid var(--line); border-radius: 6px; padding: 9px 10px; font: inherit; background: #fff; }
    .case-list { display: grid; gap: 8px; max-height: 72vh; overflow: auto; }
    .case-item { display: grid; gap: 4px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 6px; background: #fff; cursor: pointer; }
    .case-item[data-active="true"] { border-color: var(--accent); background: var(--accent-soft); }
    .case-item .title { display: flex; gap: 8px; align-items: center; justify-content: space-between; }
    .badge { display: inline-flex; align-items: center; gap: 6px; padding: 2px 8px; border-radius: 999px; font-size: 12px; background: var(--panel-alt); color: var(--muted); }
    .badge.good { background: #dcfce7; color: var(--good); }
    .badge.bad { background: #fee2e2; color: var(--bad); }
    .detail { display: grid; gap: 14px; }
    .detail-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
    .kv { border: 1px solid var(--line); border-radius: 6px; padding: 10px; background: #fff; }
    .kv span { display: block; color: var(--muted); font-size: 11px; margin-bottom: 4px; }
    .kv strong { display: block; font-size: 13px; word-break: break-word; }
    pre { margin: 0; padding: 12px; overflow: auto; background: #0f172a; color: #e2e8f0; border-radius: 6px; font-size: 12px; line-height: 1.5; }
    .stack { display: grid; gap: 10px; }
    .chips { display: flex; gap: 8px; flex-wrap: wrap; }
    .timeline { display: grid; gap: 8px; }
    .timeline-item { border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; background: #fff; }
    .timeline-item .meta { color: var(--muted); font-size: 12px; margin-bottom: 4px; }
    .muted { color: var(--muted); }
    @media (max-width: 1100px) { .summary { grid-template-columns: repeat(3, minmax(0, 1fr)); } .layout { grid-template-columns: 1fr; } .detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 720px) { header, main { padding-left: 14px; padding-right: 14px; } .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } .detail-grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>Phase 3 Dashboard</h1>
    <div class="subtle" id="run-meta"></div>
  </header>
  <main>
    <section class="summary" id="metrics"></section>
    <section class="layout">
      <aside class="panel">
        <div class="panel-head"><h2>Cases</h2><span class="subtle" id="case-count"></span></div>
        <div class="panel-body stack">
          <div class="filters">
            <input id="search" type="search" placeholder="Search case, label, category" />
            <select id="status">
              <option value="all">All statuses</option>
              <option value="pass">Pass</option>
              <option value="fail">Fail</option>
            </select>
            <select id="category"></select>
          </div>
          <div class="chips" id="failure-counts"></div>
          <div class="case-list" id="case-list"></div>
        </div>
      </aside>
      <section class="panel">
        <div class="panel-head"><h2 id="detail-title">Case detail</h2><span class="subtle" id="detail-status"></span></div>
        <div class="panel-body detail" id="detail"></div>
      </section>
    </section>
  </main>
  <script id="dashboard-data" type="application/json">__DASHBOARD_DATA__</script>
  <script>
    const data = JSON.parse(document.getElementById('dashboard-data').textContent);
    const state = { selected: 0, search: '', status: 'all', category: 'all' };
    const cases = data.cases || [];

    const metricsEl = document.getElementById('metrics');
    const listEl = document.getElementById('case-list');
    const detailEl = document.getElementById('detail');
    const searchEl = document.getElementById('search');
    const statusEl = document.getElementById('status');
    const categoryEl = document.getElementById('category');
    const titleEl = document.getElementById('detail-title');
    const detailStatusEl = document.getElementById('detail-status');
    const caseCountEl = document.getElementById('case-count');
    const failureCountsEl = document.getElementById('failure-counts');
    const runMetaEl = document.getElementById('run-meta');

    runMetaEl.textContent = [data.report.eval_run_id, data.report.model, data.report.code_commit].filter(Boolean).join(' - ');

    const metricLabels = [
      ['pass_1', 'pass^1'],
      ['pass_k', 'pass^k'],
      ['db_accuracy', 'db accuracy'],
      ['tool_call_success_rate', 'tool success'],
      ['guard_block_rate', 'guard block'],
      ['mutation_error_rate', 'mutation error'],
    ];
    metricsEl.innerHTML = metricLabels.map(([key, label]) => `
      <div class="metric">
        <label>${escapeHtml(label)}</label>
        <strong>${formatMetric(data.report.metrics?.[key])}</strong>
      </div>
    `).join('');

    failureCountsEl.innerHTML = Object.entries(data.report.failure_counts || {}).map(([label, count]) => `
      <span class="badge">${escapeHtml(label)}: ${count}</span>
    `).join('') || '<span class="subtle">No failures</span>';

    const categories = ['all', ...new Set(cases.map(item => item.category))];
    categoryEl.innerHTML = categories.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value === 'all' ? 'All categories' : value)}</option>`).join('');

    searchEl.addEventListener('input', () => { state.search = searchEl.value.toLowerCase(); renderList(); });
    statusEl.addEventListener('change', () => { state.status = statusEl.value; renderList(); });
    categoryEl.addEventListener('change', () => { state.category = categoryEl.value; renderList(); });

    function visibleCases() {
      return cases.filter(item => {
        const matchSearch = !state.search || [item.case_id, item.category, item.failure_label, item.failure_summary].filter(Boolean).join(' ').toLowerCase().includes(state.search);
        const matchStatus = state.status === 'all' || (state.status === 'pass' ? item.passed : !item.passed);
        const matchCategory = state.category === 'all' || item.category === state.category;
        return matchSearch && matchStatus && matchCategory;
      });
    }

    function renderList() {
      const visible = visibleCases();
      caseCountEl.textContent = `${visible.length} / ${cases.length} shown`;
      listEl.innerHTML = visible.map((item, index) => `
        <div class="case-item" data-index="${index}" data-active="${cases.indexOf(item) === state.selected}">
          <div class="title">
            <strong>${escapeHtml(item.case_id)}</strong>
            <span class="badge ${item.passed ? 'good' : 'bad'}">${item.passed ? 'pass' : 'fail'}</span>
          </div>
          <div class="subtle">${escapeHtml(item.category)} - trial ${item.trial} - ${item.failure_label ? escapeHtml(item.failure_label) : 'ok'}</div>
        </div>
      `).join('') || '<div class="subtle">No cases match filters.</div>';
      listEl.querySelectorAll('.case-item').forEach(node => {
        node.addEventListener('click', () => {
          const visibleIndex = Number(node.getAttribute('data-index'));
          const item = visible[visibleIndex];
          state.selected = cases.indexOf(item);
          renderList();
          renderDetail();
        });
      });
      if (!visible.length) {
        detailEl.innerHTML = '<div class="subtle">No case selected.</div>';
        titleEl.textContent = 'Case detail';
        detailStatusEl.textContent = '';
        return;
      }
      if (state.selected >= cases.length || !visible.includes(cases[state.selected])) {
        state.selected = cases.indexOf(visible[0]);
      }
      renderDetail();
    }

    function renderDetail() {
      const item = cases[state.selected];
      if (!item) return;
      titleEl.textContent = item.case_id;
      detailStatusEl.textContent = `${item.category} - ${item.passed ? 'pass' : 'fail'}`;
      const trace = item.trace || {};
      const messages = (trace.messages || []).map(msg => `
        <div class="timeline-item">
          <div class="meta">${escapeHtml(msg.role)}${msg.name ? ` - ${escapeHtml(msg.name)}` : ''} - ${escapeHtml(msg.created_at || '')}</div>
          <div>${escapeHtml(msg.content || '')}</div>
        </div>
      `).join('');
      const steps = (trace.steps || []).map(step => `
        <div class="timeline-item">
          <div class="meta">${escapeHtml(step.node)} - ${escapeHtml(step.status || 'ok')}</div>
          <div><pre>${escapeHtml(JSON.stringify(step.detail || {}, null, 2))}</pre></div>
        </div>
      `).join('');
      const toolCalls = (trace.tool_calls || []).map(call => `
        <div class="timeline-item">
          <div class="meta">${escapeHtml(call.tool_name)} - ${escapeHtml(call.status || '')}</div>
          <div><pre>${escapeHtml(JSON.stringify(call, null, 2))}</pre></div>
        </div>
      `).join('');
      const policyChecks = (trace.policy_checks || []).map(check => `
        <div class="timeline-item">
          <div class="meta">policy check</div>
          <div><pre>${escapeHtml(JSON.stringify(check, null, 2))}</pre></div>
        </div>
      `).join('');
      const writeLogs = (trace.write_audit_logs || []).map(entry => `
        <div class="timeline-item">
          <div class="meta">write audit</div>
          <div><pre>${escapeHtml(JSON.stringify(entry, null, 2))}</pre></div>
        </div>
      `).join('');
      const timeline = (trace.timeline || []).map(entry => `
        <div class="timeline-item">
          <div class="meta">#${entry.index} - ${escapeHtml(entry.source)} - ${escapeHtml(entry.status || '')}</div>
          <strong>${escapeHtml(entry.label || '')}</strong>
          <div><pre>${escapeHtml(JSON.stringify(entry.detail || {}, null, 2))}</pre></div>
        </div>
      `).join('');

      detailEl.innerHTML = `
        <div class="detail-grid">
          ${kv('Trial', item.trial)}
          ${kv('Passed', item.passed ? 'yes' : 'no')}
          ${kv('Failure', item.failure_label || 'ok')}
          ${kv('Duration', `${item.duration_seconds}s`)}
          ${kv('Intent', item.result?.final_intent || 'unknown')}
          ${kv('Auth user', item.result?.authenticated_user_id || 'unknown')}
          ${kv('Trace path', item.trace_path || item.trace_artifact_path || 'unknown')}
          ${kv('Replay task', item.replay_metadata?.task_id || 'unknown')}
        </div>
        <div class="panel">
          <div class="panel-head"><h3>Summary</h3></div>
          <div class="panel-body"><div class="muted">${escapeHtml(item.failure_summary || 'passed')}</div></div>
        </div>
        <div class="panel">
          <div class="panel-head"><h3>Final State</h3></div>
          <div class="panel-body"><pre>${escapeHtml(JSON.stringify(item.trace?.final_state || {}, null, 2))}</pre></div>
        </div>
        <div class="panel">
          <div class="panel-head"><h3>Trace Timeline</h3></div>
          <div class="panel-body timeline">${timeline || '<div class="subtle">No timeline events.</div>'}</div>
        </div>
        <div class="panel">
          <div class="panel-head"><h3>Messages</h3></div>
          <div class="panel-body timeline">${messages || '<div class="subtle">No messages.</div>'}</div>
        </div>
        <div class="panel">
          <div class="panel-head"><h3>Steps</h3></div>
          <div class="panel-body timeline">${steps || '<div class="subtle">No steps.</div>'}</div>
        </div>
        <div class="panel">
          <div class="panel-head"><h3>Tool Calls</h3></div>
          <div class="panel-body timeline">${toolCalls || '<div class="subtle">No tool calls.</div>'}</div>
        </div>
        <div class="panel">
          <div class="panel-head"><h3>Policy Checks</h3></div>
          <div class="panel-body timeline">${policyChecks || '<div class="subtle">No policy checks.</div>'}</div>
        </div>
        <div class="panel">
          <div class="panel-head"><h3>Write Audit</h3></div>
          <div class="panel-body timeline">${writeLogs || '<div class="subtle">No write audit logs.</div>'}</div>
        </div>
      `;
    }

    function kv(label, value) {
      return `<div class="kv"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value ?? ''))}</strong></div>`;
    }

    function formatMetric(value) {
      if (typeof value === 'number') return value.toFixed(4);
      return value == null ? 'n/a' : String(value);
    }

    function escapeHtml(text) {
      return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    renderList();
  </script>
</body>
</html>
'''
