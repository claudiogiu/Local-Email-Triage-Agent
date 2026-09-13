import logging

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.domain.ports import MailProvider
from src.graph.nodes import (
    classify_node,
    decide_actions_node,
    draft_reply_node,
    gate_draft_node,
    gate_labels_node,
    gate_next_action_node,
    gate_send_node,
    ingest_node,
    make_execute_node,
    normalize_node,
    persist_node,
    prepare_send_node,
    prioritize_node,
)
from src.graph.state import TriageGraphState

logger = logging.getLogger(__name__)


def _route_after_next_action(state: TriageGraphState) -> str:
    if state.get("status") == "FAILED":
        return "execute"
    if state.get("next_action") == "reply":
        return "draft_reply"
    return "execute"


def _route_after_gate_draft(state: TriageGraphState) -> str:
    if state.get("status") == "DRAFT_APPROVED":
        return "gate_send"
    return "execute"


def build_graph(provider: MailProvider, checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    logger.info("Starting triage graph construction.")
    builder = StateGraph(TriageGraphState)
    builder.add_node("ingest", ingest_node)
    builder.add_node("normalize", normalize_node)
    builder.add_node("classify", classify_node)
    builder.add_node("prioritize", prioritize_node)
    builder.add_node("decide_actions", decide_actions_node)
    builder.add_node("gate_labels", gate_labels_node)
    builder.add_node("gate_next_action", gate_next_action_node)
    builder.add_node("draft_reply", draft_reply_node)
    builder.add_node("gate_draft", gate_draft_node)
    builder.add_node("prepare_send", prepare_send_node)
    builder.add_node("gate_send", gate_send_node)
    builder.add_node("execute", make_execute_node(provider))
    builder.add_node("persist", persist_node)

    builder.add_edge(START, "ingest")
    builder.add_edge("ingest", "normalize")
    builder.add_edge("normalize", "classify")
    builder.add_edge("classify", "prioritize")
    builder.add_edge("prioritize", "decide_actions")
    builder.add_edge("decide_actions", "gate_labels")
    builder.add_edge("gate_labels", "gate_next_action")
    builder.add_conditional_edges(
        "gate_next_action", _route_after_next_action, {"draft_reply": "draft_reply", "execute": "execute"}
    )
    builder.add_edge("draft_reply", "gate_draft")
    builder.add_conditional_edges(
        "gate_draft", _route_after_gate_draft, {"gate_send": "prepare_send", "execute": "execute"}
    )
    builder.add_edge("prepare_send", "gate_send")
    builder.add_edge("gate_send", "execute")
    builder.add_edge("execute", "persist")
    builder.add_edge("persist", END)

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("Triage graph construction successfully completed.")
    return graph
