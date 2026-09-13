import logging
import re
from typing import Optional, Pattern

from src.config.constants import OLLAMA_CLASSIFIER_MODEL
from src.domain.entities import NormalizedEmail
from src.services.ollama_service import OllamaService
from src.triage.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)

ALLOWED_LABELS = (
    "AI/Billing",
    "AI/Newsletter",
    "AI/Work",
    "AI/Personal",
    "AI/Promotional",
    "AI/Security",
    "AI/Shipping",
    "AI/Travel",
    "AI/Spam",
    "AI/Other",
)

_OUTPUT_PATTERN: Pattern[str] = re.compile(r"<output>\s*(.*?)\s*</output>", re.DOTALL)


class Classifier:
    """
    Interface for invoking the distilled email classification model through
    Ollama and parsing its constrained enum output, per the immutable model
    contract of src/prompts/classify/v1.txt.

    Attributes:
        model (str): Identifier of the classifier model registered with Ollama.
        _service (OllamaService): Client used to invoke the classifier model.
        _system_prompt (str): Verbatim system prompt loaded from the versioned prompt asset.

    Methods:
        classify(email: NormalizedEmail) -> str:
            Determines the classifier's predicted label for the supplied normalized message.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        service: Optional[OllamaService] = None,
        prompt_registry: Optional[PromptRegistry] = None,
    ) -> None:
        resolved_model = model or OLLAMA_CLASSIFIER_MODEL
        if not resolved_model:
            raise ValueError("The OLLAMA_CLASSIFIER_MODEL environment variable is not configured.")
        self.model: str = resolved_model
        self._service: OllamaService = service or OllamaService()
        self._system_prompt: str = (prompt_registry or PromptRegistry()).load("classify", "v1")
        logger.info(f"Classifier initialization completed. Model: {self.model}.")

    async def classify(self, email: NormalizedEmail) -> str:
        if not email.body:
            raise ValueError("The provided email body for classification is empty.")

        question = f"Subject: {email.subject}\n\n{email.body}"
        user_message = f"\n\nNow for the real task, classify the following example\n<question>{question}</question>\n"

        logger.info(f"Starting email classification through Ollama. Message ID: {email.message_id}.")
        raw_output = await self._service.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            think=False,
        )

        match = _OUTPUT_PATTERN.search(raw_output)
        if not match:
            raise RuntimeError(f"Ollama did not return a valid classification label. Raw response: {raw_output!r}.")

        label = match.group(1).strip()
        if label not in ALLOWED_LABELS:
            raise RuntimeError(f"Ollama returned a classification label outside the allowed catalogue: {label!r}.")

        logger.info(f"Email classification successfully completed. Label: {label}.")
        return label
