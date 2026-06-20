import React from "react";
import { StatusBadge } from "./StatusBadge";
import { CardHeader, InfoRow, statusLabel, statusTone, SectionBlock, KeyValueRows } from "./EventCardHelpers";
import type { TimelineEvent } from "../types";

interface StepCardProps {
  event: TimelineEvent;
}

const STEP_NODE_LABELS: Record<string, string> = {
  receive_message: "接收消息",
  preflight_identity: "预检身份",
  preflight_confirmation: "预检确认",
  intent_and_slot_extractor: "意图和槽位提取",
  policy_reasoner: "策略判断",
  write_action_guard: "写保护",
  action_planner: "动作规划",
  tool_executor: "工具执行",
  tool_execute: "工具执行",
  pending_set: "待确认操作",
  llm_reason: "LLM 推理",
  provider_unavailable: "Provider 不可用",
  consecutive_failures_limit: "连续失败",
  finalize: "结束",
  conversation_gate: "会话确认",
  context_loader: "上下文加载",
  observation_reducer: "结果归纳",
  response_generator: "回复生成",
  run_logger: "运行记录",
  runtime_error: "运行错误",
};

export function StepCard({ event }: StepCardProps) {
  const detail = event.detail as Record<string, unknown> | null;
  const nodeLabel = STEP_NODE_LABELS[event.label] || event.label;
  const status = event.status || "ok";

  const sections = detail ? getStepSections(event.label, detail) : [];

  return (
    <div className="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3">
      <CardHeader icon="⚙️" title="管道步骤" weight={event.weight} />

      <div className="grid gap-2">
        <InfoRow label="步骤" value={nodeLabel} />
        <InfoRow label="状态" value={<StatusBadge label={statusLabel(status)} tone={statusTone(status)} />} />

        {sections.map((section, i) => (
          section.entries.length > 0 ? (
            <SectionBlock key={i} title={section.title}>
              <KeyValueRows entries={section.entries} />
            </SectionBlock>
          ) : null
        ))}

        {detail && renderFallbackKeys(detail, sections)}
      </div>
    </div>
  );
}

function getStepSections(node: string, detail: Record<string, unknown>): Array<{ title: string; entries: Array<[string, unknown]> }> {
  switch (node) {
    case "receive_message":
      return [{ title: "内容", entries: Object.entries({ content: detail.content }) }];
    case "preflight_identity":
      return [{ title: "身份信息", entries: Object.entries(detail).filter(([k]) => k !== "status") }];
    case "preflight_confirmation":
      return [{ title: "确认结果", entries: [["resolution", detail.resolution]] }];
    case "intent_and_slot_extractor":
      return [{ title: "提取结果", entries: Object.entries(detail).filter(([_, v]) => v !== null && v !== undefined) }];
    case "policy_reasoner":
      return [{ title: "决策", entries: Object.entries(detail).filter(([_, v]) => v !== null && v !== undefined) }];
    case "write_action_guard":
      return [{ title: "保护判断", entries: Object.entries(detail).filter(([_, v]) => v !== null && v !== undefined) }];
    default:
      return [{ title: "详情", entries: Object.entries(detail).filter(([_, v]) => v !== null && v !== undefined) }];
  }
}

const KNOWN_KEYS = new Set(["status"]);

function renderFallbackKeys(detail: Record<string, unknown>, sections: Array<{ title: string; entries: Array<[string, unknown]> }>): React.ReactNode {
  const coveredKeys = new Set(sections.flatMap((s) => s.entries.map(([k]) => k)));
  const fallback = Object.entries(detail).filter(
    ([k, v]) => !coveredKeys.has(k) && !KNOWN_KEYS.has(k) && v !== null && v !== undefined
  );
  if (fallback.length === 0) return null;

  return (
    <SectionBlock title="其他">
      <KeyValueRows entries={fallback} />
    </SectionBlock>
  );
}