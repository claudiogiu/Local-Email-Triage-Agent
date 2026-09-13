import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Column, Engine
from sqlmodel import Field, SQLModel, create_engine

from src.config.constants import DATABASE_PATH
from src.domain.entities import (
    ApprovalOutcome,
    MessageStatus,
    PriorityLevel,
    ProposedActionStatus,
    ProposedActionType,
)

logger = logging.getLogger(__name__)


class EmailMessageModel(SQLModel, table=True):
    """Persisted snapshot of an immutable triaged message, keyed naturally by its Message-ID header."""

    __tablename__ = "email_message"

    id: str = Field(primary_key=True)
    account_id: str = Field(index=True)
    message_id: str = Field(unique=True, index=True)
    thread_id: Optional[str] = Field(default=None)
    folder: str = Field(default="INBOX")
    uid: int = Field(default=0)
    sender: str
    recipients: List[str] = Field(sa_column=Column(JSON))
    cc_recipients: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    subject: str
    body: str
    received_at: datetime
    flags: List[str] = Field(sa_column=Column(JSON))
    headers: Dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    content_hash: str
    status: MessageStatus


class ClassificationModel(SQLModel, table=True):
    """Persisted outcome of a classifier invocation against a single message."""

    __tablename__ = "classification"

    id: str = Field(primary_key=True)
    message_id: str = Field(index=True)
    label: str
    agreement_score: Optional[float] = Field(default=None)
    model_version: str
    classified_at: datetime


class PriorityAssessmentModel(SQLModel, table=True):
    """Persisted outcome of the priority assignment step for a single message."""

    __tablename__ = "priority_assessment"

    id: str = Field(primary_key=True)
    message_id: str = Field(index=True)
    level: PriorityLevel
    rationale: str
    requires_reply: bool
    signals: Dict[str, bool] = Field(default_factory=dict, sa_column=Column(JSON))
    needs_human: bool = Field(default=False)
    model_version: str
    assessed_at: datetime


class DraftReplyModel(SQLModel, table=True):
    """Persisted reply proposal, generated or human-edited, associated with a single message."""

    __tablename__ = "draft_reply"

    id: str = Field(primary_key=True)
    message_id: str = Field(index=True)
    version: int
    body: str
    edited_by_human: bool
    diff_from_previous: Optional[str] = Field(default=None)
    created_at: datetime


class ProposedActionModel(SQLModel, table=True):
    """Persisted unit of human-in-the-loop review, proposing one action against the mailbox."""

    __tablename__ = "proposed_action"

    id: str = Field(primary_key=True)
    message_id: str = Field(index=True)
    run_id: str = Field(index=True)
    action_type: ProposedActionType
    payload: Dict[str, Any] = Field(sa_column=Column(JSON))
    status: ProposedActionStatus = Field(index=True)
    risk: Optional[str] = Field(default=None)
    agreement_score: Optional[float] = Field(default=None)
    created_at: datetime


class ApprovalDecisionModel(SQLModel, table=True):
    """Persisted resolution of a proposed action by a human reviewer."""

    __tablename__ = "approval_decision"

    id: str = Field(primary_key=True)
    proposed_action_id: str = Field(index=True)
    outcome: ApprovalOutcome
    decided_by: str
    decided_at: datetime
    note: Optional[str] = Field(default=None)
    final_payload: Dict[str, Any] = Field(sa_column=Column(JSON))


class AuditEventModel(SQLModel, table=True):
    """Persisted append-only record of a state transition, model invocation, or human decision."""

    __tablename__ = "audit_event"

    id: str = Field(primary_key=True)
    message_id: Optional[str] = Field(default=None, index=True)
    run_id: Optional[str] = Field(default=None, index=True)
    event_type: str
    payload_hash: Optional[str] = Field(default=None)
    details: Dict[str, Any] = Field(sa_column=Column(JSON))
    occurred_at: datetime


class FolderWatermarkModel(SQLModel, table=True):
    """Persisted per-folder ingestion watermark tracking the last processed UID."""

    __tablename__ = "folder_watermark"

    account_id: str = Field(primary_key=True)
    folder: str = Field(primary_key=True)
    uidvalidity: int
    last_uid: int
    updated_at: datetime


class SentRegistryModel(SQLModel, table=True):
    """Persisted idempotency registry guarding against duplicate reply transmission."""

    __tablename__ = "sent_registry"

    idempotency_key: str = Field(primary_key=True)
    message_id: str = Field(index=True)
    draft_version: int
    sent_at: datetime


class MailboxCredentialsModel(SQLModel, table=True):
    """Persisted mailbox sign-in credentials submitted through the UI, superseding the .env defaults."""

    __tablename__ = "mailbox_credentials"

    id: str = Field(primary_key=True)
    email: str
    imap_password: str
    updated_at: datetime


_engine: Optional[Engine] = None


def get_engine() -> Engine:
    """Return the process-wide database engine instance, initializing it on first access."""
    global _engine
    if _engine is None:
        if DATABASE_PATH is None:
            raise ValueError("The DATABASE_PATH environment variable is not configured.")
        _engine = create_engine(f"sqlite:///{DATABASE_PATH}")
        logger.info(f"Database engine initialization completed. Path: {DATABASE_PATH}.")
    return _engine
