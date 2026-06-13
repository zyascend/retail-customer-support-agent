from __future__ import annotations

from typing import Any

from app.agent.models import SessionState


class ContextBuilder:
    """Builds a compressed LLM-visible state summary from SessionState.

    Target budget: ~1200 tokens. Provides the LLM with context needed for
    tool-calling decisions without overwhelming the prompt with raw DB objects.
    """

    def __init__(self, *, policy_text: str, max_recent_messages: int = 6) -> None:
        self._policy_text = policy_text
        self._max_recent_messages = max_recent_messages

    def build(self, session: SessionState) -> str:
        parts: list[str] = [self._auth_summary(session)]
        if session.loaded_context.orders:
            parts.append(self._orders_summary(session))
        if session.pending_action:
            parts.append(self._pending_summary(session))
        if session.write_locks:
            parts.append(self._locks_summary(session))
        if session.tool_results:
            parts.append(self._tool_results_summary(session))
        if session.messages:
            parts.append(self._messages_summary(session))
        parts.append(self._policy_summary())
        return "\n\n".join(parts)

    def estimate_tokens(self, text: str) -> int:
        return max(1, int(len(text.split()) / 0.75))

    # ── Private helpers ──

    def _auth_summary(self, session: SessionState) -> str:
        if not session.authenticated_user_id:
            return "## Session\nUser: not authenticated"
        identity = session.active_user_identity
        name = identity.get("name", "Unknown")
        email = str(identity.get("email", ""))
        lines = [
            "## Session",
            f"User: {name} (ID: {session.authenticated_user_id})",
            f"Auth: {session.auth_method or 'unknown'}",
        ]
        if email and "@" in email:
            lines.append(f"Email domain: {email.split('@')[1]}")
        return "\n".join(lines)

    def _orders_summary(self, session: SessionState) -> str:
        lines = ["## Loaded Orders"]
        for oid, order in session.loaded_context.orders.items():
            status = order.get("status", "unknown")
            items = order.get("items", [])
            count = len(items) if isinstance(items, list) else 0
            owner = order.get("user_id", "")
            flags = ""
            if status == "pending" and owner == session.authenticated_user_id:
                flags = " [writable]"
            lines.append(f"- {oid}: {status}, {count} items{flags}")
        return "\n".join(lines)

    def _pending_summary(self, session: SessionState) -> str:
        pa = session.pending_action
        return (
            "## Pending Action\n"
            f"Action: {pa.action_name}\n"
            f"Arguments: {self._brief_args(pa.arguments)}\n"
            f"Summary: {pa.user_facing_summary}"
        )

    def _locks_summary(self, session: SessionState) -> str:
        return "## Write Locks\n" + "\n".join(f"- {lk}" for lk in session.write_locks)

    def _tool_results_summary(self, session: SessionState) -> str:
        recent = session.tool_results[-3:]
        lines = ["## Recent Tool Calls"]
        for r in recent:
            obs = self._summarize_observation(r.observation)
            lines.append(f"- {r.tool_name}: {r.status} — {obs}")
        return "\n".join(lines)

    def _messages_summary(self, session: SessionState) -> str:
        recent = session.messages[-self._max_recent_messages :]
        lines = ["## Recent Messages"]
        for msg in recent:
            lines.append(f"- [{msg.role}] {msg.content[:200]}")
        return "\n".join(lines)

    def _policy_summary(self) -> str:
        return f"## Policy\n{self._policy_text[:500].strip()}"

    @staticmethod
    def _brief_args(args: dict[str, Any]) -> str:
        parts = []
        for k, v in args.items():
            s = str(v)
            parts.append(f"{k}={s[:37] + '...' if len(s) > 40 else s}")
        return ", ".join(parts)

    @staticmethod
    def _summarize_observation(obs: Any) -> str:
        if obs is None:
            return "(none)"
        if isinstance(obs, dict):
            fields = []
            for f in ("order_id", "status", "user_id", "item_count", "name", "email"):
                if f in obs:
                    fields.append(f"{f}={obs[f]}")
            return ", ".join(fields[:4]) if fields else f"dict({len(obs)} keys)"
        if isinstance(obs, list):
            return f"list({len(obs)} items)"
        s = str(obs)
        return s[:77] + "..." if len(s) > 80 else s
