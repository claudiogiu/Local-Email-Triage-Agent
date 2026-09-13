import logging
from datetime import UTC, datetime
from email.message import Message
from typing import Iterator, List, Optional

from imapclient import IMAPClient
from sqlalchemy.exc import IntegrityError

from src.config.constants import (
    DRY_RUN,
    IMAP_HOST,
    IMAP_PASSWORD,
    IMAP_PORT,
    IMAP_USERNAME,
)
from src.domain.entities import (
    DraftRef,
    FolderStatus,
    MessageRef,
    OutgoingMessage,
    RawMessage,
    SentRef,
)
from src.persistence.models import SentRegistryModel
from src.persistence.repositories import (
    MailboxCredentialsRepository,
    SentRegistryRepository,
)
from src.providers.email_parsing import parse_raw_message
from src.services.smtp_service import SmtpService

logger = logging.getLogger(__name__)


class ImapMailProvider:
    """
    Interface for discovering and retrieving messages over IMAP, enforcing
    read-only fetch semantics on every discovery and retrieval operation.
    Write operations are implemented but remain inert whenever the dry-run
    switch is active, regardless of the caller.

    Attributes:
        host (str): Hostname of the IMAP server used for mailbox access.
        port (int): Port of the IMAP server used for mailbox access.
        username (str): Account identifier employed during authentication.
        dry_run (bool): Global switch that, when active, suppresses every write operation.
        _password (str): Application password used during authentication.
        _smtp_service (Optional[SmtpService]): Client used for real message transmission, lazily constructed if not supplied.

    Methods:
        _connect() -> IMAPClient:
            Establishes an authenticated, SSL-secured connection to the configured IMAP server.

        verify_connection() -> None:
            Attempts an authenticated connection and immediate logout, raising if sign-in fails.

        _find_special_use_folder(client: IMAPClient, use_flag: bytes) -> Optional[str]:
            Resolves the mailbox folder advertising the supplied IMAP special-use flag.

        list_new(since: datetime, folders: List[str]) -> Iterator[MessageRef]:
            Enumerates the messages currently flagged UNSEEN within the given folders.

        fetch(ref: MessageRef) -> RawMessage:
            Retrieves the complete envelope and body of the referenced message without marking it as read.

        apply_label(ref: MessageRef, label: str) -> None:
            Assigns the specified label to the referenced message via folder-level copy semantics.

        move(ref: MessageRef, folder: str) -> None:
            Relocates the referenced message to the specified folder.

        mark_read(ref: MessageRef) -> None:
            Marks the referenced message as read via an explicit IMAP flag write.

        save_draft(reply: OutgoingMessage) -> DraftRef:
            Persists the supplied reply as a draft on the mail provider.

        send(reply: OutgoingMessage, idempotency_key: str) -> SentRef:
            Transmits the supplied reply over SMTP, claiming the idempotency key in the sent registry before transmission to guard against duplicate delivery.

        get_folder_status(folder: str) -> FolderStatus:
            Retrieves the current UIDVALIDITY and maximum assigned UID of the specified folder.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        dry_run: Optional[bool] = None,
        smtp_service: Optional[SmtpService] = None,
    ) -> None:
        stored_credentials = MailboxCredentialsRepository().get()
        resolved_host = host or IMAP_HOST
        resolved_port = port or IMAP_PORT
        resolved_username = username or (stored_credentials.email if stored_credentials else None) or IMAP_USERNAME
        resolved_password = (
            password or (stored_credentials.imap_password if stored_credentials else None) or IMAP_PASSWORD
        )
        if not (resolved_host and resolved_port and resolved_username and resolved_password):
            raise ValueError("The IMAP connection parameters are not fully configured.")
        self.host: str = resolved_host
        self.port: int = resolved_port
        self.username: str = resolved_username
        self._password: str = resolved_password
        self.dry_run: bool = DRY_RUN if dry_run is None else dry_run
        self._smtp_service: Optional[SmtpService] = smtp_service
        logger.info(
            f"IMAP mail provider initialization completed. "
            f"Host: {self.host}. "
            f"Port: {self.port}. "
            f"Dry run: {self.dry_run}. "
        )

    def _connect(self) -> IMAPClient:
        client = IMAPClient(self.host, port=self.port, ssl=True)
        client.login(self.username, self._password)
        return client

    def verify_connection(self) -> None:
        client = self._connect()
        client.logout()

    def _find_special_use_folder(self, client: IMAPClient, use_flag: bytes) -> Optional[str]:
        for flags, _delimiter, name in client.list_folders():
            if use_flag in flags:
                return name
        return None

    def list_new(self, since: datetime, folders: List[str]) -> Iterator[MessageRef]:
        logger.info(f"Starting discovery of unseen messages. Folders: {len(folders)}.")
        client = self._connect()
        try:
            for folder in folders:
                client.select_folder(folder, readonly=True)
                uids = sorted(client.search(["UNSEEN"]))
                if not uids:
                    continue
                response = client.fetch(uids, [b"ENVELOPE"])
                for uid in uids:
                    envelope = response[uid][b"ENVELOPE"]
                    message_id: Optional[str] = envelope.message_id.decode() if envelope.message_id else None
                    yield MessageRef(account_id=self.username, folder=folder, uid=uid, message_id=message_id)
        finally:
            client.logout()
        logger.info("Discovery of unseen messages successfully completed.")

    def fetch(self, ref: MessageRef) -> RawMessage:
        logger.info(f"Starting fetch of a message. Folder: {ref.folder}. UID: {ref.uid}.")
        client = self._connect()
        try:
            client.select_folder(ref.folder, readonly=True)
            response = client.fetch([ref.uid], [b"BODY.PEEK[]", b"ENVELOPE", b"INTERNALDATE", b"FLAGS"])
            if ref.uid not in response:
                raise ValueError(f"No message found for UID {ref.uid} in folder {ref.folder}.")
            data = response[ref.uid]
            raw_bytes: bytes = data[b"BODY[]"]
            received_at: datetime = data[b"INTERNALDATE"]
        finally:
            client.logout()
        logger.info("Message fetch successfully completed.")
        return parse_raw_message(ref, raw_bytes, received_at)

    def apply_label(self, ref: MessageRef, label: str) -> None:
        if self.dry_run:
            logger.info(f"Dry run active: label application skipped. UID: {ref.uid}. Label: {label}.")
            return
        client = self._connect()
        try:
            if not client.folder_exists(label):
                client.create_folder(label)
                logger.info(f"Label folder created. Label: {label}.")
            client.select_folder(ref.folder)
            client.copy([ref.uid], label)
        finally:
            client.logout()
        logger.info(f"Label successfully applied. UID: {ref.uid}. Label: {label}.")

    def move(self, ref: MessageRef, folder: str) -> None:
        if self.dry_run:
            logger.info(f"Dry run active: folder relocation skipped. UID: {ref.uid}. Folder: {folder}.")
            return
        client = self._connect()
        try:
            client.select_folder(ref.folder)
            client.move([ref.uid], folder)
        finally:
            client.logout()
        logger.info(f"Folder relocation successfully completed. UID: {ref.uid}. Folder: {folder}.")

    def mark_read(self, ref: MessageRef) -> None:
        if self.dry_run:
            logger.info(f"Dry run active: mark-as-read skipped. UID: {ref.uid}.")
            return
        client = self._connect()
        try:
            client.select_folder(ref.folder)
            client.add_flags([ref.uid], [b"\\Seen"])
        finally:
            client.logout()
        logger.info(f"Message successfully marked as read. UID: {ref.uid}.")

    def save_draft(self, reply: OutgoingMessage) -> DraftRef:
        if self.dry_run:
            logger.info(f"Dry run active: draft persistence skipped. In reply to: {reply.in_reply_to_message_id}.")
            return DraftRef(provider_ref="dry-run-draft", message_id=reply.in_reply_to_message_id)
        client = self._connect()
        try:
            drafts_folder = self._find_special_use_folder(client, b"\\Drafts")
            if drafts_folder is None:
                raise RuntimeError("The mailbox does not advertise a folder with the IMAP \\Drafts special use.")
            message = Message()
            message["To"] = ", ".join(reply.recipients)
            message["Subject"] = reply.subject
            message.set_payload(reply.body)
            client.append(drafts_folder, message.as_bytes(), flags=[b"\\Draft"])
        finally:
            client.logout()
        logger.info(f"Draft successfully persisted. In reply to: {reply.in_reply_to_message_id}.")
        return DraftRef(provider_ref=drafts_folder, message_id=reply.in_reply_to_message_id)

    def send(self, reply: OutgoingMessage, idempotency_key: str) -> SentRef:
        if self.dry_run:
            logger.info(f"Dry run active: message transmission skipped. Idempotency key: {idempotency_key}.")
            return SentRef(
                provider_ref="dry-run-sent",
                message_id=reply.in_reply_to_message_id,
                sent_at=datetime.now(UTC),
            )
        registry = SentRegistryRepository()
        sent_at = datetime.now(UTC)
        try:
            registry.add(
                SentRegistryModel(
                    idempotency_key=idempotency_key,
                    message_id=reply.in_reply_to_message_id,
                    draft_version=reply.draft_version,
                    sent_at=sent_at,
                )
            )
        except IntegrityError:
            logger.info(f"Message transmission skipped: idempotency key already registered. Key: {idempotency_key}.")
            return SentRef(provider_ref="already-sent", message_id=reply.in_reply_to_message_id, sent_at=sent_at)

        (self._smtp_service or SmtpService()).send(reply)
        logger.info(f"Message successfully transmitted. Idempotency key: {idempotency_key}.")
        return SentRef(provider_ref="smtp-sent", message_id=reply.in_reply_to_message_id, sent_at=sent_at)

    def get_folder_status(self, folder: str) -> FolderStatus:
        client = self._connect()
        try:
            select_info = client.select_folder(folder, readonly=True)
            uidvalidity = select_info[b"UIDVALIDITY"]
            uidnext = select_info[b"UIDNEXT"]
        finally:
            client.logout()
        return FolderStatus(uidvalidity=uidvalidity, max_uid=uidnext - 1)
