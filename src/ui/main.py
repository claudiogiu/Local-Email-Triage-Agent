import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.config.constants import WEB_STATIC_DIR
from src.ui.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

SERVICE_NAME: str = "Local Email Triage Agent UI"
SERVICE_VERSION: str = "0.1.0"

app = FastAPI(title=SERVICE_NAME, version=SERVICE_VERSION)

app.include_router(router)
app.mount("/static", StaticFiles(directory=str(WEB_STATIC_DIR)), name="static")

logger.info("UI service initialization completed.")
