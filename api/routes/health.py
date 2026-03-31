"""Health check endpoint."""
from fastapi import APIRouter

from config.settings import settings
from core.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="ok",
        environment=settings.env.value,
        providers={
            "fundamentals": settings.provider_fundamentals,
            "eod_prices": settings.provider_eod_prices,
            "intraday": settings.provider_intraday,
        },
    )
