import logging

from src.domain.ports import MailProvider
from src.providers.imap_mail_provider import ImapMailProvider

logger = logging.getLogger(__name__)


class MailProviderFactory:
    """
    Interface for constructing the mail provider implementation used by the
    rest of the system, keeping the construction logic out of the caller.

    Attributes:
        None.

    Methods:
        create() -> MailProvider:
            Instantiates the IMAP mail provider implementation.
    """

    @staticmethod
    def create() -> MailProvider:
        logger.info("Mail provider factory selected the IMAP implementation.")
        return ImapMailProvider()
