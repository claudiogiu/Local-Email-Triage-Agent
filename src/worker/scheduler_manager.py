import asyncio
import logging
from typing import Optional

from src.config.constants import IMAP_FOLDERS, IMAP_USERNAME
from src.core.orchestrator import get_orchestrator, reset_orchestrator
from src.persistence.repositories import MailboxCredentialsRepository
from src.worker.poller import Poller
from src.worker.scheduler import Scheduler

logger = logging.getLogger(__name__)

_scheduler_task: Optional[asyncio.Task] = None


def _resolve_account_id() -> str:
    stored = MailboxCredentialsRepository().get()
    return (stored.email if stored else None) or IMAP_USERNAME or "default-account"


async def _start_scheduler() -> None:
    global _scheduler_task
    folders = IMAP_FOLDERS or ["INBOX"]
    account_id = _resolve_account_id()
    orchestrator = await get_orchestrator()
    poller = Poller(orchestrator.provider, run_starter=orchestrator.start_run)
    scheduler = Scheduler(poller)
    _scheduler_task = asyncio.create_task(scheduler.run_forever(account_id, folders))
    logger.info(f"Polling scheduler started. Account: {account_id}. Folders: {len(folders)}.")


async def start_scheduler_if_configured() -> None:
    """Start the polling scheduler if it is not already running, tolerating missing mailbox credentials."""
    if _scheduler_task is not None and not _scheduler_task.done():
        return
    try:
        await _start_scheduler()
    except Exception as e:
        logger.error(f"Polling scheduler could not be started: {e}")


async def restart_scheduler() -> None:
    """Stop any running scheduler, rebuild the orchestrator from the current credentials, and start fresh."""
    await stop_scheduler()
    await reset_orchestrator()
    await _start_scheduler()


async def stop_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is not None:
        _scheduler_task.cancel()
        _scheduler_task = None
