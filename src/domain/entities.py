from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class MessageStatus(str, Enum):
    """
    Enumeration defining the lifecycle stages traversed by a message under triage.
    """

    DISCOVERED = "DISCOVERED"
    FETCHED = "FETCHED"
    CLASSIFIED = "CLASSIFIED"
    PRIORITIZED = "PRIORITIZED"
    DRAFTED = "DRAFTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    DONE = "DONE"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class PriorityLevel(str, Enum):
    """
    Enumeration defining the priority levels assignable to a triaged message.
    """

    URGENT = "URGENT"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class ProposedActionType(str, Enum):
    """
    Enumeration defining the catalogue of actions the deterministic decision
    step may propose for human approval.
    """

    APPLY_LABEL = "APPLY_LABEL"
    ARCHIVE = "ARCHIVE"
    MARK_SPAM = "MARK_SPAM"
    MARK_READ = "MARK_READ"
    SAVE_DRAFT = "SAVE_DRAFT"
    SEND_REPLY = "SEND_REPLY"


class ProposedActionStatus(str, Enum):
    """
    Enumeration defining the lifecycle stages of a proposed action awaiting
    or having received a human approval decision.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class ApprovalOutcome(str, Enum):
    """
    Enumeration defining the possible outcomes of a human approval gate.
    """

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"


@dataclass(frozen=True)
class MessageRef:
    """Reference identifying a single message within a mailbox folder without carrying its content."""

    account_id: str
    folder: str
    uid: int
    message_id: Optional[str]


@dataclass(frozen=True)
class FolderStatus:
    """Current identity and maximum assigned UID of a single mailbox folder."""

    uidvalidity: int
    max_uid: int


@dataclass(frozen=True)
class RawMessage:
    """Unprocessed message content and envelope metadata as retrieved from the mail provider."""

    ref: MessageRef
    sender: str
    recipients: List[str]
    cc_recipients: List[str]
    subject: str
    body: str
    received_at: datetime
    headers: Dict[str, str]


@dataclass(frozen=True)
class NormalizedEmail:
    """Sanitized, budget-truncated textual representation of a message ready for model invocation."""

    message_id: str
    subject: str
    body: str
    sender_domain: Optional[str]
    truncated: bool
    original_length: int
    normalized_length: int


@dataclass(frozen=True)
class OutgoingMessage:
    """Reply content addressed to the sender of a message, prior to being saved or transmitted."""

    in_reply_to_message_id: str
    recipients: List[str]
    subject: str
    body: str
    draft_version: int


@dataclass(frozen=True)
class DraftRef:
    """Reference to a reply draft persisted on the mail provider."""

    provider_ref: str
    message_id: str


@dataclass(frozen=True)
class SentRef:
    """Reference to a message successfully transmitted through the mail provider."""

    provider_ref: str
    message_id: str
    sent_at: datetime


@dataclass(frozen=True)
class CompletionRequest:
    """Parameters governing a single invocation of a text or structured completion model."""

    system_prompt: str
    user_message: str
    temperature: float
    model: Optional[str]
    think: bool


@dataclass(frozen=True)
class CompletionResult:
    """Raw textual output returned by a completion model invocation."""

    text: str
