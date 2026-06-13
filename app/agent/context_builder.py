from __future__ import annotations

from app.agent.models import SessionState


class ContextBuilder:
    """Builds a compressed LLM-visible state summary from SessionState.

    Target budget: ~1200 tokens. Provides the LLM with context needed for
    tool-calling decisions without overwhelming the prompt with raw DB objects.
    """

    def __init__(self, *, policy_text: str, max_recent_messages: int = 6) -> None:
        self._policy_text = policy_text
        self._max_recent_messages = max_recent_messages

    @property
    def policy_text(self) -> str:
        return self._policy_text

    def build(self, session: SessionState) -> str:  # noqa: C901
        parts: list[str] = []

        if session.authenticated_user_id:
            user_line = f"User: user_id={session.authenticated_user_id}"
            if session.auth_method:
                user_line += f" ({session.auth_method})"
            parts.append(user_line)

        if session.loaded_context.orders:
            order_parts = []
            for oid, order in session.loaded_context.orders.items():
                status = order.get("status", "?")
                items = order.get("items", [])
                item_count = len(items) if isinstance(items, list) else 0
                order_parts.append(f"#{oid}={status} ({item_count} items)")
            parts.append("Orders: " + ", ".join(order_parts))

        if session.pending_action:
            parts.append(
                f"Pending: {session.pending_action.action_name} "
                f"— waiting for user confirmation"
            )

        if session.write_locks:
            parts.append(f"Locks: {', '.join(session.write_locks)}")

        return "\n".join(parts)

    def estimate_tokens(self, text: str) -> int:
        return max(1, int(len(text.split()) / 0.75))
