import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

from src.config.constants import IMAP_PASSWORD, IMAP_USERNAME, SMTP_HOST, SMTP_PORT
from src.domain.entities import OutgoingMessage
from src.persistence.repositories import MailboxCredentialsRepository

logger = logging.getLogger(__name__)


class SmtpService:
    """
    Interface for transmitting an outgoing reply over an authenticated,
    STARTTLS-secured SMTP connection to the configured mailbox.

    Attributes:
        host (str): Hostname of the SMTP server used for transmission.
        port (int): Port of the SMTP server used for transmission.
        username (str): Account identifier employed during authentication.
        _password (str): Application password used during authentication.

    Methods:
        send(reply: OutgoingMessage) -> None:
            Transmits the supplied reply over SMTP, raising on any transport or authentication failure.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        stored_credentials = MailboxCredentialsRepository().get()
        resolved_host = host or SMTP_HOST
        resolved_port = port or SMTP_PORT
        resolved_username = username or (stored_credentials.email if stored_credentials else None) or IMAP_USERNAME
        resolved_password = (
            password or (stored_credentials.imap_password if stored_credentials else None) or IMAP_PASSWORD
        )
        if not (resolved_host and resolved_port and resolved_username and resolved_password):
            raise ValueError("The SMTP connection parameters are not fully configured.")
        self.host: str = resolved_host
        self.port: int = resolved_port
        self.username: str = resolved_username
        self._password: str = resolved_password
        logger.info(f"SMTP service initialization completed. Host: {self.host}. Port: {self.port}.")

    def send(self, reply: OutgoingMessage) -> None:
        logger.info(f"Starting SMTP transmission. In reply to: {reply.in_reply_to_message_id}.")
        message = EmailMessage()
        message["From"] = self.username
        message["To"] = ", ".join(reply.recipients)
        message["Subject"] = reply.subject
        message["In-Reply-To"] = reply.in_reply_to_message_id
        message["References"] = reply.in_reply_to_message_id
        message.set_content(reply.body)
        with smtplib.SMTP(self.host, self.port, timeout=30) as client:
            client.starttls()
            client.login(self.username, self._password)
            client.send_message(message)
        logger.info("SMTP transmission successfully completed.")
