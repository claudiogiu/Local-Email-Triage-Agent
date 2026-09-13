import os
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
SOURCE_ROOT: Path = PROJECT_ROOT / "src"
PROMPTS_DIR: Path = SOURCE_ROOT / "prompts"
CONFIG_TOML_PATH: Path = PROJECT_ROOT / "config.toml"
WEB_TEMPLATES_DIR: Path = SOURCE_ROOT / "web" / "templates"
WEB_STATIC_DIR: Path = SOURCE_ROOT / "web" / "static"

API_BASE_URL: Optional[str] = os.getenv("API_BASE_URL")

OLLAMA_BASE_URL: Optional[str] = os.getenv("OLLAMA_BASE_URL")
OLLAMA_CLASSIFIER_MODEL: Optional[str] = os.getenv("OLLAMA_CLASSIFIER_MODEL")
OLLAMA_REASONING_MODEL: Optional[str] = os.getenv("OLLAMA_REASONING_MODEL")
OLLAMA_TIMEOUT_SECONDS: Optional[int] = (
    int(os.getenv("OLLAMA_TIMEOUT_SECONDS"))
    if os.getenv("OLLAMA_TIMEOUT_SECONDS") is not None
    else None
)

HF_CLASSIFIER_REPO: Optional[str] = os.getenv("HF_CLASSIFIER_REPO")
CLASSIFIER_LOCAL_DIR: Optional[str] = os.getenv("CLASSIFIER_LOCAL_DIR")

IMAP_HOST: Optional[str] = os.getenv("IMAP_HOST")
IMAP_PORT: Optional[int] = (
    int(os.getenv("IMAP_PORT"))
    if os.getenv("IMAP_PORT") is not None
    else None
)
SMTP_HOST: Optional[str] = os.getenv("SMTP_HOST")
SMTP_PORT: Optional[int] = (
    int(os.getenv("SMTP_PORT"))
    if os.getenv("SMTP_PORT") is not None
    else None
)
IMAP_USERNAME: Optional[str] = os.getenv("IMAP_USERNAME")
IMAP_PASSWORD: Optional[str] = os.getenv("IMAP_PASSWORD")
IMAP_FOLDERS: Optional[List[str]] = (
    os.getenv("IMAP_FOLDERS").split(",")
    if os.getenv("IMAP_FOLDERS") is not None
    else None
)
IMAP_ARCHIVE_FOLDER: Optional[str] = os.getenv("IMAP_ARCHIVE_FOLDER")
IMAP_SPAM_FOLDER: Optional[str] = os.getenv("IMAP_SPAM_FOLDER")
POLL_INTERVAL_SECONDS: Optional[int] = (
    int(os.getenv("POLL_INTERVAL_SECONDS"))
    if os.getenv("POLL_INTERVAL_SECONDS") is not None
    else None
)

DATABASE_PATH: Optional[str] = os.getenv("DATABASE_PATH")
CHECKPOINT_PATH: Optional[str] = os.getenv("CHECKPOINT_PATH")

DRY_RUN: Optional[bool] = (
    os.getenv("DRY_RUN").strip().lower() == "true"
    if os.getenv("DRY_RUN") is not None
    else None
)
LOG_LEVEL: Optional[str] = os.getenv("LOG_LEVEL")
