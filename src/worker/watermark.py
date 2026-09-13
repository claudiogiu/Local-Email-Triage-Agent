import logging
import uuid
from datetime import UTC, datetime
from typing import List, Optional

from src.domain.entities import MessageRef
from src.domain.ports import MailProvider
from src.persistence.models import AuditEventModel, FolderWatermarkModel
from src.persistence.repositories import AuditEventRepository, FolderWatermarkRepository

logger = logging.getLogger(__name__)


class WatermarkService:
    """
    Interface for bootstrapping and advancing per-folder ingestion watermarks,
    admitting a message to triage only when it is both UNSEEN and newer than
    the folder's last processed UID.

    Attributes:
        _repository (FolderWatermarkRepository): Persistence access point for folder watermarks.
        _audit_repository (AuditEventRepository): Persistence access point for the audit trail.

    Methods:
        _bootstrap(account_id: str, folder: str, max_uid: int, uidvalidity: int) -> FolderWatermarkModel:
            Registers the current maximum UID as the watermark without admitting any candidate.

        resolve_candidates(provider: MailProvider, account_id: str, folder: str) -> List[MessageRef]:
            Determines which UNSEEN messages in the folder qualify for triage against the watermark.
    """

    def __init__(
        self,
        repository: Optional[FolderWatermarkRepository] = None,
        audit_repository: Optional[AuditEventRepository] = None,
    ) -> None:
        self._repository: FolderWatermarkRepository = repository or FolderWatermarkRepository()
        self._audit_repository: AuditEventRepository = audit_repository or AuditEventRepository()

    def _bootstrap(self, account_id: str, folder: str, max_uid: int, uidvalidity: int) -> FolderWatermarkModel:
        watermark = FolderWatermarkModel(
            account_id=account_id,
            folder=folder,
            uidvalidity=uidvalidity,
            last_uid=max_uid,
            updated_at=datetime.now(UTC),
        )
        logger.info(f"Starting watermark bootstrap. Folder: {folder}. Last UID: {watermark.last_uid}.")
        self._repository.upsert(watermark)
        logger.info("Watermark bootstrap successfully completed. No candidate admitted on this run.")
        return watermark

    def resolve_candidates(self, provider: MailProvider, account_id: str, folder: str) -> List[MessageRef]:
        status = provider.get_folder_status(folder)
        existing = self._repository.get_by_account_and_folder(account_id, folder)

        if existing is None:
            self._bootstrap(account_id, folder, status.max_uid, status.uidvalidity)
            return []

        if existing.uidvalidity != status.uidvalidity:
            logger.info(
                f"Starting UIDVALIDITY reset. "
                f"Folder: {folder}. "
                f"Previous UIDVALIDITY: {existing.uidvalidity}. "
                f"Current UIDVALIDITY: {status.uidvalidity}. "
            )
            self._audit_repository.add(
                AuditEventModel(
                    id=str(uuid.uuid4()),
                    message_id=None,
                    run_id=None,
                    event_type="UIDVALIDITY_CHANGED",
                    payload_hash=None,
                    details={
                        "account_id": account_id,
                        "folder": folder,
                        "previous_uidvalidity": existing.uidvalidity,
                        "current_uidvalidity": status.uidvalidity,
                    },
                    occurred_at=datetime.now(UTC),
                )
            )
            self._bootstrap(account_id, folder, status.max_uid, status.uidvalidity)
            logger.info("UIDVALIDITY reset successfully completed.")
            return []

        candidates = [
            ref
            for ref in provider.list_new(since=datetime.now(UTC), folders=[folder])
            if ref.uid > existing.last_uid
        ]
        logger.info(f"Watermark evaluation successfully completed. Folder: {folder}. Candidates: {len(candidates)}.")
        return candidates
