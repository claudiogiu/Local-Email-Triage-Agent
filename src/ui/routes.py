import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from src.config.constants import WEB_TEMPLATES_DIR
from src.ui.client import ApiClient

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(WEB_TEMPLATES_DIR))

_TERMINAL_MESSAGE_STATUSES = {"DONE", "REJECTED", "CLOSED", "FAILED"}


def _pick_active_action(actions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for action in reversed(actions):
        if action.get("action_status") == "PENDING":
            return action
    return None


def _label_already_resolved(actions: List[Dict[str, Any]]) -> bool:
    return any(
        action.get("action_type") == "APPLY_LABEL" and action.get("action_status") != "PENDING"
        for action in actions
    )


def _fingerprint_of(phase: str, action: Optional[Dict[str, Any]], message_status: Optional[str]) -> str:
    action_id = action.get("proposed_action_id", "") if action else ""
    action_status = action.get("action_status", "") if action else ""
    return f"{phase}:{action_id}:{action_status}:{message_status}"


async def _render_card_status(
    request: Request, message_id: str, known_fingerprint: Optional[str] = None
) -> HTMLResponse:
    detail = await ApiClient().get_message_detail(message_id)
    actions = detail.get("actions", [])
    active_action = _pick_active_action(actions)
    message_status = detail.get("message_status")

    if message_status in _TERMINAL_MESSAGE_STATUSES:
        phase = "terminal"
    elif active_action is not None:
        phase = "action"
    elif _label_already_resolved(actions):
        phase = "next_action"
    else:
        phase = "processing"

    fingerprint = _fingerprint_of(phase, active_action, message_status)

    if known_fingerprint is not None and known_fingerprint == fingerprint:
        # Nothing changed since the caller's last render: tell HTMX to leave the
        # existing card untouched instead of replacing it, so an unchanged card
        # never visibly flickers on every polling tick.
        response = HTMLResponse(content="")
        response.headers["HX-Reswap"] = "none"
        return response

    return templates.TemplateResponse(
        request,
        "card_status.html",
        {
            "message_id": message_id,
            "detail": detail,
            "action": active_action if phase == "action" else None,
            "phase": phase,
            "polling": phase != "terminal",
            "fingerprint": fingerprint,
        },
    )


@router.get("/", response_class=HTMLResponse, tags=["Pages"])
async def render_intro(request: Request) -> HTMLResponse:
    """
    Render the introductory landing page, showing a mailbox sign-in form
    until working credentials are configured.
    """
    try:
        mailbox_status = await ApiClient().get_mailbox_status()
    except Exception as e:
        logger.error(f"Mailbox status retrieval failed: {e}")
        mailbox_status = {"connected": False, "email": None}
    return templates.TemplateResponse(request, "intro.html", {"mailbox": mailbox_status, "error": None})


@router.post("/connect", response_class=HTMLResponse, tags=["Pages"])
async def connect_mailbox(request: Request, email: str = Form(...), imap_password: str = Form(...)) -> HTMLResponse:
    """
    Submit mailbox sign-in credentials and re-render the landing page with
    the resulting connection state.
    """
    result = await ApiClient().submit_mailbox_credentials(email, imap_password)
    if result.get("connected"):
        return templates.TemplateResponse(
            request, "intro.html", {"mailbox": result, "error": None}
        )
    return templates.TemplateResponse(
        request,
        "intro.html",
        {"mailbox": {"connected": False, "email": None}, "error": result.get("detail"), "attempted_email": email},
    )


@router.post("/logout", response_class=HTMLResponse, tags=["Pages"])
async def logout(request: Request) -> HTMLResponse:
    """
    Sign out of the mailbox and re-render the landing page's sign-in form.
    """
    await ApiClient().logout_mailbox()
    return templates.TemplateResponse(request, "intro.html", {"mailbox": {"connected": False, "email": None}, "error": None})


@router.get("/inbox", response_class=HTMLResponse, tags=["Pages"])
async def render_inbox(request: Request) -> HTMLResponse:
    """
    Render the inbox page listing every currently-unread message.
    """
    return templates.TemplateResponse(request, "inbox.html", {})


@router.get("/partials/inbox", response_class=HTMLResponse, tags=["Partials"])
async def render_inbox_partial(request: Request) -> HTMLResponse:
    """
    Render the unread mailbox scan as an HTML fragment of selectable cards.
    """
    try:
        result = await ApiClient().list_unread()
        messages = [
            item
            for item in result.get("messages", [])
            if item.get("message_status") not in _TERMINAL_MESSAGE_STATUSES
        ]
        error = None
    except Exception as e:
        logger.error(f"Unread inbox retrieval from the API failed: {e}")
        messages = []
        error = "Unable To Read The Mailbox Right Now. Please Try Again Shortly."
    return templates.TemplateResponse(request, "inbox_fragment.html", {"messages": messages, "error": error})


@router.post("/cards/trigger", response_class=HTMLResponse, tags=["Cards"])
async def trigger_card(
    request: Request, folder: str = Form(...), uid: int = Form(...), message_id: str = Form(...)
) -> HTMLResponse:
    """
    Manually start triage for a single unread message and render its
    resulting live status card.
    """
    await ApiClient().trigger_triage(folder, uid, message_id)
    return await _render_card_status(request, message_id)


@router.get("/cards/{message_id}/status", response_class=HTMLResponse, tags=["Cards"])
async def card_status(request: Request, message_id: str, since: Optional[str] = None) -> HTMLResponse:
    """
    Render the current live status card of a single message, polled
    periodically while its triage run is in progress. If `since` matches the
    card's current fingerprint, nothing is re-rendered.
    """
    return await _render_card_status(request, message_id, known_fingerprint=since)


@router.get("/cards/{message_id}/edit-draft", response_class=HTMLResponse, tags=["Cards"])
async def render_edit_draft(request: Request, message_id: str) -> HTMLResponse:
    """
    Render a stable, non-refreshing text editor for the message's pending
    draft reply, so in-progress typing is never lost to polling.
    """
    detail = await ApiClient().get_message_detail(message_id)
    action = _pick_active_action(detail.get("actions", []))
    if action is None or action.get("action_type") != "SAVE_DRAFT":
        return await _render_card_status(request, message_id)
    return templates.TemplateResponse(
        request, "card_edit_draft.html", {"message_id": message_id, "detail": detail, "action": action}
    )


@router.post("/actions/{action_id}/approve", tags=["Actions"])
async def approve_action(action_id: str, action_type: str) -> Response:
    """
    Approve a pending action, routing to the label, draft, or send endpoint
    according to its type.
    """
    client = ApiClient()
    if action_type == "APPLY_LABEL":
        await client.resolve_label(action_id, approved=True)
    elif action_type == "SAVE_DRAFT":
        await client.resolve_draft(action_id, {"outcome": "approved"})
    elif action_type == "SEND_REPLY":
        await client.resolve_send(action_id, approved=True)
    return Response(status_code=204)


@router.post("/actions/{action_id}/reject", tags=["Actions"])
async def reject_action(action_id: str, action_type: str) -> Response:
    """
    Reject a pending action, routing to the label, draft, or send endpoint
    according to its type.
    """
    client = ApiClient()
    if action_type == "APPLY_LABEL":
        await client.resolve_label(action_id, approved=False)
    elif action_type == "SAVE_DRAFT":
        await client.resolve_draft(action_id, {"outcome": "rejected"})
    elif action_type == "SEND_REPLY":
        await client.resolve_send(action_id, approved=False)
    return Response(status_code=204)


@router.post("/cards/{message_id}/next-action", response_class=HTMLResponse, tags=["Cards"])
async def resolve_next_action(request: Request, message_id: str, next_action: str = Form(...)) -> HTMLResponse:
    """
    Resolve the post-label next-action gate for a single message and render
    its resulting live status card.
    """
    await ApiClient().resolve_next_action(message_id, next_action)
    return await _render_card_status(request, message_id)


@router.post("/actions/{action_id}/edit", response_class=HTMLResponse, tags=["Actions"])
async def edit_draft(
    request: Request, action_id: str, message_id: str = Form(...), subject: str = Form(...), body: str = Form(...)
) -> HTMLResponse:
    """
    Approve a pending draft reply with a human-edited subject and body, and
    render the resulting live status card.
    """
    await ApiClient().resolve_draft(action_id, {"outcome": "edited", "subject": subject, "body": body})
    return await _render_card_status(request, message_id)


@router.post("/messages/{message_id}/archive", tags=["Actions"])
async def archive_message(message_id: str) -> Response:
    """
    Archive a triaged message immediately, on direct user request.
    """
    await ApiClient().archive_message(message_id)
    return Response(status_code=204)


@router.post("/messages/{message_id}/mark-spam", tags=["Actions"])
async def mark_message_spam(message_id: str) -> Response:
    """
    Mark a triaged message as spam immediately, on direct user request.
    """
    await ApiClient().mark_spam(message_id)
    return Response(status_code=204)
