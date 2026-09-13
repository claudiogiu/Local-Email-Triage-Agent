from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.api.fields import OperationStatus


class ServiceInfoResponse(BaseModel):
    """Response model describing the running service's identity and available endpoints."""

    service_name: str = Field(..., description="Human-readable name of the running service")
    version: str = Field(..., description="Semantic version of the running service")
    docs_url: str = Field(..., description="Path at which the interactive API documentation is served")
    endpoints: Dict[str, str] = Field(..., description="Mapping of endpoint name to its mounted path")


class SignalDetail(BaseModel):
    """Outcome of a single deterministic agreement signal evaluated against a proposed label."""

    name: str = Field(..., description="Identifier of the evaluated signal")
    outcome: str = Field(..., description="Whether the signal confirms, contradicts, or does not apply to the label")


class PendingApprovalResponse(BaseModel):
    """A single proposed action, pending or already resolved, attached to a triaged message."""

    proposed_action_id: str = Field(..., description="Identifier of the proposed action")
    action_status: str = Field(..., description="Current lifecycle status of the proposed action")
    message_id: str = Field(..., description="Message-ID of the email under review")
    sender: str = Field(..., description="Sender address of the email under review")
    subject: str = Field(..., description="Subject line of the email under review")
    body_preview: str = Field(..., description="Truncated preview of the email body")
    action_type: str = Field(..., description="Type of action proposed for approval")
    proposed_label: Optional[str] = Field(None, description="Label proposed by the classifier, if applicable")
    agreement_score: Optional[float] = Field(
        None, description="Deterministic agreement score backing the proposed label"
    )
    signals: List[SignalDetail] = Field(..., description="Deterministic signals evaluated against the proposed label")
    payload: Dict[str, Any] = Field(
        default_factory=dict, description="Raw action payload, used for draft and send actions"
    )
    created_at: str = Field(..., description="Timestamp at which the proposed action was created")


class DraftEditRequest(BaseModel):
    """Request body for approving a draft reply gate with a human-edited body."""

    subject: str = Field(..., description="Edited reply subject line")
    body: str = Field(..., description="Edited reply body")


class UnreadMessageResponse(BaseModel):
    """A single currently-unread message discovered by a live mailbox scan."""

    folder: str = Field(..., description="IMAP folder containing the message")
    uid: int = Field(..., description="IMAP UID of the message within its folder")
    message_id: Optional[str] = Field(None, description="Message-ID header, if present")
    sender: str = Field(..., description="Sender address of the message")
    subject: str = Field(..., description="Subject line of the message")
    body_preview: str = Field(..., description="Truncated preview of the message body")
    received_at: str = Field(..., description="Timestamp at which the message was received")
    already_triaged: bool = Field(..., description="Whether this message already has a persisted triage snapshot")
    message_status: Optional[str] = Field(None, description="Persisted triage status, if this message was already triaged")


class UnreadInboxResponse(BaseModel):
    """Response model listing every currently-unread message in the scanned folders."""

    status: OperationStatus = Field(..., description="Outcome of the unread inbox scan")
    messages: List[UnreadMessageResponse] = Field(..., description="Currently-unread messages, most recent last")
    execution_time_ms: float = Field(..., description="Duration in milliseconds of the unread inbox scan")


class MessageDetailResponse(BaseModel):
    """Current triage status and full action history of a single message."""

    status: OperationStatus = Field(..., description="Outcome of the message detail retrieval")
    found: bool = Field(..., description="Whether a persisted triage snapshot exists for this message")
    message_status: Optional[str] = Field(None, description="Current lifecycle status of the message, if found")
    sender: Optional[str] = Field(None, description="Sender address of the message, if found")
    subject: Optional[str] = Field(None, description="Subject line of the message, if found")
    body_preview: Optional[str] = Field(None, description="Truncated preview of the message body, if found")
    priority_level: Optional[str] = Field(None, description="Priority level assessed for the message, if available")
    requires_reply: Optional[bool] = Field(None, description="Whether the priority assessment flagged a reply as likely needed")
    actions: List[PendingApprovalResponse] = Field(
        default_factory=list, description="Every proposed action recorded against this message, oldest first"
    )


class MailboxCredentialsRequest(BaseModel):
    """Request body for submitting mailbox sign-in credentials through the UI."""

    email: str = Field(..., description="Full mailbox email address")
    imap_password: str = Field(..., description="IMAP application password, not the regular account password")


class MailboxCredentialsResponse(BaseModel):
    """Response model describing the current mailbox connection state."""

    status: OperationStatus = Field(..., description="Outcome of the request")
    connected: bool = Field(..., description="Whether the mailbox currently has working credentials configured")
    email: Optional[str] = Field(None, description="Email address currently connected, if any")
    detail: Optional[str] = Field(None, description="Human-readable explanation, set on failure")


class NextActionRequest(BaseModel):
    """Request body for resolving the post-label next-action gate."""

    next_action: str = Field(..., description="One of 'reply', 'archive', 'mark_spam', or 'none'")


class TriggerTriageRequest(BaseModel):
    """Request body identifying a single unread message to manually triage."""

    folder: str = Field(..., description="IMAP folder containing the message")
    uid: int = Field(..., description="IMAP UID of the message within its folder")
    message_id: str = Field(..., description="Message-ID header of the message, from a prior unread inbox scan")


class TriggerTriageResponse(BaseModel):
    """Response model describing the outcome of manually triggering triage for one message."""

    status: OperationStatus = Field(..., description="Outcome of the trigger request")
    message_id: str = Field(..., description="Message-ID of the message whose triage run was triggered")
    already_triaged: bool = Field(..., description="Whether the message already had a persisted triage snapshot")


class ApprovalDecisionResponse(BaseModel):
    """Response model describing the outcome of resolving a single proposed action."""

    status: OperationStatus = Field(..., description="Outcome of the approval decision submission")
    proposed_action_id: str = Field(..., description="Identifier of the proposed action that was resolved")
    outcome: str = Field(..., description="Decision outcome that was recorded")
    execution_time_ms: float = Field(..., description="Duration in milliseconds of the approval decision submission")
