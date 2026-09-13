import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routes import router
from src.api.schemas import ServiceInfoResponse
from src.config.constants import IMAP_FOLDERS
from src.core.orchestrator import reset_orchestrator
from src.persistence.migrate import create_schema
from src.worker.scheduler_manager import start_scheduler_if_configured, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

SERVICE_NAME: str = "Local Email Triage Agent"
SERVICE_VERSION: str = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting application lifespan initialization.")
    create_schema()
    if IMAP_FOLDERS:
        await start_scheduler_if_configured()
    logger.info("Application lifespan initialization completed.")
    yield
    await stop_scheduler()
    await reset_orchestrator()
    logger.info("Application lifespan shutdown completed.")


app = FastAPI(title=SERVICE_NAME, version=SERVICE_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.exception_handler(Exception)
async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "message": "Unexpected server error"},
    )


@app.get("/", response_model=ServiceInfoResponse, tags=["Service"])
async def get_service_info() -> ServiceInfoResponse:
    """
    Report the running service's identity, version, documentation location,
    and the map of mounted endpoints.
    """
    endpoints: Dict[str, str] = {
        operation.get("operationId", f"{method}_{path}"): path
        for path, methods in app.openapi().get("paths", {}).items()
        for method, operation in methods.items()
    }
    return ServiceInfoResponse(
        service_name=SERVICE_NAME,
        version=SERVICE_VERSION,
        docs_url=app.docs_url or "/docs",
        endpoints=endpoints,
    )
