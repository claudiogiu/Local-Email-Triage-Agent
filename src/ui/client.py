import logging
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from src.config.constants import API_BASE_URL

logger = logging.getLogger(__name__)

_DRAFT_OUTCOME_PATH = {
    "approved": "approve",
    "edited": "edit",
    "rejected": "reject",
}


class ApiClient:
    """
    Interface for calling the Local Email Triage Agent's REST API from the
    UI process, translating browser-facing interactions into the underlying
    inbox, message, approval, draft, and send endpoints.

    Attributes:
        base_url (str): Base URL of the API service, reachable over the internal network.

    Methods:
        get_mailbox_status() -> Dict[str, Any]:
            Reports whether the mailbox currently has working sign-in credentials configured.

        submit_mailbox_credentials(email: str, imap_password: str) -> Dict[str, Any]:
            Verifies and stores mailbox sign-in credentials submitted through the UI.

        logout_mailbox() -> Dict[str, Any]:
            Clears the stored mailbox credentials and stops the polling scheduler.

        list_unread() -> Dict[str, Any]:
            Retrieves every currently-unread message from a live mailbox scan.

        trigger_triage(folder: str, uid: int, message_id: str) -> Dict[str, Any]:
            Manually starts a triage run for a single unread message.

        get_message_detail(message_id: str) -> Dict[str, Any]:
            Retrieves the current triage status and full action history of a single message.

        resolve_next_action(message_id: str, next_action: str) -> Dict[str, Any]:
            Resolves a suspended run's post-label next-action gate.

        resolve_label(action_id: str, approved: bool) -> Dict[str, Any]:
            Approves or rejects a pending label-application action.

        resolve_draft(action_id: str, decision: Dict[str, Any]) -> Dict[str, Any]:
            Resolves a pending draft reply gate with the supplied decision.

        resolve_send(action_id: str, approved: bool) -> Dict[str, Any]:
            Approves or rejects a pending message transmission.

        archive_message(message_id: str) -> Dict[str, Any]:
            Archives a triaged message immediately.

        mark_spam(message_id: str) -> Dict[str, Any]:
            Marks a triaged message as spam immediately.
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        resolved_base_url = base_url or API_BASE_URL
        if not resolved_base_url:
            raise ValueError("The API_BASE_URL environment variable is not configured.")
        self.base_url: str = resolved_base_url

    async def get_mailbox_status(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/api/v1/settings/mailbox-credentials")
            response.raise_for_status()
            return response.json()

    async def submit_mailbox_credentials(self, email: str, imap_password: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/settings/mailbox-credentials",
                json={"email": email, "imap_password": imap_password},
            )
            response.raise_for_status()
            return response.json()

    async def logout_mailbox(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"{self.base_url}/api/v1/settings/mailbox-credentials/logout")
            response.raise_for_status()
            return response.json()

    async def list_unread(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(f"{self.base_url}/api/v1/messages/unread")
            response.raise_for_status()
            return response.json()

    async def trigger_triage(self, folder: str, uid: int, message_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/messages/trigger",
                json={"folder": folder, "uid": uid, "message_id": message_id},
            )
            response.raise_for_status()
            return response.json()

    async def get_message_detail(self, message_id: str) -> Dict[str, Any]:
        encoded_message_id = quote(message_id, safe="")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/api/v1/messages/{encoded_message_id}")
            response.raise_for_status()
            return response.json()

    async def resolve_next_action(self, message_id: str, next_action: str) -> Dict[str, Any]:
        encoded_message_id = quote(message_id, safe="")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/messages/{encoded_message_id}/next-action",
                json={"next_action": next_action},
            )
            response.raise_for_status()
            return response.json()

    async def resolve_label(self, action_id: str, approved: bool) -> Dict[str, Any]:
        path = "approve" if approved else "reject"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.base_url}/api/v1/approvals/{action_id}/{path}")
            response.raise_for_status()
            return response.json()

    async def resolve_draft(self, action_id: str, decision: Dict[str, Any]) -> Dict[str, Any]:
        path = _DRAFT_OUTCOME_PATH.get(decision.get("outcome", ""), "reject")
        body = {key: value for key, value in decision.items() if key != "outcome"}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.base_url}/api/v1/drafts/{action_id}/{path}", json=body or None)
            response.raise_for_status()
            return response.json()

    async def resolve_send(self, action_id: str, approved: bool) -> Dict[str, Any]:
        path = "approve" if approved else "reject"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.base_url}/api/v1/sends/{action_id}/{path}")
            response.raise_for_status()
            return response.json()

    async def archive_message(self, message_id: str) -> Dict[str, Any]:
        encoded_message_id = quote(message_id, safe="")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.base_url}/api/v1/messages/{encoded_message_id}/archive")
            response.raise_for_status()
            return response.json()

    async def mark_spam(self, message_id: str) -> Dict[str, Any]:
        encoded_message_id = quote(message_id, safe="")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.base_url}/api/v1/messages/{encoded_message_id}/mark-spam")
            response.raise_for_status()
            return response.json()
