"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.api.routes import router
from app.core.config import reload_settings, settings
from app.core.logutil import event
from app.services.tracing import configure_tracing

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Show application INFO logs in the uvicorn process.

    Uvicorn installs its own root handler. ``basicConfig`` does nothing after
    that, so the ``app`` logger level is set directly.
    """
    level_name = (settings.log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.getLogger("app").setLevel(level)
    root = logging.getLogger()
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    loaded = reload_settings()
    configure_logging()
    logger.info(
        "Settings loaded. embedding_provider=%s llm_provider=%s llm_model=%s "
        "mlflow=%s openai_key_set=%s agent_enabled=%s. "
        "UI calls http://localhost:%s/api/v1.",
        loaded.embedding_provider,
        loaded.llm_provider,
        loaded.llm_model,
        loaded.mlflow_tracking_uri,
        bool(loaded.openai_api_key),
        loaded.investigation_agent_enabled,
        loaded.api_port,
    )
    configure_tracing()
    yield


app = FastAPI(
    title=settings.app_name,
    description="Claims Investigation Workbench — Advisory Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_http(request: Request, call_next):
    """Log the request and the response, including claim text. Skip secret headers."""
    body = await request.body()
    event(
        logger,
        "http request",
        method=request.method,
        path=request.url.path,
        query=str(request.url.query),
        body=_text(body),
    )
    response = await call_next(request)
    payload = b""
    async for chunk in response.body_iterator:
        payload += chunk
    event(
        logger,
        "http response",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        body=_text(payload),
    )
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "content-type"}
    }
    return Response(
        content=payload,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
    )


def _text(raw: bytes) -> str:
    if not raw:
        return ""
    return raw.decode("utf-8", errors="replace")


app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root():
    """The workbench UI is Streamlit. This process is the API."""
    return {
        "service": settings.app_name,
        "health": "/health",
        "docs": "/docs",
        "api": "/api/v1",
        "ui": "http://localhost:8501",
    }


@app.get("/health")
async def health():
    from app.services.store import ping_ok

    return {
        "status": "healthy",
        "service": settings.app_name,
        "database": "ok" if ping_ok() else "unavailable",
    }
