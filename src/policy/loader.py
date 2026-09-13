import logging
import tomllib
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from src.config.constants import CONFIG_TOML_PATH

logger = logging.getLogger(__name__)


class ReplyPolicy(BaseModel):
    """Policy governing reply drafting."""

    max_length_chars: int


class SendPolicy(BaseModel):
    """Policy governing message transmission. auto_approve is always forced to False in code, per I1."""

    auto_approve: bool


class Policy(BaseModel):
    """Root policy document combining the reply and send policy sections."""

    reply: ReplyPolicy
    send: SendPolicy


class PolicyLoader:
    """
    Interface for loading and validating the versioned application policy
    document, enforcing the non-negotiable send.auto_approve invariant
    regardless of the file's own content.

    Attributes:
        config_path (Path): Filesystem location of the policy TOML document.

    Methods:
        load() -> Policy:
            Reads, validates, and returns the policy document with send.auto_approve forced to False.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path: Path = config_path or CONFIG_TOML_PATH

    def load(self) -> Policy:
        if not self.config_path.is_file():
            raise ValueError(f"The policy configuration file does not exist: {self.config_path}.")
        with self.config_path.open("rb") as f:
            raw = tomllib.load(f)
        policy = Policy(**raw["policy"])
        policy.send.auto_approve = False
        logger.info("Policy document successfully loaded, with send auto-approve forced to False.")
        return policy
