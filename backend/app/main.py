from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import settings
from app.intelligence.services.rate_limiter import (
    RateLimitConfig,
    create_rate_limiter,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_rate_limiter(
        RateLimitConfig(
            max_requests=settings.llm_rate_limit_max_requests,
            window_seconds=settings.llm_rate_limit_window_seconds,
        )
    )
    yield
    # Shutdown (nothing to clean up for in-process limiter)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs" if settings.app_env.value != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.include_router(health_router)
