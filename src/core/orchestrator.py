import logging
from typing import Any, Optional

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from src.config.constants import CHECKPOINT_PATH
from src.domain.ports import MailProvider
from src.graph.builder import build_graph
from src.providers.factory import MailProviderFactory

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Interface for compiling the triage graph once per process, invoking a new
    run, and resuming a run suspended at a human approval gate. A run is
    identified by its Message-ID, used as the LangGraph thread_id, per
    ADR-0002. The checkpointer persists every suspended run to SQLite, so a
    process restart does not lose a pending approval.

    Attributes:
        provider (MailProvider): Mail provider bound to the compiled graph's execute node.
        _graph (CompiledStateGraph): The compiled, invocable triage graph.
        _connection (aiosqlite.Connection): Underlying SQLite connection backing the checkpointer.

    Methods:
        close() -> None:
            Releases the underlying checkpointer database connection.

        start_run(message_id: str) -> None:
            Invokes the triage graph for the supplied message from the beginning.

        resume_run(message_id: str, decision: Any) -> None:
            Resumes a run suspended at a human approval gate with the supplied decision.
    """

    def __init__(self, provider: MailProvider, graph: CompiledStateGraph, connection: aiosqlite.Connection) -> None:
        self.provider: MailProvider = provider
        self._graph: CompiledStateGraph = graph
        self._connection: aiosqlite.Connection = connection
        logger.info("Orchestrator initialization completed.")

    @classmethod
    async def create(cls, provider: Optional[MailProvider] = None) -> "Orchestrator":
        if not CHECKPOINT_PATH:
            raise ValueError("The CHECKPOINT_PATH environment variable is not configured.")
        resolved_provider = provider or MailProviderFactory.create()
        connection = await aiosqlite.connect(CHECKPOINT_PATH)
        checkpointer = AsyncSqliteSaver(connection)
        await checkpointer.setup()
        graph = build_graph(resolved_provider, checkpointer)
        return cls(resolved_provider, graph, connection)

    async def close(self) -> None:
        await self._connection.close()
        logger.info("Orchestrator checkpointer connection closed.")

    async def start_run(self, message_id: str) -> None:
        logger.info(f"Starting triage run. Message ID: {message_id}.")
        await self._graph.ainvoke(
            {
                "run_id": message_id,
                "message_id": message_id,
                "normalized_subject": None,
                "normalized_body": None,
                "classification_label": None,
                "priority_level": None,
                "requires_reply": None,
                "next_action": None,
                "proposed_action_ids": [],
                "draft_action_id": None,
                "draft_feedback": None,
                "send_action_id": None,
                "status": "STARTED",
                "error": None,
            },
            config={"configurable": {"thread_id": message_id}},
        )
        logger.info("Triage run successfully completed or suspended at a gate.")

    async def resume_run(self, message_id: str, decision: Any) -> None:
        logger.info(f"Starting triage run resume. Message ID: {message_id}.")
        await self._graph.ainvoke(
            Command(resume=decision),
            config={"configurable": {"thread_id": message_id}},
        )
        logger.info("Triage run resume successfully completed.")


_orchestrator: Optional[Orchestrator] = None


async def get_orchestrator() -> Orchestrator:
    """Return the process-wide orchestrator instance, initializing it on first access."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = await Orchestrator.create()
    return _orchestrator


async def reset_orchestrator() -> None:
    """Close and discard the process-wide orchestrator, so the next access rebuilds it from current credentials."""
    global _orchestrator
    if _orchestrator is not None:
        await _orchestrator.close()
        _orchestrator = None
