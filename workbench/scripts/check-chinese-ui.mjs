import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;

const files = [
  "src/App.tsx",
  "src/components/BusinessState.tsx",
  "src/components/Conversation.tsx",
  "src/components/Inspector.tsx",
  "src/components/RunControl.tsx",
  "src/components/StatusBadge.tsx",
  "src/components/Timeline.tsx",
  "src/api.ts",
].map((file) => join(root, file));

const forbidden = new Set([
  "Business State",
  "Case",
  "Case list scope",
  "Change",
  "Confirm",
  "Context",
  "Conversation",
  "DB ",
  "Demo",
  "Deny",
  "Deterministic",
  "Event Detail",
  "Event Details",
  "Events",
  "Guard Blocks",
  "Inspector",
  "Loading case",
  "Loading workbench...",
  "Manual user message",
  "Mode",
  "No messages yet.",
  "No pending action.",
  "No summary available",
  "No timeline events yet.",
  "Order",
  "Pending Action",
  "Reset",
  "Retail Agent Workbench",
  "Run Control",
  "Run all",
  "Selected event",
  "Send",
  "Session",
  "Single-session Phase 4 operations dashboard",
  "Slots",
  "Step",
  "Trace",
  "Transcript",
  "Type a customer reply...",
  "Unauthenticated",
  "User",
  "Workbench dashboard",
  "Workbench request failed",
  "Failed to parse JSON response",
  "Request failed:",
  "unknown",
]);

const stringLiteralPattern = /(?<quote>["'`])(?<value>(?:\\.|(?!\k<quote>).)*)\k<quote>/g;

const violations = [];
for (const file of files) {
  const text = readFileSync(file, "utf8");
  for (const match of text.matchAll(stringLiteralPattern)) {
    const value = match.groups.value;
    if (forbidden.has(value)) {
      violations.push(`${file}: ${value}`);
    }
  }
}

if (violations.length) {
  console.error(violations.join("\n"));
  process.exit(1);
}
