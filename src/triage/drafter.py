import logging
from typing import Optional

from jinja2 import Template
from pydantic import BaseModel

from src.domain.entities import CompletionRequest
from src.domain.ports import LLMProvider
from src.triage.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)


class DraftOutput(BaseModel):
    """Schema-validated output of the reasoning model's reply-drafting invocation for a single message."""

    subject: str
    body: str


class Drafter:
    """
    Interface for invoking the reasoning model to draft a reply to a message,
    rendering the classification, original content, tone, and any
    regeneration feedback into the prompt, and validating the model's
    response against DraftOutput.

    Attributes:
        _provider (LLMProvider): Reasoning model provider used to invoke the structured completion.
        _prompt_template (str): Raw Jinja2 template loaded from the versioned prompt asset.
        _max_length_chars (int): Upper bound enforced on the drafted reply body.

    Methods:
        draft(subject: str, body: str, classification_label: str, tone: str, feedback: Optional[str]) -> Optional[DraftOutput]:
            Produces the validated draft reply for the supplied message, truncating an over-length body, or None if validation fails twice.
    """

    def __init__(
        self,
        provider: LLMProvider,
        prompt_registry: Optional[PromptRegistry] = None,
        max_length_chars: int = 1200,
    ) -> None:
        self._provider: LLMProvider = provider
        self._prompt_template: str = (prompt_registry or PromptRegistry()).load(
            "draft_reply", "v1", extension="jinja"
        )
        self._max_length_chars: int = max_length_chars

    async def draft(
        self,
        subject: str,
        body: str,
        classification_label: str,
        tone: str = "professional and concise",
        feedback: Optional[str] = None,
    ) -> Optional[DraftOutput]:
        user_message = Template(self._prompt_template).render(
            classification_label=classification_label,
            subject=subject,
            body=body,
            tone=tone,
            feedback=feedback,
        )
        request = CompletionRequest(
            system_prompt="You are a precise, professional email assistant drafting replies on behalf of the user.",
            user_message=user_message,
            temperature=0.2,
            model=None,
            think=False,
        )
        result = await self._provider.structured(request, DraftOutput)
        if result is None:
            logger.error("Draft reply generation degraded to needs_human after exhausting the retry.")
            return None
        if len(result.body) > self._max_length_chars:
            truncated_body = result.body[: self._max_length_chars].rsplit(" ", 1)[0]
            logger.info(f"Drafted reply truncated to the configured length limit. Limit: {self._max_length_chars}.")
            result = DraftOutput(subject=result.subject, body=truncated_body)
        logger.info("Draft reply generation successfully completed.")
        return result
