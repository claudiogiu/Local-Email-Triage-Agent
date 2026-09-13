from datetime import datetime
from email import message_from_bytes
from email.message import Message

from src.domain.entities import MessageRef, RawMessage


def extract_body(parsed: Message) -> str:
    target = parsed
    if parsed.is_multipart():
        plain_parts = [part for part in parsed.walk() if part.get_content_type() == "text/plain"]
        html_parts = [part for part in parsed.walk() if part.get_content_type() == "text/html"]
        if plain_parts:
            target = plain_parts[0]
        elif html_parts:
            target = html_parts[0]
        else:
            return ""
    payload = target.get_payload(decode=True)
    if payload is None:
        return ""
    return payload.decode(target.get_content_charset() or "utf-8", errors="replace")


def parse_raw_message(ref: MessageRef, raw_bytes: bytes, received_at: datetime) -> RawMessage:
    parsed = message_from_bytes(raw_bytes)
    recipients = [addr.strip() for addr in parsed.get("To", "").split(",") if addr.strip()]
    cc_recipients = [addr.strip() for addr in parsed.get("Cc", "").split(",") if addr.strip()]
    return RawMessage(
        ref=ref,
        sender=parsed.get("From", ""),
        recipients=recipients,
        cc_recipients=cc_recipients,
        subject=parsed.get("Subject", ""),
        body=extract_body(parsed),
        received_at=received_at,
        headers=dict(parsed.items()),
    )
