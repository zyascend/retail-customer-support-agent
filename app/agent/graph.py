from __future__ import annotations

from typing import Any, Callable, Dict, Iterable

PHASE1_NODES = (
    "receive_message",
    "conversation_gate",
    "identity_resolver",
    "intent_and_slot_extractor",
    "context_loader",
    "policy_reasoner",
    "action_planner",
    "write_action_guard",
    "tool_executor",
    "observation_reducer",
    "response_generator",
    "run_logger",
)


def build_linear_graph(node_fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Any:
    """Build the Phase 1 LangGraph shell.

    Runtime logic remains deterministic and testable in node methods; this graph
    preserves the intended node boundary and can be expanded without changing the
    CLI surface.
    """
    try:
        from langgraph.graph import END, StateGraph
    except Exception:
        return None

    graph = StateGraph(dict)
    for node in PHASE1_NODES:
        graph.add_node(node, _wrap(node, node_fn))
    graph.set_entry_point(PHASE1_NODES[0])
    for current, next_node in _pairs(PHASE1_NODES):
        graph.add_edge(current, next_node)
    graph.add_edge(PHASE1_NODES[-1], END)
    return graph.compile()


def _wrap(
    node_name: str, node_fn: Callable[[Dict[str, Any]], Dict[str, Any]]
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def run(payload: Dict[str, Any]) -> Dict[str, Any]:
        payload["current_node"] = node_name
        return node_fn(payload)

    return run


def _pairs(items: Iterable[str]) -> Iterable[tuple[str, str]]:
    sequence = list(items)
    return zip(sequence, sequence[1:])

