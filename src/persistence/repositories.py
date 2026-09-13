import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Engine
from sqlmodel import Session, select

from src.domain.entities import MessageStatus, ProposedActionStatus
from src.persistence.models import (
    ApprovalDecisionModel,
    AuditEventModel,
    ClassificationModel,
    DraftReplyModel,
    EmailMessageModel,
    FolderWatermarkModel,
    MailboxCredentialsModel,
    PriorityAssessmentModel,
    ProposedActionModel,
    SentRegistryModel,
    get_engine,
)

logger = logging.getLogger(__name__)

_MAILBOX_CREDENTIALS_ID = "default"


class EmailMessageRepository:
    """
    Interface for persisting and retrieving triaged message snapshots.

    Attributes:
        _engine (Engine): Database engine used to open sessions against the relational schema.

    Methods:
        add(message: EmailMessageModel) -> EmailMessageModel:
            Persists the supplied message snapshot and returns it as stored.

        get_by_message_id(message_id: str) -> Optional[EmailMessageModel]:
            Retrieves the message snapshot matching the supplied Message-ID, if present.

        update_status(message_id: str, status: MessageStatus) -> None:
            Advances the lifecycle status of the message snapshot matching the supplied Message-ID.

        list_by_sender(sender: str) -> List[EmailMessageModel]:
            Retrieves every message snapshot previously received from the supplied sender.
    """

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine: Engine = engine or get_engine()

    def add(self, message: EmailMessageModel) -> EmailMessageModel:
        logger.info(f"Starting persistence of an email message. Message ID: {message.message_id}.")
        with Session(self._engine) as session:
            session.add(message)
            session.commit()
            session.refresh(message)
        logger.info("Email message successfully persisted.")
        return message

    def get_by_message_id(self, message_id: str) -> Optional[EmailMessageModel]:
        with Session(self._engine) as session:
            statement = select(EmailMessageModel).where(EmailMessageModel.message_id == message_id)
            return session.exec(statement).first()

    def update_status(self, message_id: str, status: MessageStatus) -> None:
        with Session(self._engine) as session:
            statement = select(EmailMessageModel).where(EmailMessageModel.message_id == message_id)
            message = session.exec(statement).first()
            if message is None:
                raise ValueError(f"No email message is persisted for Message-ID {message_id}.")
            message.status = status
            session.add(message)
            session.commit()
        logger.info(f"Email message status successfully updated. Status: {status.value}.")

    def list_by_sender(self, sender: str) -> List[EmailMessageModel]:
        with Session(self._engine) as session:
            statement = select(EmailMessageModel).where(EmailMessageModel.sender == sender)
            return list(session.exec(statement).all())


class ClassificationRepository:
    """
    Interface for persisting and retrieving classifier outcomes.

    Attributes:
        _engine (Engine): Database engine used to open sessions against the relational schema.

    Methods:
        add(classification: ClassificationModel) -> ClassificationModel:
            Persists the supplied classification outcome and returns it as stored.

        get_by_message_id(message_id: str) -> Optional[ClassificationModel]:
            Retrieves the classification outcome associated with the supplied message, if present.
    """

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine: Engine = engine or get_engine()

    def add(self, classification: ClassificationModel) -> ClassificationModel:
        logger.info(f"Starting persistence of a classification outcome. Message ID: {classification.message_id}.")
        with Session(self._engine) as session:
            session.add(classification)
            session.commit()
            session.refresh(classification)
        logger.info("Classification outcome successfully persisted.")
        return classification

    def get_by_message_id(self, message_id: str) -> Optional[ClassificationModel]:
        with Session(self._engine) as session:
            statement = select(ClassificationModel).where(ClassificationModel.message_id == message_id)
            return session.exec(statement).first()


class PriorityAssessmentRepository:
    """
    Interface for persisting and retrieving priority assessment outcomes.

    Attributes:
        _engine (Engine): Database engine used to open sessions against the relational schema.

    Methods:
        add(assessment: PriorityAssessmentModel) -> PriorityAssessmentModel:
            Persists the supplied priority assessment and returns it as stored.

        get_by_message_id(message_id: str) -> Optional[PriorityAssessmentModel]:
            Retrieves the priority assessment associated with the supplied message, if present.
    """

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine: Engine = engine or get_engine()

    def add(self, assessment: PriorityAssessmentModel) -> PriorityAssessmentModel:
        logger.info(f"Starting persistence of a priority assessment. Message ID: {assessment.message_id}.")
        with Session(self._engine) as session:
            session.add(assessment)
            session.commit()
            session.refresh(assessment)
        logger.info("Priority assessment successfully persisted.")
        return assessment

    def get_by_message_id(self, message_id: str) -> Optional[PriorityAssessmentModel]:
        with Session(self._engine) as session:
            statement = select(PriorityAssessmentModel).where(PriorityAssessmentModel.message_id == message_id)
            return session.exec(statement).first()


class DraftReplyRepository:
    """
    Interface for persisting and retrieving reply draft proposals.

    Attributes:
        _engine (Engine): Database engine used to open sessions against the relational schema.

    Methods:
        add(draft: DraftReplyModel) -> DraftReplyModel:
            Persists the supplied reply draft and returns it as stored.

        list_by_message_id(message_id: str) -> List[DraftReplyModel]:
            Retrieves every reply draft version associated with the supplied message.
    """

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine: Engine = engine or get_engine()

    def add(self, draft: DraftReplyModel) -> DraftReplyModel:
        logger.info(f"Starting persistence of a reply draft. Message ID: {draft.message_id}.")
        with Session(self._engine) as session:
            session.add(draft)
            session.commit()
            session.refresh(draft)
        logger.info("Reply draft successfully persisted.")
        return draft

    def list_by_message_id(self, message_id: str) -> List[DraftReplyModel]:
        with Session(self._engine) as session:
            statement = select(DraftReplyModel).where(DraftReplyModel.message_id == message_id)
            return list(session.exec(statement).all())


class ProposedActionRepository:
    """
    Interface for persisting and retrieving proposed actions awaiting or having
    received a human approval decision.

    Attributes:
        _engine (Engine): Database engine used to open sessions against the relational schema.

    Methods:
        add(action: ProposedActionModel) -> ProposedActionModel:
            Persists the supplied proposed action and returns it as stored.

        get_by_id(action_id: str) -> Optional[ProposedActionModel]:
            Retrieves the proposed action matching the supplied identifier, if present.

        update_status(action_id: str, status: ProposedActionStatus) -> None:
            Advances the lifecycle status of the proposed action matching the supplied identifier.

        list_by_message_id(message_id: str) -> List[ProposedActionModel]:
            Retrieves every proposed action associated with the supplied message.
    """

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine: Engine = engine or get_engine()

    def add(self, action: ProposedActionModel) -> ProposedActionModel:
        logger.info(f"Starting persistence of a proposed action. Action ID: {action.id}.")
        with Session(self._engine) as session:
            session.add(action)
            session.commit()
            session.refresh(action)
        logger.info("Proposed action successfully persisted.")
        return action

    def get_by_id(self, action_id: str) -> Optional[ProposedActionModel]:
        with Session(self._engine) as session:
            return session.get(ProposedActionModel, action_id)

    def list_by_message_id(self, message_id: str) -> List[ProposedActionModel]:
        with Session(self._engine) as session:
            statement = select(ProposedActionModel).where(ProposedActionModel.message_id == message_id)
            return list(session.exec(statement).all())

    def update_status(self, action_id: str, status: ProposedActionStatus) -> None:
        with Session(self._engine) as session:
            action = session.get(ProposedActionModel, action_id)
            if action is None:
                raise ValueError(f"No proposed action is persisted for ID {action_id}.")
            action.status = status
            session.add(action)
            session.commit()
        logger.info(f"Proposed action status successfully updated. Status: {status.value}.")


class ApprovalDecisionRepository:
    """
    Interface for persisting and retrieving human resolutions of proposed actions.

    Attributes:
        _engine (Engine): Database engine used to open sessions against the relational schema.

    Methods:
        add(decision: ApprovalDecisionModel) -> ApprovalDecisionModel:
            Persists the supplied approval decision and returns it as stored.

        get_by_proposed_action_id(proposed_action_id: str) -> Optional[ApprovalDecisionModel]:
            Retrieves the approval decision associated with the supplied proposed action, if present.
    """

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine: Engine = engine or get_engine()

    def add(self, decision: ApprovalDecisionModel) -> ApprovalDecisionModel:
        logger.info(f"Starting persistence of an approval decision. Proposed action ID: {decision.proposed_action_id}.")
        with Session(self._engine) as session:
            session.add(decision)
            session.commit()
            session.refresh(decision)
        logger.info("Approval decision successfully persisted.")
        return decision

    def get_by_proposed_action_id(self, proposed_action_id: str) -> Optional[ApprovalDecisionModel]:
        with Session(self._engine) as session:
            statement = select(ApprovalDecisionModel).where(
                ApprovalDecisionModel.proposed_action_id == proposed_action_id
            )
            return session.exec(statement).first()


class AuditEventRepository:
    """
    Interface for persisting and retrieving the append-only audit trail.

    Attributes:
        _engine (Engine): Database engine used to open sessions against the relational schema.

    Methods:
        add(event: AuditEventModel) -> AuditEventModel:
            Persists the supplied audit event and returns it as stored.

        record(message_id: Optional[str], run_id: Optional[str], event_type: str, details: Dict[str, Any], payload_hash: Optional[str]) -> AuditEventModel:
            Builds and persists an audit event from its constituent fields, assigning its identifier and timestamp.
    """

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine: Engine = engine or get_engine()

    def add(self, event: AuditEventModel) -> AuditEventModel:
        logger.info(f"Starting persistence of an audit event. Event type: {event.event_type}.")
        with Session(self._engine) as session:
            session.add(event)
            session.commit()
            session.refresh(event)
        logger.info("Audit event successfully persisted.")
        return event

    def record(
        self,
        message_id: Optional[str],
        run_id: Optional[str],
        event_type: str,
        details: Dict[str, Any],
        payload_hash: Optional[str] = None,
    ) -> AuditEventModel:
        return self.add(
            AuditEventModel(
                id=str(uuid.uuid4()),
                message_id=message_id,
                run_id=run_id,
                event_type=event_type,
                payload_hash=payload_hash,
                details=details,
                occurred_at=datetime.now(UTC),
            )
        )


class FolderWatermarkRepository:
    """
    Interface for persisting and retrieving per-folder ingestion watermarks.

    Attributes:
        _engine (Engine): Database engine used to open sessions against the relational schema.

    Methods:
        upsert(watermark: FolderWatermarkModel) -> FolderWatermarkModel:
            Inserts or replaces the watermark for the folder identified by the supplied record.

        get_by_account_and_folder(account_id: str, folder: str) -> Optional[FolderWatermarkModel]:
            Retrieves the watermark associated with the supplied account and folder, if present.
    """

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine: Engine = engine or get_engine()

    def upsert(self, watermark: FolderWatermarkModel) -> FolderWatermarkModel:
        logger.info(
            f"Starting persistence of a folder watermark. "
            f"Folder: {watermark.folder}. "
            f"Last UID: {watermark.last_uid}. "
        )
        with Session(self._engine) as session:
            session.merge(watermark)
            session.commit()
        logger.info("Folder watermark successfully persisted.")
        return watermark

    def get_by_account_and_folder(self, account_id: str, folder: str) -> Optional[FolderWatermarkModel]:
        with Session(self._engine) as session:
            return session.get(FolderWatermarkModel, (account_id, folder))


class SentRegistryRepository:
    """
    Interface for persisting and retrieving the reply transmission idempotency registry.

    Attributes:
        _engine (Engine): Database engine used to open sessions against the relational schema.

    Methods:
        add(entry: SentRegistryModel) -> SentRegistryModel:
            Persists the supplied idempotency registry entry and returns it as stored.

        exists(idempotency_key: str) -> bool:
            Determines whether the supplied idempotency key has already been registered.
    """

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine: Engine = engine or get_engine()

    def add(self, entry: SentRegistryModel) -> SentRegistryModel:
        logger.info(f"Starting persistence of a sent registry entry. Idempotency key: {entry.idempotency_key}.")
        with Session(self._engine) as session:
            session.add(entry)
            session.commit()
            session.refresh(entry)
        logger.info("Sent registry entry successfully persisted.")
        return entry

    def exists(self, idempotency_key: str) -> bool:
        with Session(self._engine) as session:
            return session.get(SentRegistryModel, idempotency_key) is not None


class MailboxCredentialsRepository:
    """
    Interface for persisting and retrieving the single set of mailbox
    sign-in credentials submitted through the UI.

    Attributes:
        _engine (Engine): Database engine used to open sessions against the relational schema.

    Methods:
        get() -> Optional[MailboxCredentialsModel]:
            Retrieves the currently stored mailbox credentials, if any have been submitted.

        set(email: str, imap_password: str) -> MailboxCredentialsModel:
            Persists the supplied mailbox credentials, replacing any previously stored value.

        clear() -> None:
            Removes any stored mailbox credentials.
    """

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine: Engine = engine or get_engine()

    def get(self) -> Optional[MailboxCredentialsModel]:
        with Session(self._engine) as session:
            return session.get(MailboxCredentialsModel, _MAILBOX_CREDENTIALS_ID)

    def set(self, email: str, imap_password: str) -> MailboxCredentialsModel:
        logger.info(f"Starting persistence of mailbox credentials. Email: {email}.")
        entry = MailboxCredentialsModel(
            id=_MAILBOX_CREDENTIALS_ID,
            email=email,
            imap_password=imap_password,
            updated_at=datetime.now(UTC),
        )
        with Session(self._engine) as session:
            session.merge(entry)
            session.commit()
        logger.info("Mailbox credentials successfully persisted.")
        return entry

    def clear(self) -> None:
        with Session(self._engine) as session:
            existing = session.get(MailboxCredentialsModel, _MAILBOX_CREDENTIALS_ID)
            if existing is not None:
                session.delete(existing)
                session.commit()
