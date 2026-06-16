import { roleLabel } from "../labels";
import type { WorkbenchSnapshot } from "../types";

export function Conversation({ busy, snapshot }: { busy: boolean; snapshot: WorkbenchSnapshot }) {
  return (
    <section className="min-w-0 flex flex-col overflow-hidden border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 p-3" aria-label="对话记录">
      <div className="flex items-start justify-between gap-3 mb-3 shrink-0">
        <div>
          <div className="mb-0.5 text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">对话</div>
          <h2 className="m-0 text-base leading-tight text-[#182230] dark:text-white">消息记录</h2>
        </div>
        <span className="inline-flex items-center rounded-full bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 text-xs font-extrabold leading-none whitespace-nowrap px-2 py-1.5">
          {snapshot.messages.length}
        </span>
      </div>

      {snapshot.messages.length ? (
        <ol className="grid gap-2 m-0 p-0 list-none flex-1 overflow-auto min-h-0 content-start">
          {snapshot.messages.map((message, index) => (
            <li
              className={
                "border rounded-lg p-2.5 " +
                (message.role === "assistant"
                  ? "border-blue-100 dark:border-blue-900/40 bg-blue-50/50 dark:bg-blue-950/30"
                  : message.role === "user"
                    ? "border-green-100 dark:border-green-900/40 bg-green-50/30 dark:bg-green-950/20"
                    : "border-slate-200 dark:border-slate-700 bg-[#fbfcfe] dark:bg-slate-800/50")
              }
              key={`${index}-${message.role}`}
            >
              <div className="flex justify-between gap-2.5 mb-1.5 text-slate-500 dark:text-slate-400 text-xs font-extrabold tracking-normal">
                <span>{roleLabel(message.role)}</span>
                {message.created_at ? <time className="overflow-hidden text-ellipsis whitespace-nowrap tracking-normal">{message.created_at}</time> : null}
              </div>
              <p className="m-0 break-anywhere text-[#253044] dark:text-slate-200 text-sm">{message.content}</p>
            </li>
          ))}
        </ol>
      ) : (
        <div className="border border-dashed border-slate-300 dark:border-slate-600 rounded-lg text-slate-500 dark:text-slate-400 p-3.5 text-sm">暂无消息。</div>
      )}

      {/* Agent thinking indicator */}
      {busy && (
        <div className="shrink-0 mt-2 flex items-center gap-2 px-1 py-1.5">
          <span className="inline-flex gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: "0ms" }} />
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: "150ms" }} />
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: "300ms" }} />
          </span>
          <span className="text-xs text-slate-500 dark:text-slate-400 font-semibold">Agent 正在思考…</span>
        </div>
      )}
    </section>
  );
}
