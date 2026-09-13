import asyncio
import hashlib
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Pattern

from fastapi import APIRouter, HTTPException

from src.api.fields import OperationStatus
from src.api.schemas import (
    ApprovalDecisionResponse,
    DraftEditRequest,
    MailboxCredentialsRequest,
    MailboxCredentialsResponse,
    MessageDetailResponse,
    NextActionRequest,
    PendingApprovalResponse,
    SignalDetail,
    TriggerTriageRequest,
    TriggerTriageResponse,
    UnreadInboxResponse,
    UnreadMessageResponse,
)
from src.config.constants import (
    IMAP_ARCHIVE_FOLDER,
    IMAP_FOLDERS,
    IMAP_SPAM_FOLDER,
    IMAP_USERNAME,
)
from src.core.orchestrator import get_orchestrator, reset_orchestrator
from src.domain.entities import (
    ApprovalOutcome,
    MessageRef,
    MessageStatus,
    ProposedActionStatus,
    ProposedActionType,
)
from src.persistence.models import (
    ApprovalDecisionModel,
    EmailMessageModel,
    ProposedActionModel,
)
from src.persistence.repositories import (
    ApprovalDecisionRepository,
    AuditEventRepository,
    ClassificationRepository,
    EmailMessageRepository,
    MailboxCredentialsRepository,
    PriorityAssessmentRepository,
    ProposedActionRepository,
)
from src.providers.imap_mail_provider import ImapMailProvider
from src.triage.evaluator import Evaluator
from src.worker.scheduler_manager import restart_scheduler, stop_scheduler

logger = logging.getLogger(__name__)

router = APIRouter()

_SENDER_DOMAIN_PATTERN: Pattern[str] = re.compile(r"@([\w.-]+)")
_LOCAL_REVIEWER: str = IMAP_USERNAME or "local-user"

_background_tasks: set = set()


def _fire_and_forget(coroutine: Any) -> None:
    task = asyncio.create_task(coroutine)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _run_manually_triggered_triage(message_id: str) -> None:
    try:
        orchestrator = await get_orchestrator()
        await orchestrator.start_run(message_id)
    except Exception as e:
        logger.error(f"Manually triggered triage run failed. Message ID: {message_id}. Error: {e}")


def _build_pending_approval(action: ProposedActionModel) -> PendingApprovalResponse:
    message = EmailMessageRepository().get_by_message_id(action.message_id)
    if message is None:
        raise ValueError(f"No persisted message snapshot for message ID {action.message_id}.")

    proposed_label = action.payload.get("label") if action.action_type == ProposedActionType.APPLY_LABEL else None
    classification = ClassificationRepository().get_by_message_id(action.message_id)
    signals: List[SignalDetail] = []
    agreement_score = classification.agreement_score if classification else None

    if proposed_label:
        domain_match = _SENDER_DOMAIN_PATTERN.search(message.sender)
        sender_domain = domain_match.group(1).lower() if domain_match else None
        evaluation = Evaluator().evaluate_with_signals(
            label=proposed_label,
            sender=message.sender,
            sender_domain=sender_domain,
            subject=message.subject,
            headers=message.headers or {},
            injection_suspected=False,
        )
        signals = [SignalDetail(**signal) for signal in evaluation["signals"]]

    return PendingApprovalResponse(
        proposed_action_id=action.id,
        action_status=action.status.value,
        message_id=action.message_id,
        sender=message.sender,
        subject=message.subject,
        body_preview=message.body[:280],
        action_type=action.action_type.value,
        proposed_label=proposed_label,
        agreement_score=agreement_score,
        signals=signals,
        payload=action.payload,
        created_at=action.created_at.isoformat(),
    )


@router.get("/settings/mailbox-credentials", response_model=MailboxCredentialsResponse, tags=["Settings"])
async def get_mailbox_credentials_status() -> MailboxCredentialsResponse:
    """
    Report whether the user has explicitly signed in through the UI. A
    working `.env` fallback, if any, is not reported as signed in: signing
    in through the UI is always required to reach this state.
    """
    stored = MailboxCredentialsRepository().get()
    if stored is not None:
        return MailboxCredentialsResponse(status=OperationStatus.SUCCESS, connected=True, email=stored.email)
    return MailboxCredentialsResponse(status=OperationStatus.SUCCESS, connected=False, email=None)


@router.post("/settings/mailbox-credentials", response_model=MailboxCredentialsResponse, tags=["Settings"])
async def set_mailbox_credentials(request: MailboxCredentialsRequest) -> MailboxCredentialsResponse:
    """
    Verify the supplied mailbox credentials against the real IMAP server,
    persist them only on success, and restart the polling scheduler to use
    them.
    """
    try:
        ImapMailProvider(username=request.email, password=request.imap_password).verify_connection()
    except Exception as e:
        logger.error(f"Mailbox credential verification failed. Email: {request.email}. Error: {e}")
        return MailboxCredentialsResponse(
            status=OperationStatus.FAILURE,
            connected=False,
            email=None,
            detail=(
                "We could not sign in with these details. Please check the email address and the IMAP "
                "application password, not your regular account password."
            ),
        )
    MailboxCredentialsRepository().set(request.email, request.imap_password)
    await restart_scheduler()
    logger.info(f"Mailbox credentials successfully verified and stored. Email: {request.email}.")
    return MailboxCredentialsResponse(status=OperationStatus.SUCCESS, connected=True, email=request.email)


@router.post("/settings/mailbox-credentials/logout", response_model=MailboxCredentialsResponse, tags=["Settings"])
async def logout_mailbox() -> MailboxCredentialsResponse:
    """
    Clear the stored mailbox credentials and stop the polling scheduler,
    requiring sign-in again before any further triage runs.
    """
    MailboxCredentialsRepository().clear()
    await stop_scheduler()
    await reset_orchestrator()
    logger.info("Mailbox credentials cleared and polling scheduler stopped.")
    return MailboxCredentialsResponse(status=OperationStatus.SUCCESS, connected=False, email=None)


async def _resolve_action(action_id: str, outcome: ApprovalOutcome) -> ApprovalDecisionResponse:
    start = time.time()
    try:
        action = ProposedActionRepository().get_by_id(action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="Proposed action not found")

        ApprovalDecisionRepository().add(
            ApprovalDecisionModel(
                id=str(uuid.uuid4()),
                proposed_action_id=action_id,
                outcome=outcome,
                decided_by=_LOCAL_REVIEWER,
                decided_at=datetime.now(UTC),
                note=None,
                final_payload=action.payload,
            )
        )
        AuditEventRepository().record(
            action.message_id,
            action.run_id,
            "HUMAN_DECISION",
            {"proposed_action_id": action_id, "outcome": outcome.value, "decided_by": _LOCAL_REVIEWER},
        )

        orchestrator = await get_orchestrator()
        await orchestrator.resume_run(action.message_id, {action_id: outcome.value.lower()})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Approval decision resolution failed: {e}")
        raise HTTPException(status_code=500, detail="Approval decision resolution failed") from e
    execution_time_ms = (time.time() - start) * 1000
    return ApprovalDecisionResponse(
        status=OperationStatus.SUCCESS,
        proposed_action_id=action_id,
        outcome=outcome.value,
        execution_time_ms=execution_time_ms,
    )


@router.post("/approvals/{action_id}/approve", response_model=ApprovalDecisionResponse, tags=["Approvals"])
async def approve_action(action_id: str) -> ApprovalDecisionResponse:
    """
    Resolve a pending proposed action as approved and resume its suspended
    triage run.
    """
    return await _resolve_action(action_id, ApprovalOutcome.APPROVED)


@router.post("/approvals/{action_id}/reject", response_model=ApprovalDecisionResponse, tags=["Approvals"])
async def reject_action(action_id: str) -> ApprovalDecisionResponse:
    """
    Resolve a pending proposed action as rejected and resume its suspended
    triage run.
    """
    return await _resolve_action(action_id, ApprovalOutcome.REJECTED)


async def _resolve_gate_decision(action_id: str, decision: Dict[str, Any]) -> ApprovalDecisionResponse:
    start = time.time()
    try:
        action = ProposedActionRepository().get_by_id(action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="Proposed action not found")

        AuditEventRepository().record(
            action.message_id,
            action.run_id,
            "HUMAN_DECISION",
            {"proposed_action_id": action_id, "decision": decision, "decided_by": _LOCAL_REVIEWER},
        )

        orchestrator = await get_orchestrator()
        await orchestrator.resume_run(action.message_id, decision)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Gate decision resolution failed: {e}")
        raise HTTPException(status_code=500, detail="Gate decision resolution failed") from e
    execution_time_ms = (time.time() - start) * 1000
    return ApprovalDecisionResponse(
        status=OperationStatus.SUCCESS,
        proposed_action_id=action_id,
        outcome=str(decision.get("outcome", "")),
        execution_time_ms=execution_time_ms,
    )


@router.post("/drafts/{action_id}/approve", response_model=ApprovalDecisionResponse, tags=["Drafts"])
async def approve_draft(action_id: str) -> ApprovalDecisionResponse:
    """
    Approve a pending draft reply as-is and resume its suspended triage run.
    """
    return await _resolve_gate_decision(action_id, {"outcome": "approved"})


@router.post("/drafts/{action_id}/edit", response_model=ApprovalDecisionResponse, tags=["Drafts"])
async def edit_draft(action_id: str, request: DraftEditRequest) -> ApprovalDecisionResponse:
    """
    Approve a pending draft reply with a human-edited subject and body.
    """
    return await _resolve_gate_decision(
        action_id, {"outcome": "edited", "subject": request.subject, "body": request.body}
    )


@router.post("/drafts/{action_id}/reject", response_model=ApprovalDecisionResponse, tags=["Drafts"])
async def reject_draft(action_id: str) -> ApprovalDecisionResponse:
    """
    Reject a pending draft reply and resume its suspended triage run.
    """
    return await _resolve_gate_decision(action_id, {"outcome": "rejected"})


@router.post("/sends/{action_id}/approve", response_model=ApprovalDecisionResponse, tags=["Sends"])
async def approve_send(action_id: str) -> ApprovalDecisionResponse:
    """
    Approve a pending message transmission and resume its suspended triage
    run.
    """
    return await _resolve_gate_decision(action_id, {"outcome": "approved"})


@router.post("/sends/{action_id}/reject", response_model=ApprovalDecisionResponse, tags=["Sends"])
async def reject_send(action_id: str) -> ApprovalDecisionResponse:
    """
    Reject a pending message transmission and resume its suspended triage
    run.
    """
    return await _resolve_gate_decision(action_id, {"outcome": "rejected"})


async def _execute_manual_move_action(
    message_id: str, action_type: ProposedActionType, destination_folder: str
) -> ApprovalDecisionResponse:
    start = time.time()
    try:
        message = EmailMessageRepository().get_by_message_id(message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Message not found")
        if not destination_folder:
            raise HTTPException(status_code=500, detail="The destination folder is not configured")

        action = ProposedActionRepository().add(
            ProposedActionModel(
                id=str(uuid.uuid4()),
                message_id=message_id,
                run_id=message_id,
                action_type=action_type,
                payload={"destination_folder": destination_folder},
                status=ProposedActionStatus.APPROVED,
                risk=None,
                agreement_score=None,
                created_at=datetime.now(UTC),
            )
        )
        ApprovalDecisionRepository().add(
            ApprovalDecisionModel(
                id=str(uuid.uuid4()),
                proposed_action_id=action.id,
                outcome=ApprovalOutcome.APPROVED,
                decided_by=_LOCAL_REVIEWER,
                decided_at=datetime.now(UTC),
                note="Directly triggered by the user through the API; no separate proposal step.",
                final_payload=action.payload,
            )
        )

        orchestrator = await get_orchestrator()
        orchestrator.provider.move(
            MessageRef(account_id=message.account_id, folder=message.folder, uid=message.uid, message_id=message_id),
            destination_folder,
        )

        AuditEventRepository().record(
            message_id,
            message_id,
            "ACTION_EXECUTED",
            {"action_id": action.id, "action_type": action_type.value, "destination_folder": destination_folder},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Manual move action failed: {e}")
        raise HTTPException(status_code=500, detail="Manual move action failed") from e
    execution_time_ms = (time.time() - start) * 1000
    return ApprovalDecisionResponse(
        status=OperationStatus.SUCCESS,
        proposed_action_id=action.id,
        outcome=ApprovalOutcome.APPROVED.value,
        execution_time_ms=execution_time_ms,
    )


@router.post("/messages/{message_id}/archive", response_model=ApprovalDecisionResponse, tags=["Messages"])
async def archive_message(message_id: str) -> ApprovalDecisionResponse:
    """
    Archive a triaged message immediately, standalone from any suspended
    triage run's next-action gate.
    """
    return await _execute_manual_move_action(message_id, ProposedActionType.ARCHIVE, IMAP_ARCHIVE_FOLDER or "")


@router.post("/messages/{message_id}/mark-spam", response_model=ApprovalDecisionResponse, tags=["Messages"])
async def mark_message_spam(message_id: str) -> ApprovalDecisionResponse:
    """
    Mark a triaged message as spam immediately, standalone from any
    suspended triage run's next-action gate.
    """
    return await _execute_manual_move_action(message_id, ProposedActionType.MARK_SPAM, IMAP_SPAM_FOLDER or "")


@router.post("/messages/{message_id}/next-action", response_model=ApprovalDecisionResponse, tags=["Messages"])
async def resolve_next_action(message_id: str, request: NextActionRequest) -> ApprovalDecisionResponse:
    """
    Resolve a suspended run's post-label next-action gate: reply, archive,
    mark as spam, or take no further action.
    """
    start = time.time()
    try:
        AuditEventRepository().record(
            message_id,
            message_id,
            "HUMAN_DECISION",
            {"next_action": request.next_action, "decided_by": _LOCAL_REVIEWER},
        )
        orchestrator = await get_orchestrator()
        await orchestrator.resume_run(message_id, {"next_action": request.next_action})
    except Exception as e:
        logger.error(f"Next-action resolution failed: {e}")
        raise HTTPException(status_code=500, detail="Next-action resolution failed") from e
    execution_time_ms = (time.time() - start) * 1000
    return ApprovalDecisionResponse(
        status=OperationStatus.SUCCESS,
        proposed_action_id=message_id,
        outcome=request.next_action,
        execution_time_ms=execution_time_ms,
    )


@router.get("/messages/unread", response_model=UnreadInboxResponse, tags=["Messages"])
async def list_unread_messages() -> UnreadInboxResponse:
    """
    Scan the configured mailbox folders live and list every currently-unread
    message, flagging whether each already has a persisted triage snapshot.
    """
    start = time.time()
    try:
        orchestrator = await get_orchestrator()
        provider = orchestrator.provider
        folders = IMAP_FOLDERS or ["INBOX"]
        messages: List[UnreadMessageResponse] = []
        for ref in provider.list_new(since=datetime.now(UTC), folders=folders):
            raw = provider.fetch(ref)
            snapshot = (
                EmailMessageRepository().get_by_message_id(raw.ref.message_id)
                if raw.ref.message_id is not None
                else None
            )
            messages.append(
                UnreadMessageResponse(
                    folder=ref.folder,
                    uid=ref.uid,
                    message_id=raw.ref.message_id,
                    sender=raw.sender,
                    subject=raw.subject,
                    body_preview=raw.body[:280],
                    received_at=raw.received_at.isoformat(),
                    already_triaged=snapshot is not None,
                    message_status=snapshot.status.value if snapshot is not None else None,
                )
            )
    except Exception as e:
        logger.error(f"Unread inbox scan failed: {e}")
        raise HTTPException(status_code=500, detail="Unread inbox scan failed") from e
    execution_time_ms = (time.time() - start) * 1000
    return UnreadInboxResponse(status=OperationStatus.SUCCESS, messages=messages, execution_time_ms=execution_time_ms)


@router.post("/messages/trigger", response_model=TriggerTriageResponse, tags=["Messages"])
async def trigger_triage(request: TriggerTriageRequest) -> TriggerTriageResponse:
    """
    Manually start a triage run for a single unread message identified by its
    folder, UID, and Message-ID, bypassing the watermark. A no-op if the
    message was already triaged.
    """
    try:
        existing = EmailMessageRepository().get_by_message_id(request.message_id)
        if existing is not None:
            return TriggerTriageResponse(
                status=OperationStatus.SUCCESS, message_id=request.message_id, already_triaged=True
            )

        orchestrator = await get_orchestrator()
        provider = orchestrator.provider
        ref = MessageRef(
            account_id=IMAP_USERNAME or "default-account",
            folder=request.folder,
            uid=request.uid,
            message_id=request.message_id,
        )
        raw = provider.fetch(ref)

        snapshot = EmailMessageModel(
            id=str(uuid.uuid4()),
            account_id=ref.account_id,
            message_id=request.message_id,
            thread_id=None,
            folder=raw.ref.folder,
            uid=raw.ref.uid,
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
        EmailMessageRepository().add(snapshot)
        _fire_and_forget(_run_manually_triggered_triage(request.message_id))
    except Exception as e:
        logger.error(f"Manual triage trigger failed: {e}")
        raise HTTPException(status_code=500, detail="Manual triage trigger failed") from e
    return TriggerTriageResponse(status=OperationStatus.SUCCESS, message_id=request.message_id, already_triaged=False)


@router.get("/messages/{message_id}", response_model=MessageDetailResponse, tags=["Messages"])
async def get_message_detail(message_id: str) -> MessageDetailResponse:
    """
    Report the current triage status and full action history of a single
    message.
    """
    message = EmailMessageRepository().get_by_message_id(message_id)
    if message is None:
        return MessageDetailResponse(status=OperationStatus.SUCCESS, found=False)
    actions = [_build_pending_approval(action) for action in ProposedActionRepository().list_by_message_id(message_id)]
    priority = PriorityAssessmentRepository().get_by_message_id(message_id)
    return MessageDetailResponse(
        status=OperationStatus.SUCCESS,
        found=True,
        message_status=message.status.value,
        sender=message.sender,
        subject=message.subject,
        body_preview=message.body[:280],
        priority_level=priority.level.value if priority else None,
        requires_reply=priority.requires_reply if priority else None,
        actions=actions,
    )
