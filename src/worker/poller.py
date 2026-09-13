import asyncio
import hashlib
import logging
import uuid
from typing import Awaitable, Callable, List, Optional

from src.domain.entities import MessageRef, MessageStatus
from src.domain.ports import MailProvider
from src.persistence.models import EmailMessageModel
from src.persistence.repositories import EmailMessageRepository
from src.worker.watermark import WatermarkService

logger = logging.getLogger(__name__)

RunStarter = Callable[[str], Awaitable[None]]


async def default_run_starter(message_id: str) -> None:
    logger.info(f"Run start requested with no orchestrator wired yet. Message ID: {message_id}.")


class Poller:
    """
    Interface for discovering newly arrived messages across configured
    folders, deduplicating them against persisted state, and starting one
    triage run per message with inference concurrency limited to one.

    Attributes:
        _provider (MailProvider): Mail provider used for message discovery and retrieval.
        _watermark_service (WatermarkService): Component resolving watermark-qualified candidates.
        _repository (EmailMessageRepository): Persistence access point for message snapshots.
        _run_starter (RunStarter): Callable invoked once per newly discovered message to start its run.
        _inference_semaphore (asyncio.Semaphore): Concurrency guard limiting simultaneous run starts to one.

    Methods:
        _process_candidate(ref: MessageRef) -> Optional[str]:
            Fetches, deduplicates, persists, and starts a run for a single candidate.

        poll_once(account_id: str, folders: List[str]) -> List[str]:
            Discovers, deduplicates, and starts a run for every newly qualified candidate.
    """

    def __init__(
        self,
        provider: MailProvider,
        watermark_service: Optional[WatermarkService] = None,
        repository: Optional[EmailMessageRepository] = None,
        run_starter: Optional[RunStarter] = None,
    ) -> None:
        self._provider: MailProvider = provider
        self._watermark_service: WatermarkService = watermark_service or WatermarkService()
        self._repository: EmailMessageRepository = repository or EmailMessageRepository()
        self._run_starter: RunStarter = run_starter or default_run_starter
        self._inference_semaphore = asyncio.Semaphore(1)

    def _process_candidate(self, ref: MessageRef) -> Optional[EmailMessageModel]:
        raw = self._provider.fetch(ref)
        if raw.ref.message_id and self._repository.get_by_message_id(raw.ref.message_id) is not None:
            logger.info("Candidate skipped: already persisted, deduplicated on Message-ID.")
            return None

        message_id = raw.ref.message_id or str(uuid.uuid4())
        snapshot = EmailMessageModel(
            id=str(uuid.uuid4()),
            account_id=ref.account_id,
            message_id=message_id,
            thread_id=None,
            folder=ref.folder,
            uid=ref.uid,
            sender=raw.sender,
            recipients=raw.recipients,
            cc_recipients=raw.cc_recipients,
            subject=raw.subject,
            body=raw.body,
            received_at=raw.received_at,
            flags=[],
            headers=raw.headers,
            content_hash=hashlib.sha256(raw.body.encode("utf-8")).hexdigest(),
            status=MessageStatus.DISCOVERED,
        )
        return self._repository.add(snapshot)

    async def poll_once(self, account_id: str, folders: List[str]) -> List[str]:
        started: List[str] = []
        for folder in folders:
            candidates = self._watermark_service.resolve_candidates(self._provider, account_id, folder)
            logger.info(f"Starting candidate processing. Folder: {folder}. Candidates: {len(candidates)}.")
            for ref in candidates:
                snapshot = self._process_candidate(ref)
                if snapshot is None:
                    continue
                async with self._inference_semaphore:
                    await self._run_starter(snapshot.message_id)
                started.append(snapshot.message_id)
        logger.info(f"Polling cycle successfully completed. Runs started: {len(started)}.")
        return started
