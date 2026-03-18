from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.v1 import auth
from app.core.config import get_settings
from app.core.exceptions import AppException

settings = get_settings()


def create_app() -> FastAPI:
    app = FastAPI(
        title="SentimentPulse API",
        version="1.0.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
    )

    @app.exception_handler(AppException)
    async def app_exception_handler(request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(auth.router, prefix="/api/v1")

    return app


app = create_app()
