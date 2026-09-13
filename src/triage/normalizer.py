import logging
import re
from typing import Optional, Pattern

from bs4 import BeautifulSoup

from src.domain.entities import NormalizedEmail, RawMessage

logger = logging.getLogger(__name__)

_QUOTE_HEADER_PATTERN: Pattern[str] = re.compile(r"^On .+ wrote:\s*$", re.MULTILINE)
_ORIGINAL_MESSAGE_PATTERN: Pattern[str] = re.compile(
    r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.MULTILINE | re.IGNORECASE
)
_SIGNATURE_DELIMITER_PATTERN: Pattern[str] = re.compile(r"^--\s*$", re.MULTILINE)
_HIDDEN_STYLE_PATTERN: Pattern[str] = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)
_SENDER_DOMAIN_PATTERN: Pattern[str] = re.compile(r"@([\w.-]+)")


class Normalizer:
    """
    Interface for converting raw email payloads into sanitized textual
    representations suitable for downstream model invocation, enforcing
    the configured character budget and neutralizing untrusted markup.

    Attributes:
        max_characters (int): Upper bound applied to the normalized body length.

    Methods:
        _strip_markup(raw: str) -> str:
            Removes HTML structure, tracking artifacts, and quoted history from the payload.

        _neutralize_delimiters(text: str) -> str:
            Escapes prompt delimiter sequences occurring within untrusted content.

        normalize(raw: RawMessage) -> NormalizedEmail:
            Produces the sanitized, budget-constrained representation of the supplied message.
    """

    def __init__(self, max_characters: int = 8000) -> None:
        self.max_characters: int = max_characters
        logger.info(f"Normalizer initialized with a character budget of {self.max_characters}.")

    def _strip_markup(self, raw: str) -> str:
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        for tag in soup.find_all("img"):
            tag.decompose()
        for tag in soup.find_all(style=_HIDDEN_STYLE_PATTERN):
            tag.decompose()
        text = soup.get_text(separator=" ")

        for pattern in (_QUOTE_HEADER_PATTERN, _ORIGINAL_MESSAGE_PATTERN, _SIGNATURE_DELIMITER_PATTERN):
            match = pattern.search(text)
            if match:
                text = text[: match.start()]

        lines = [line for line in text.splitlines() if not line.lstrip().startswith(">")]
        text = "\n".join(lines)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    def _neutralize_delimiters(self, text: str) -> str:
        return text.replace("<", "&lt;").replace(">", "&gt;")

    def normalize(self, raw: RawMessage) -> NormalizedEmail:
        if not raw.body:
            raise ValueError("The provided raw message body is empty.")

        logger.info(f"Starting email normalization. Message ID: {raw.ref.message_id}.")
        original_length = len(raw.body)

        body = self._neutralize_delimiters(self._strip_markup(raw.body))
        truncated = len(body) > self.max_characters
        body = body[: self.max_characters]
        subject = self._neutralize_delimiters(self._strip_markup(raw.subject))

        domain_match = _SENDER_DOMAIN_PATTERN.search(raw.sender)
        sender_domain: Optional[str] = domain_match.group(1).lower() if domain_match else None

        normalized = NormalizedEmail(
            message_id=raw.ref.message_id or "",
            subject=subject,
            body=body,
            sender_domain=sender_domain,
            truncated=truncated,
            original_length=original_length,
            normalized_length=len(body),
        )
        logger.info(
            f"Email normalization successfully completed. "
            f"Original length: {original_length}. "
            f"Normalized length: {normalized.normalized_length}. "
            f"Truncated: {truncated}. "
        )
        return normalized
