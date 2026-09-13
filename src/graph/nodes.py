import difflib
import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Dict, Pattern

from langgraph.types import interrupt

from src.config.constants import IMAP_ARCHIVE_FOLDER, IMAP_SPAM_FOLDER
from src.domain.entities import (
    MessageRef,
    MessageStatus,
    NormalizedEmail,
    OutgoingMessage,
    PriorityLevel,
    ProposedActionStatus,
    ProposedActionType,
    RawMessage,
)
from src.domain.ports import MailProvider
from src.graph.state import TriageGraphState
from src.persistence.models import (
    ClassificationModel,
    DraftReplyModel,
    PriorityAssessmentModel,
    ProposedActionModel,
)
from src.persistence.repositories import (
    AuditEventRepository,
    ClassificationRepository,
    DraftReplyRepository,
    EmailMessageRepository,
    PriorityAssessmentRepository,
    ProposedActionRepository,
)
from src.policy.loader import PolicyLoader
from src.providers.ollama_llm_provider import OllamaLLMProvider
from src.triage.classifier import Classifier
from src.triage.drafter import Drafter
from src.triage.evaluator import Evaluator
from src.triage.normalizer import Normalizer
from src.triage.prioritizer import Prioritizer, PriorityDeterministicSignals

logger = logging.getLogger(__name__)

_SENDER_DOMAIN_PATTERN: Pattern[str] = re.compile(r"@([\w.-]+)")


def _fallback_priority_level(signals: Dict[str, bool]) -> PriorityLevel:
    if signals["deadline_keyword"] and signals["direct_recipient"]:
        return PriorityLevel.URGENT
    strong_signal_count = sum(1 for value in signals.values() if value)
    if strong_signal_count >= 3:
        return PriorityLevel.HIGH
    if strong_signal_count >= 1:
        return PriorityLevel.NORMAL
    return PriorityLevel.LOW


async def ingest_node(state: TriageGraphState) -> Dict[str, Any]:
    if state.get("status") == "FAILED":
        return {}
    message_id = state["message_id"]
    run_id = state["run_id"]
    logger.info(f"Starting graph ingest. Run ID: {run_id}.")
    snapshot = EmailMessageRepository().get_by_message_id(message_id)
    if snapshot is None:
        logger.error(f"Ingest failed: no persisted snapshot for message. Run ID: {run_id}.")
        AuditEventRepository().record(message_id, run_id, "INGEST_FAILED", {"reason": "no persisted snapshot"})
        return {"status": "FAILED", "error": "No persisted message snapshot was found for this run."}
    EmailMessageRepository().update_status(message_id, MessageStatus.FETCHED)
    AuditEventRepository().record(message_id, run_id, "INGESTED", {"body_length": len(snapshot.body)})
    logger.info("Graph ingest successfully completed.")
    return {"status": "FETCHED"}


async def normalize_node(state: TriageGraphState) -> Dict[str, Any]:
    if state.get("status") == "FAILED":
        return {}
    logger.info(f"Starting graph normalization. Run ID: {state['run_id']}.")
    snapshot = EmailMessageRepository().get_by_message_id(state["message_id"])
    if snapshot is None:
        return {"status": "FAILED", "error": "No persisted message snapshot was found for normalization."}
    raw = RawMessage(
        ref=MessageRef(
            account_id=snapshot.account_id, folder=snapshot.folder, uid=snapshot.uid, message_id=snapshot.message_id
        ),
        sender=snapshot.sender,
        recipients=snapshot.recipients,
        cc_recipients=snapshot.cc_recipients,
        subject=snapshot.subject,
        body=snapshot.body,
        received_at=snapshot.received_at,
        headers={},
    )
    normalized = Normalizer().normalize(raw)
    AuditEventRepository().record(
        state["message_id"],
        state["run_id"],
        "NORMALIZED",
        {"truncated": normalized.truncated, "normalized_length": normalized.normalized_length},
    )
    logger.info("Graph normalization successfully completed.")
    return {
        "status": "NORMALIZED",
        "normalized_subject": normalized.subject,
        "normalized_body": normalized.body,
    }


async def classify_node(state: TriageGraphState) -> Dict[str, Any]:
    if state.get("status") == "FAILED":
        return {}
    logger.info(f"Starting graph classification. Run ID: {state['run_id']}.")
    normalized_email = NormalizedEmail(
        message_id=state["message_id"],
        subject=state.get("normalized_subject") or "",
        body=state.get("normalized_body") or "",
        sender_domain=None,
        truncated=False,
        original_length=0,
        normalized_length=len(state.get("normalized_body") or ""),
    )
    input_hash = hashlib.sha256(f"{normalized_email.subject}\n\n{normalized_email.body}".encode()).hexdigest()

    try:
        label = await Classifier().classify(normalized_email)
    except Exception as e:
        logger.error(f"Graph classification failed. Run ID: {state['run_id']}. Error: {e}")
        AuditEventRepository().record(
            state["message_id"],
            state["run_id"],
            "CLASSIFICATION_FAILED",
            {"prompt_version": "v1", "error": str(e)},
            payload_hash=input_hash,
        )
        return {"status": "FAILED", "error": str(e)}

    snapshot = EmailMessageRepository().get_by_message_id(state["message_id"])
    agreement_score = None
    if snapshot is not None:
        domain_match = _SENDER_DOMAIN_PATTERN.search(snapshot.sender)
        sender_domain = domain_match.group(1).lower() if domain_match else None
        agreement_score = Evaluator().evaluate(
            label=label,
            sender=snapshot.sender,
            sender_domain=sender_domain,
            subject=snapshot.subject,
            headers=snapshot.headers or {},
            injection_suspected=False,
        )

    ClassificationRepository().add(
        ClassificationModel(
            id=str(uuid.uuid4()),
            message_id=state["message_id"],
            label=label,
            agreement_score=agreement_score,
            model_version="v1",
            classified_at=datetime.now(UTC),
        )
    )
    EmailMessageRepository().update_status(state["message_id"], MessageStatus.CLASSIFIED)
    AuditEventRepository().record(
        state["message_id"],
        state["run_id"],
        "CLASSIFIED",
        {"prompt_version": "v1", "label": label, "agreement_score": agreement_score},
        payload_hash=input_hash,
    )
    logger.info(f"Graph classification successfully completed. Label: {label}.")
    return {"status": "CLASSIFIED", "classification_label": label}


async def prioritize_node(state: TriageGraphState) -> Dict[str, Any]:
    if state.get("status") == "FAILED":
        return {}
    logger.info(f"Starting graph prioritization. Run ID: {state['run_id']}.")
    label = state.get("classification_label")
    if not label:
        return {"status": "FAILED", "error": "No classification label is available to assess priority."}
    snapshot = EmailMessageRepository().get_by_message_id(state["message_id"])
    if snapshot is None:
        return {"status": "FAILED", "error": "No persisted message snapshot was found for prioritization."}

    signals = PriorityDeterministicSignals().evaluate(
        account_id=snapshot.account_id,
        sender=snapshot.sender,
        recipients=snapshot.recipients,
        subject=snapshot.subject,
        body=snapshot.body,
        headers=snapshot.headers or {},
        received_at=snapshot.received_at,
    )

    output = await Prioritizer(OllamaLLMProvider()).assess(
        signals=signals,
        classification_label=label,
        subject=state.get("normalized_subject") or snapshot.subject,
        body=state.get("normalized_body") or snapshot.body,
    )

    needs_human = output is None
    if output is None:
        level = _fallback_priority_level(signals)
        rationale = "Reasoning model output failed schema validation after the retry; falling back to deterministic signals."
        requires_reply = signals["direct_recipient"]
    else:
        level = PriorityLevel(output.level.upper())
        rationale = output.rationale
        requires_reply = output.requires_reply

    PriorityAssessmentRepository().add(
        PriorityAssessmentModel(
            id=str(uuid.uuid4()),
            message_id=state["message_id"],
            level=level,
            rationale=rationale,
            requires_reply=requires_reply,
            signals=signals,
            needs_human=needs_human,
            model_version="v1",
            assessed_at=datetime.now(UTC),
        )
    )
    EmailMessageRepository().update_status(state["message_id"], MessageStatus.PRIORITIZED)
    AuditEventRepository().record(
        state["message_id"],
        state["run_id"],
        "PRIORITIZED",
        {"level": level.value, "needs_human": needs_human, "signals": signals},
    )
    logger.info(f"Graph prioritization successfully completed. Level: {level.value}.")
    return {"status": "PRIORITIZED", "priority_level": level.value, "requires_reply": requires_reply}


async def decide_actions_node(state: TriageGraphState) -> Dict[str, Any]:
    if state.get("status") == "FAILED":
        return {}
    logger.info(f"Starting graph decision. Run ID: {state['run_id']}.")
    label = state.get("classification_label")
    if not label:
        return {"status": "FAILED", "error": "No classification label is available to decide an action."}

    action = ProposedActionModel(
        id=str(uuid.uuid4()),
        message_id=state["message_id"],
        run_id=state["run_id"],
        action_type=ProposedActionType.APPLY_LABEL,
        payload={"label": label},
        status=ProposedActionStatus.PENDING,
        risk=None,
        agreement_score=None,
        created_at=datetime.now(UTC),
    )
    ProposedActionRepository().add(action)
    AuditEventRepository().record(
        state["message_id"],
        state["run_id"],
        "ACTION_PROPOSED",
        {"action_id": action.id, "action_type": action.action_type.value, "payload": action.payload},
    )
    logger.info(f"Graph decision successfully completed. Proposed action: {action.action_type.value}.")
    return {"status": "DECIDED", "proposed_action_ids": [action.id]}


async def gate_labels_node(state: TriageGraphState) -> Dict[str, Any]:
    if state.get("status") == "FAILED":
        return {}
    logger.info(f"Starting label approval gate. Run ID: {state['run_id']}.")
    EmailMessageRepository().update_status(state["message_id"], MessageStatus.AWAITING_APPROVAL)
    AuditEventRepository().record(
        state["message_id"],
        state["run_id"],
        "AWAITING_APPROVAL",
        {"proposed_action_ids": state["proposed_action_ids"]},
    )

    decision = interrupt(
        {
            "message_id": state["message_id"],
            "proposed_action_ids": state["proposed_action_ids"],
        }
    )

    outcomes = decision if isinstance(decision, dict) else {}
    repository = ProposedActionRepository()
    for action_id in state.get("proposed_action_ids", []):
        outcome = outcomes.get(action_id, "rejected")
        new_status = ProposedActionStatus.APPROVED if outcome == "approved" else ProposedActionStatus.REJECTED
        repository.update_status(action_id, new_status)

    AuditEventRepository().record(
        state["message_id"],
        state["run_id"],
        "GATE_RESOLVED",
        {"outcomes": outcomes},
    )
    logger.info("Label approval gate successfully resumed.")
    return {"status": "GATED"}


async def gate_next_action_node(state: TriageGraphState) -> Dict[str, Any]:
    if state.get("status") == "FAILED":
        return {}
    logger.info(f"Starting next-action gate. Run ID: {state['run_id']}.")
    EmailMessageRepository().update_status(state["message_id"], MessageStatus.AWAITING_APPROVAL)
    AuditEventRepository().record(
        state["message_id"],
        state["run_id"],
        "AWAITING_NEXT_ACTION",
        {"requires_reply_hint": state.get("requires_reply"), "priority_level_hint": state.get("priority_level")},
    )

    decision = interrupt(
        {
            "message_id": state["message_id"],
            "requires_reply_hint": state.get("requires_reply"),
            "priority_level_hint": state.get("priority_level"),
        }
    )
    next_action = decision.get("next_action", "none") if isinstance(decision, dict) else "none"

    updated_action_ids = list(state.get("proposed_action_ids", []))
    if next_action in ("archive", "mark_spam"):
        destination_folder = IMAP_ARCHIVE_FOLDER if next_action == "archive" else IMAP_SPAM_FOLDER
        action_type = ProposedActionType.ARCHIVE if next_action == "archive" else ProposedActionType.MARK_SPAM
        action = ProposedActionModel(
            id=str(uuid.uuid4()),
            message_id=state["message_id"],
            run_id=state["run_id"],
            action_type=action_type,
            payload={"destination_folder": destination_folder or ""},
            status=ProposedActionStatus.APPROVED,
            risk=None,
            agreement_score=None,
            created_at=datetime.now(UTC),
        )
        ProposedActionRepository().add(action)
        updated_action_ids.append(action.id)

    AuditEventRepository().record(
        state["message_id"], state["run_id"], "NEXT_ACTION_RESOLVED", {"next_action": next_action}
    )
    logger.info(f"Next-action gate successfully resumed. Choice: {next_action}.")
    return {"status": "NEXT_ACTION_RESOLVED", "next_action": next_action, "proposed_action_ids": updated_action_ids}


async def draft_reply_node(state: TriageGraphState) -> Dict[str, Any]:
    if state.get("status") == "FAILED":
        return {}
    logger.info(f"Starting graph draft generation. Run ID: {state['run_id']}.")
    snapshot = EmailMessageRepository().get_by_message_id(state["message_id"])
    if snapshot is None:
        return {"status": "FAILED", "error": "No persisted message snapshot was found for drafting."}

    policy = PolicyLoader().load()
    label = state.get("classification_label") or ""
    existing_versions = DraftReplyRepository().list_by_message_id(state["message_id"])
    next_version = len(existing_versions) + 1
    feedback = state.get("draft_feedback")

    output = await Drafter(OllamaLLMProvider(), max_length_chars=policy.reply.max_length_chars).draft(
        subject=state.get("normalized_subject") or snapshot.subject,
        body=state.get("normalized_body") or snapshot.body,
        classification_label=label,
        feedback=feedback,
    )
    if output is None:
        return {"status": "FAILED", "error": "Draft reply generation failed schema validation after the retry."}

    diff_from_previous = None
    if existing_versions:
        diff_from_previous = "\n".join(
            difflib.unified_diff(
                existing_versions[-1].body.splitlines(),
                output.body.splitlines(),
                lineterm="",
            )
        )

    draft = DraftReplyRepository().add(
        DraftReplyModel(
            id=str(uuid.uuid4()),
            message_id=state["message_id"],
            version=next_version,
            body=output.body,
            edited_by_human=False,
            diff_from_previous=diff_from_previous,
            created_at=datetime.now(UTC),
        )
    )

    action = ProposedActionModel(
        id=str(uuid.uuid4()),
        message_id=state["message_id"],
        run_id=state["run_id"],
        action_type=ProposedActionType.SAVE_DRAFT,
        payload={
            "draft_id": draft.id,
            "version": draft.version,
            "recipient": snapshot.sender,
            "subject": output.subject,
            "body": output.body,
        },
        status=ProposedActionStatus.PENDING,
        risk=None,
        agreement_score=None,
        created_at=datetime.now(UTC),
    )
    ProposedActionRepository().add(action)
    EmailMessageRepository().update_status(state["message_id"], MessageStatus.DRAFTED)
    AuditEventRepository().record(
        state["message_id"],
        state["run_id"],
        "DRAFTED",
        {"draft_id": draft.id, "version": draft.version, "action_id": action.id},
    )
    logger.info(f"Graph draft generation successfully completed. Version: {draft.version}.")
    updated_action_ids = state.get("proposed_action_ids", []) + [action.id]
    return {
        "status": "DRAFTED",
        "draft_action_id": action.id,
        "proposed_action_ids": updated_action_ids,
        "draft_feedback": None,
    }


async def gate_draft_node(state: TriageGraphState) -> Dict[str, Any]:
    if state.get("status") == "FAILED":
        return {}
    logger.info(f"Starting draft approval gate. Run ID: {state['run_id']}.")
    action_id = state["draft_action_id"]
    action = ProposedActionRepository().get_by_id(action_id)

    decision = interrupt(
        {
            "message_id": state["message_id"],
            "draft_action_id": action_id,
            "draft_payload": action.payload if action else None,
        }
    )
    outcome = decision.get("outcome") if isinstance(decision, dict) else "rejected"

    if outcome == "approved":
        ProposedActionRepository().update_status(action_id, ProposedActionStatus.APPROVED)
        AuditEventRepository().record(
            state["message_id"], state["run_id"], "GATE_DRAFT_RESOLVED", {"outcome": "approved"}
        )
        logger.info("Draft approval gate resolved as approved.")
        return {"status": "DRAFT_APPROVED"}

    if outcome == "edited":
        existing_versions = DraftReplyRepository().list_by_message_id(state["message_id"])
        previous = existing_versions[-1]
        edited_body = decision.get("body") or ""
        edited = DraftReplyRepository().add(
            DraftReplyModel(
                id=str(uuid.uuid4()),
                message_id=state["message_id"],
                version=previous.version + 1,
                body=edited_body,
                edited_by_human=True,
                diff_from_previous="\n".join(
                    difflib.unified_diff(previous.body.splitlines(), edited_body.splitlines(), lineterm="")
                ),
                created_at=datetime.now(UTC),
            )
        )
        ProposedActionRepository().update_status(action_id, ProposedActionStatus.APPROVED)
        AuditEventRepository().record(
            state["message_id"],
            state["run_id"],
            "GATE_DRAFT_RESOLVED",
            {"outcome": "edited", "draft_id": edited.id, "version": edited.version},
        )
        logger.info("Draft approval gate resolved as edited.")
        return {"status": "DRAFT_APPROVED"}

    ProposedActionRepository().update_status(action_id, ProposedActionStatus.REJECTED)
    AuditEventRepository().record(
        state["message_id"], state["run_id"], "GATE_DRAFT_RESOLVED", {"outcome": "rejected"}
    )
    logger.info("Draft approval gate resolved as rejected.")
    return {"status": "DRAFT_REJECTED"}


async def prepare_send_node(state: TriageGraphState) -> Dict[str, Any]:
    if state.get("status") == "FAILED":
        return {}
    logger.info(f"Starting send action preparation. Run ID: {state['run_id']}.")
    snapshot = EmailMessageRepository().get_by_message_id(state["message_id"])
    draft = DraftReplyRepository().list_by_message_id(state["message_id"])[-1]

    action = ProposedActionModel(
        id=str(uuid.uuid4()),
        message_id=state["message_id"],
        run_id=state["run_id"],
        action_type=ProposedActionType.SEND_REPLY,
        payload={
            "draft_id": draft.id,
            "version": draft.version,
            "recipient": snapshot.sender if snapshot else None,
            "subject": f"Re: {snapshot.subject}" if snapshot else "",
            "body": draft.body,
        },
        status=ProposedActionStatus.PENDING,
        risk=None,
        agreement_score=None,
        created_at=datetime.now(UTC),
    )
    ProposedActionRepository().add(action)
    EmailMessageRepository().update_status(state["message_id"], MessageStatus.AWAITING_APPROVAL)
    AuditEventRepository().record(
        state["message_id"], state["run_id"], "AWAITING_SEND_APPROVAL", {"send_action_id": action.id}
    )
    logger.info(f"Send action preparation successfully completed. Action ID: {action.id}.")
    updated_action_ids = state.get("proposed_action_ids", []) + [action.id]
    return {"status": "SEND_PREPARED", "send_action_id": action.id, "proposed_action_ids": updated_action_ids}


async def gate_send_node(state: TriageGraphState) -> Dict[str, Any]:
    if state.get("status") == "FAILED":
        return {}
    logger.info(f"Starting send approval gate. Run ID: {state['run_id']}.")
    action_id = state["send_action_id"]
    action = ProposedActionRepository().get_by_id(action_id)

    decision = interrupt(
        {
            "message_id": state["message_id"],
            "send_action_id": action_id,
            "payload": action.payload if action else {},
        }
    )
    outcome = decision.get("outcome") if isinstance(decision, dict) else "rejected"
    new_status = ProposedActionStatus.APPROVED if outcome == "approved" else ProposedActionStatus.REJECTED
    ProposedActionRepository().update_status(action_id, new_status)
    AuditEventRepository().record(
        state["message_id"], state["run_id"], "GATE_SEND_RESOLVED", {"outcome": outcome}
    )
    logger.info(f"Send approval gate successfully resumed. Outcome: {outcome}.")
    return {"status": "SEND_GATED", "send_action_id": action_id}


def make_execute_node(provider: MailProvider) -> Callable[[TriageGraphState], Awaitable[Dict[str, Any]]]:
    """Build an execute node bound to the supplied mail provider."""

    async def execute_node(state: TriageGraphState) -> Dict[str, Any]:
        if state.get("status") == "FAILED":
            return {}
        logger.info(f"Starting graph execution. Run ID: {state['run_id']}.")
        repository = ProposedActionRepository()
        audit_repository = AuditEventRepository()
        snapshot = EmailMessageRepository().get_by_message_id(state["message_id"])
        message_ref = MessageRef(
            account_id=snapshot.account_id if snapshot else "",
            folder=snapshot.folder if snapshot else "INBOX",
            uid=snapshot.uid if snapshot else 0,
            message_id=state["message_id"],
        )
        executed = 0
        failed = 0
        for action_id in state.get("proposed_action_ids", []):
            action = repository.get_by_id(action_id)
            if action is None or action.status != ProposedActionStatus.APPROVED:
                continue
            try:
                if action.action_type == ProposedActionType.APPLY_LABEL:
                    provider.apply_label(message_ref, action.payload.get("label", ""))
                elif action.action_type in (ProposedActionType.ARCHIVE, ProposedActionType.MARK_SPAM):
                    destination_folder = action.payload.get("destination_folder", "")
                    if destination_folder:
                        provider.move(message_ref, destination_folder)
                elif action.action_type == ProposedActionType.SAVE_DRAFT:
                    # Approving the draft here only confirms its content; the draft is never
                    # persisted as a standalone artifact on the mailbox. Only the final,
                    # approved SEND_REPLY actually writes to the mailbox.
                    pass
                elif action.action_type == ProposedActionType.SEND_REPLY:
                    latest_draft = DraftReplyRepository().list_by_message_id(state["message_id"])[-1]
                    idempotency_key = hashlib.sha256(
                        f"{state['message_id']}:{latest_draft.version}".encode()
                    ).hexdigest()
                    provider.send(
                        OutgoingMessage(
                            in_reply_to_message_id=state["message_id"],
                            recipients=[action.payload.get("recipient", "")],
                            subject=action.payload.get("subject", ""),
                            body=latest_draft.body,
                            draft_version=latest_draft.version,
                        ),
                        idempotency_key,
                    )
                    provider.mark_read(message_ref)
                    audit_repository.record(
                        state["message_id"],
                        state["run_id"],
                        "ACTION_EXECUTED",
                        {"action_id": "auto-mark-read", "action_type": ProposedActionType.MARK_READ.value},
                    )
            except Exception as e:
                failed += 1
                logger.error(f"Action execution failed. Action ID: {action_id}. Error: {e}")
                audit_repository.record(
                    state["message_id"],
                    state["run_id"],
                    "ACTION_EXECUTION_FAILED",
                    {"action_id": action_id, "action_type": action.action_type.value, "error": str(e)},
                )
                continue
            executed += 1
            audit_repository.record(
                state["message_id"],
                state["run_id"],
                "ACTION_EXECUTED",
                {"action_id": action_id, "action_type": action.action_type.value},
            )
        logger.info(f"Graph execution successfully completed. Actions executed: {executed}. Failed: {failed}.")
        return {"status": "EXECUTED"}

    return execute_node


async def persist_node(state: TriageGraphState) -> Dict[str, Any]:
    logger.info(f"Starting graph persistence. Run ID: {state['run_id']}.")
    if state.get("status") == "FAILED":
        EmailMessageRepository().update_status(state["message_id"], MessageStatus.FAILED)
        final_status = MessageStatus.FAILED
    else:
        repository = ProposedActionRepository()
        action_statuses = [
            action.status
            for action_id in state.get("proposed_action_ids", [])
            if (action := repository.get_by_id(action_id)) is not None
        ]
        if any(status == ProposedActionStatus.PENDING for status in action_statuses):
            final_status = MessageStatus.AWAITING_APPROVAL
        elif action_statuses and all(status == ProposedActionStatus.REJECTED for status in action_statuses):
            final_status = MessageStatus.REJECTED
        else:
            final_status = MessageStatus.DONE
        EmailMessageRepository().update_status(state["message_id"], final_status)

    AuditEventRepository().record(
        state["message_id"],
        state["run_id"],
        "RUN_COMPLETED",
        {"final_status": final_status.value, "error": state.get("error")},
    )
    logger.info(f"Graph persistence successfully completed. Final status: {final_status.value}.")
    return {"status": final_status.value}
