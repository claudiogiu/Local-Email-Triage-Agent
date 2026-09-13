import asyncio
import logging
from typing import List, Optional

from src.config.constants import POLL_INTERVAL_SECONDS
from src.worker.poller import Poller

logger = logging.getLogger(__name__)


class Scheduler:
    """
    Interface for periodically invoking the poller at a configured interval
    until cancelled.

    Attributes:
        _poller (Poller): Component performing one discovery-and-start cycle per invocation.
        _interval_seconds (int): Delay, in seconds, between consecutive polling cycles.

    Methods:
        run_forever(account_id: str, folders: List[str]) -> None:
            Repeatedly invokes the poller at the configured interval until cancelled.
    """

    def __init__(self, poller: Poller, interval_seconds: Optional[int] = None) -> None:
        self._poller: Poller = poller
        self._interval_seconds: int = interval_seconds or POLL_INTERVAL_SECONDS or 300

    async def run_forever(self, account_id: str, folders: List[str]) -> None:
        logger.info(f"Starting polling scheduler. Interval: {self._interval_seconds} seconds.")
        while True:
            try:
                await self._poller.poll_once(account_id, folders)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Polling cycle failed: {e}")
            await asyncio.sleep(self._interval_seconds)
