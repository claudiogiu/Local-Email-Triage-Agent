import logging
from typing import Any, Dict, List, Optional

import httpx

from src.config.constants import OLLAMA_BASE_URL, OLLAMA_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class OllamaService:
    """
    Interface for invoking the locally hosted Ollama inference server over its
    HTTP API, covering chat completion, embedding generation, and model
    inventory retrieval.

    Attributes:
        base_url (str): Base URL of the Ollama inference server.
        timeout_seconds (int): Request timeout, in seconds, applied to every invocation.

    Methods:
        chat(model: str, messages: List[Dict[str, str]], temperature: float, think: bool) -> str:
            Requests a chat completion from the specified model and returns its textual content.
    """

    def __init__(self, base_url: Optional[str] = None, timeout_seconds: Optional[int] = None) -> None:
        resolved_base_url = base_url or OLLAMA_BASE_URL
        if not resolved_base_url:
            raise ValueError("The OLLAMA_BASE_URL environment variable is not configured.")
        self.base_url: str = resolved_base_url
        self.timeout_seconds: int = timeout_seconds or OLLAMA_TIMEOUT_SECONDS or 60
        logger.info(
            f"Ollama service initialization completed. "
            f"Base URL: {self.base_url}. "
            f"Timeout: {self.timeout_seconds} seconds. "
        )

    async def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        think: bool,
    ) -> str:
        if not messages:
            raise ValueError("The messages payload supplied to the chat invocation is empty.")
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": think,
            "options": {"temperature": temperature},
        }
        logger.info(f"Starting chat completion request to Ollama. Model: {model}.")
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        content = data.get("message", {}).get("content", "")
        logger.info("Chat completion request to Ollama successfully completed.")
        return content
