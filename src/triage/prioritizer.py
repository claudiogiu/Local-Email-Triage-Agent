import logging
import re
from datetime import datetime
from email.utils import parseaddr
from typing import Dict, List, Literal, Optional, Pattern

from jinja2 import Template
from pydantic import BaseModel, Field

from src.domain.entities import CompletionRequest
from src.domain.ports import LLMProvider
from src.persistence.repositories import EmailMessageRepository
from src.triage.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)

_DEADLINE_KEYWORD_PATTERN: Pattern[str] = re.compile(
    r"\burgent\w*|\basap\b|\bdeadline\b|\bscadenza\b|\bimmediat\w*|\bpriorit[aà]\b|\bentro (oggi|domani|stasera)\b",
    re.IGNORECASE,
)


class PriorityDeterministicSignals:
    """
    Interface for computing deterministic priority signals from a message's
    envelope, content, and history, independent of any model judgment. These
    signals are fused with the reasoning model's assessment in a later step.

    Attributes:
        None.

    Methods:
        _direct_recipient_signal(account_id: str, recipients: List[str]) -> bool:
            Determines whether the account was addressed directly rather than only in copy.

        _known_sender_signal(sender: str) -> bool:
            Determines whether the sender has appeared in the account's own message history before.

        _active_thread_signal(headers: Dict[str, str]) -> bool:
            Determines whether the message references an earlier message already present in the account's history.

        _deadline_keyword_signal(subject: str, body: str) -> bool:
            Determines whether the subject or body contains a recognized deadline-related keyword.

        _business_hours_signal(received_at: datetime) -> bool:
            Determines whether the message arrived during typical business hours on a weekday.

        evaluate(account_id: str, sender: str, recipients: List[str], subject: str, body: str, headers: Dict[str, str], received_at: datetime) -> Dict[str, bool]:
            Computes every deterministic priority signal for the supplied message.
    """

    def _direct_recipient_signal(self, account_id: str, recipients: List[str]) -> bool:
        addresses = [parseaddr(recipient)[1].lower() for recipient in recipients]
        return account_id.lower() in addresses

    def _known_sender_signal(self, sender: str) -> bool:
        return len(EmailMessageRepository().list_by_sender(sender)) > 0

    def _active_thread_signal(self, headers: Dict[str, str]) -> bool:
        referenced_id = self._extract_thread_reference(headers)
        if referenced_id is None:
            return False
        return EmailMessageRepository().get_by_message_id(referenced_id) is not None

    @staticmethod
    def _extract_thread_reference(headers: Dict[str, str]) -> Optional[str]:
        references = headers.get("References", "").split()
        if references:
            return references[0].strip()
        in_reply_to = headers.get("In-Reply-To", "").strip()
        return in_reply_to or None

    def _deadline_keyword_signal(self, subject: str, body: str) -> bool:
        return bool(_DEADLINE_KEYWORD_PATTERN.search(f"{subject}\n{body}"))

    def _business_hours_signal(self, received_at: datetime) -> bool:
        return received_at.weekday() < 5 and 9 <= received_at.hour < 18

    def evaluate(
        self,
        account_id: str,
        sender: str,
        recipients: List[str],
        subject: str,
        body: str,
        headers: Dict[str, str],
        received_at: datetime,
    ) -> Dict[str, bool]:
        signals = {
            "direct_recipient": self._direct_recipient_signal(account_id, recipients),
            "known_sender": self._known_sender_signal(sender),
            "active_thread": self._active_thread_signal(headers),
            "deadline_keyword": self._deadline_keyword_signal(subject, body),
            "business_hours_arrival": self._business_hours_signal(received_at),
        }
        logger.info(f"Deterministic priority signals successfully computed. Signals: {signals}.")
        return signals


class PriorityOutput(BaseModel):
    """Schema-validated output of the reasoning model's priority assessment for a single message."""

    level: Literal["urgent", "high", "normal", "low"]
    rationale: str = Field(max_length=280)
    requires_reply: bool
    confidence: float = Field(ge=0, le=1)


class Prioritizer:
    """
    Interface for invoking the reasoning model to assess a message's priority,
    fusing deterministic signals into the rendered prompt and validating the
    model's response against PriorityOutput.

    Attributes:
        _provider (LLMProvider): Reasoning model provider used to invoke the structured completion.
        _prompt_template (str): Raw Jinja2 template loaded from the versioned prompt asset.

    Methods:
        assess(signals: Dict[str, bool], classification_label: str, subject: str, body: str) -> Optional[PriorityOutput]:
            Produces the validated priority assessment for the supplied message, or None if validation fails twice.
    """

    def __init__(self, provider: LLMProvider, prompt_registry: Optional[PromptRegistry] = None) -> None:
        self._provider: LLMProvider = provider
        self._prompt_template: str = (prompt_registry or PromptRegistry()).load("prioritize", "v1", extension="jinja")

    async def assess(
        self,
        signals: Dict[str, bool],
        classification_label: str,
        subject: str,
        body: str,
    ) -> Optional[PriorityOutput]:
        user_message = Template(self._prompt_template).render(
            classification_label=classification_label,
            subject=subject,
            body=body,
            **signals,
        )
        request = CompletionRequest(
            system_prompt="You are a precise, deterministic email triage assistant.",
            user_message=user_message,
            temperature=0.0,
            model=None,
            think=False,
        )
        result = await self._provider.structured(request, PriorityOutput)
        if result is None:
            logger.error("Priority assessment degraded to needs_human after exhausting the retry.")
            return None
        logger.info(f"Priority assessment successfully completed. Level: {result.level}.")
        return result
