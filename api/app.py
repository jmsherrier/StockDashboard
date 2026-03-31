"""
FastAPI application.

This is the API layer that a frontend (or trading bot) will consume.
Auto-generates OpenAPI docs at /docs.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from storage.database import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logging.basicConfig(level=getattr(logging, settings.log_level))
    logger.info("Starting Stock Dashboard API (%s)", settings.env.value)
    await init_db()
    yield
    logger.info("Shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Stock Dashboard API",
        description="Screening pipeline & stock data API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — permissive for dev, tighten in prod
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.env == "dev" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    from api.routes import health, screener, stocks
    app.include_router(health.router, tags=["Health"])
    app.include_router(screener.router, prefix="/api/screener", tags=["Screener"])
    app.include_router(stocks.router, prefix="/api/stocks", tags=["Stocks"])

    return app
