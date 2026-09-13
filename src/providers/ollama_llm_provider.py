import logging
import re
from typing import Optional, Pattern, Type, TypeVar

from pydantic import BaseModel, ValidationError

from src.config.constants import OLLAMA_REASONING_MODEL
from src.domain.entities import CompletionRequest, CompletionResult
from src.services.ollama_service import OllamaService

logger = logging.getLogger(__name__)

_JSON_OBJECT_PATTERN: Pattern[str] = re.compile(r"\{.*\}", re.DOTALL)

T = TypeVar("T", bound=BaseModel)


class OllamaLLMProvider:
    """
    Interface for invoking the locally hosted reasoning model through Ollama,
    implementing the LLMProvider port for free-form completion and for
    schema-validated structured completion with a single retry on failure.

    Attributes:
        model (str): Identifier of the reasoning model registered with Ollama.
        _service (OllamaService): Client used to invoke the reasoning model.

    Methods:
        _extract_json_object(text: str) -> str:
            Extracts the first JSON object literal found within a raw completion.

        complete(req: CompletionRequest) -> CompletionResult:
            Produces a free-form textual completion for the supplied request.

        structured(req: CompletionRequest, schema: Type[T]) -> Optional[T]:
            Produces a completion validated against the supplied schema, retrying once on failure.
    """

    def __init__(self, model: Optional[str] = None, service: Optional[OllamaService] = None) -> None:
        resolved_model = model or OLLAMA_REASONING_MODEL
        if not resolved_model:
            raise ValueError("The OLLAMA_REASONING_MODEL environment variable is not configured.")
        self.model: str = resolved_model
        self._service: OllamaService = service or OllamaService()

    def _extract_json_object(self, text: str) -> str:
        match = _JSON_OBJECT_PATTERN.search(text)
        if not match:
            raise ValueError("No JSON object literal was found in the completion.")
        return match.group(0)

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        logger.info(f"Starting reasoning model completion. Model: {req.model or self.model}.")
        text = await self._service.chat(
            model=req.model or self.model,
            messages=[
                {"role": "system", "content": req.system_prompt},
                {"role": "user", "content": req.user_message},
            ],
            temperature=req.temperature,
            think=req.think,
        )
        logger.info("Reasoning model completion successfully completed.")
        return CompletionResult(text=text)

    async def structured(self, req: CompletionRequest, schema: Type[T]) -> Optional[T]:
        result = await self.complete(req)
        try:
            return schema.model_validate_json(self._extract_json_object(result.text))
        except (ValidationError, ValueError) as first_error:
            logger.error(f"Structured completion failed validation on first attempt: {first_error}")
            first_error_message = str(first_error)

        retry_req = CompletionRequest(
            system_prompt=req.system_prompt,
            user_message=(
                f"{req.user_message}\n\n"
                f"Your previous response failed schema validation with this error:\n{first_error_message}\n"
                f"Return ONLY a single valid JSON object matching the required schema, with no other text."
            ),
            temperature=req.temperature,
            model=req.model,
            think=req.think,
        )
        retry_result = await self.complete(retry_req)
        try:
            return schema.model_validate_json(self._extract_json_object(retry_result.text))
        except (ValidationError, ValueError) as second_error:
            logger.error(f"Structured completion failed validation after retry: {second_error}")
            return None
