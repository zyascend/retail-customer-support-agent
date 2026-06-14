import type { TimelineEvent, WorkbenchMode } from "./types";

const MODE_LABELS: Record<WorkbenchMode, string> = {
  offline_demo: "离线演示",
  llm: "LLM 模式",
};

const STATUS_LABELS: Record<string, string> = {
  ok: "正常",
  success: "成功",
  complete: "完成",
  completed: "完成",
  passed: "通过",
  blocked: "已阻止",
  warning: "警告",
  pending: "待处理",
  skipped: "已跳过",
  error: "错误",
  failed: "失败",
  failure: "失败",
  required: "需要确认",
  confirmed: "已确认",
  denied: "已拒绝",
  changed: "已变更",
  not_required: "无需确认",
  unknown: "未知",
};

const ROLE_LABELS: Record<string, string> = {
  user: "用户",
  assistant: "助手",
  tool: "工具",
  system: "系统",
};

const TIMELINE_KIND_LABELS: Record<TimelineEvent["kind"], string> = {
  message: "消息",
  step: "步骤",
  tool_call: "工具调用",
  write_audit: "写入审计",
};

const INTENT_LABELS: Record<string, string> = {
  lookup: "查询订单",
  cancel_order: "取消订单",
  modify_order_address: "修改地址",
  return_items: "退货",
  exchange_items: "换货",
  transfer: "转人工",
  unknown: "未知",
};

const ACTION_LABELS: Record<string, string> = {
  cancel_pending_order: "取消待处理订单",
  modify_pending_order_address: "修改待处理订单地址",
  return_delivered_order_items: "退回已送达商品",
  exchange_delivered_order_items: "换货已送达商品",
  transfer_to_human_agents: "转接人工客服",
  context_loader: "上下文加载",
  offline_demo_intent: "离线演示意图",
};

const EVENT_LABELS: Record<string, string> = {
  receive_message: "接收消息",
  preflight_identity: "预检身份",
  provider_unavailable: "Provider 不可用",
  offline_demo_harness: "离线演示",
  offline_demo_intent: "离线演示意图",
  conversation_gate: "会话确认",
  tool_executor: "工具执行",
  identity_resolver: "身份识别",
  intent_and_slot_extractor: "意图和槽位提取",
  context_loader: "上下文加载",
  policy_reasoner: "策略判断",
  action_planner: "动作规划",
  write_action_guard: "写入保护",
  observation_reducer: "结果归纳",
  response_generator: "回复生成",
  run_logger: "运行记录",
  runtime_error: "运行错误",
  find_user_id_by_email: "按邮箱查找用户",
  get_user_details: "获取用户详情",
  get_order_details: "获取订单详情",
  cancel_pending_order: "取消待处理订单",
  modify_pending_order_address: "修改待处理订单地址",
  return_delivered_order_items: "退回已送达商品",
  exchange_delivered_order_items: "换货已送达商品",
  transfer_to_human_agents: "转接人工客服",
};

const ERROR_LABELS: Record<string, string> = {
  runtime_error: "运行出错",
  session_not_found: "会话不存在",
  case_not_found: "案例不存在",
  invalid_mode: "模式不支持",
  llm_unavailable: "LLM 不可用",
  case_required: "请先选择案例",
  script_complete: "脚本已完成",
  empty_message: "请输入消息内容",
};

export function modeLabel(mode: WorkbenchMode | string | null | undefined): string {
  if (!mode) {
    return "加载中";
  }
  return MODE_LABELS[mode as WorkbenchMode] || mode;
}

export function statusLabel(status: string | null | undefined): string {
  if (!status) {
    return "未知";
  }
  return STATUS_LABELS[status.toLowerCase()] || status;
}

export function roleLabel(role: string | null | undefined): string {
  if (!role) {
    return "未知角色";
  }
  return ROLE_LABELS[role.toLowerCase()] || role;
}

export function timelineKindLabel(kind: TimelineEvent["kind"]): string {
  return TIMELINE_KIND_LABELS[kind] || kind;
}

export function intentLabel(intent: string | null | undefined): string {
  if (!intent) {
    return "未知";
  }
  return INTENT_LABELS[intent] || intent;
}

export function actionLabel(action: string | null | undefined): string {
  if (!action) {
    return "待处理动作";
  }
  return ACTION_LABELS[action] || action;
}

export function eventLabel(label: string | null | undefined): string {
  if (!label) {
    return "未命名事件";
  }
  return EVENT_LABELS[label] || ROLE_LABELS[label] || label;
}

export function errorLabel(code: string | null | undefined): string {
  if (!code) {
    return "请求失败";
  }
  return ERROR_LABELS[code] || code;
}

const GROUP_LABELS: Record<string, string> = {
  auth: "身份认证",
  success: "成功写操作",
  blocked: "写保护阻止",
  confirmation: "用户确认流程",
  transfer: "边界能力",
};

export function groupLabel(key: string): string {
  return GROUP_LABELS[key] || key;
}

export function weightLabel(weight: "primary" | "secondary"): string {
  return weight === "primary" ? "关键" : "辅助";
}
