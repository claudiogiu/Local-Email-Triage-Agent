from datetime import datetime
from typing import Any, Iterator, List, Protocol

from src.domain.entities import (
    CompletionRequest,
    CompletionResult,
    DraftRef,
    FolderStatus,
    MessageRef,
    OutgoingMessage,
    RawMessage,
    SentRef,
)


class MailProvider(Protocol):
    """
    Interface for discovering, retrieving, and acting upon messages held by a
    mailbox, abstracting the concrete mail protocol and vendor from the rest
    of the system.

    Attributes:
        None.

    Methods:
        list_new(since: datetime, folders: List[str]) -> Iterator[MessageRef]:
            Enumerates the messages received after the specified timestamp within the given folders.

        fetch(ref: MessageRef) -> RawMessage:
            Retrieves the complete envelope and body of the referenced message without altering its read state.

        apply_label(ref: MessageRef, label: str) -> None:
            Assigns the specified label to the referenced message.

        move(ref: MessageRef, folder: str) -> None:
            Relocates the referenced message to the specified folder.

        mark_read(ref: MessageRef) -> None:
            Marks the referenced message as read.

        save_draft(reply: OutgoingMessage) -> DraftRef:
            Persists the supplied reply as a draft on the mail provider.

        send(reply: OutgoingMessage, idempotency_key: str) -> SentRef:
            Transmits the supplied reply, guarding against duplicate delivery through the provided key.

        get_folder_status(folder: str) -> FolderStatus:
            Retrieves the current UIDVALIDITY and maximum assigned UID of the specified folder.
    """

    def list_new(self, since: datetime, folders: List[str]) -> Iterator[MessageRef]: ...

    def fetch(self, ref: MessageRef) -> RawMessage: ...

    def apply_label(self, ref: MessageRef, label: str) -> None: ...

    def move(self, ref: MessageRef, folder: str) -> None: ...

    def mark_read(self, ref: MessageRef) -> None: ...

    def save_draft(self, reply: OutgoingMessage) -> DraftRef: ...

    def send(self, reply: OutgoingMessage, idempotency_key: str) -> SentRef: ...

    def get_folder_status(self, folder: str) -> FolderStatus: ...


class LLMProvider(Protocol):
    """
    Interface for invoking a locally hosted reasoning model, either for free-form
    text completion or for output validated against a caller-supplied schema.

    Attributes:
        None.

    Methods:
        complete(req: CompletionRequest) -> CompletionResult:
            Produces a free-form textual completion for the supplied request.

        structured(req: CompletionRequest, schema: type) -> Any:
            Produces a completion validated against the supplied schema type.
    """

    async def complete(self, req: CompletionRequest) -> CompletionResult: ...

    async def structured(self, req: CompletionRequest, schema: type) -> Any: ...
