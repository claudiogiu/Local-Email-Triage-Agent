import logging
from pathlib import Path
from typing import Optional

from src.config.constants import PROMPTS_DIR

logger = logging.getLogger(__name__)


class PromptRegistry:
    """
    Interface for loading versioned prompt assets from the filesystem,
    keeping prompt content out of application source code.

    Attributes:
        prompts_dir (Path): Root directory containing every versioned prompt asset.

    Methods:
        load(name: str, version: str, extension: str) -> str:
            Reads and returns the content of the specified versioned prompt asset.
    """

    def __init__(self, prompts_dir: Optional[Path] = None) -> None:
        self.prompts_dir: Path = prompts_dir or PROMPTS_DIR

    def load(self, name: str, version: str, extension: str = "txt") -> str:
        path = self.prompts_dir / name / f"{version}.{extension}"
        if not path.is_file():
            raise ValueError(f"The requested prompt asset does not exist: {name}/{version}.{extension}.")
        logger.debug(f"Prompt asset loaded. Name: {name}. Version: {version}.")
        return path.read_text(encoding="utf-8")
