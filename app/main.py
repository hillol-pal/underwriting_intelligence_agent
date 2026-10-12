"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    description="Claims Investigation Workbench — Advisory Agent",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health():
    from app.services.store import ping_ok

    return {
        "status": "healthy",
        "service": settings.app_name,
        "database": "ok" if ping_ok() else "unavailable",
    }
