"""Stock detail endpoints — individual stock lookup and data."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from storage.repositories import (
    FundamentalRepository,
    PriceRepository,
    StockRepository,
)

router = APIRouter()


@router.get("/search")
async def search_stocks(
    q: str = Query(..., min_length=1, description="Search query (symbol or name)"),
    limit: int = Query(20, ge=1, le=100),
):
    """Search stocks by symbol or name prefix."""
    from sqlalchemy import select, or_
    from core.models import Stock
    from storage.database import get_session

    async with get_session() as session:
        stmt = (
            select(Stock)
            .where(
                or_(
                    Stock.symbol.ilike(f"{q}%"),
                    Stock.name.ilike(f"%{q}%"),
                )
            )
            .where(Stock.is_active == True)
            .limit(limit)
        )
        result = await session.execute(stmt)
        stocks = result.scalars().all()

    return [
        {
            "symbol": s.symbol,
            "name": s.name,
            "exchange": s.exchange,
            "sector": s.sector,
            "market_cap": s.market_cap,
        }
        for s in stocks
    ]


@router.get("/{symbol}")
async def get_stock(symbol: str):
    """Get full stock details including latest fundamentals."""
    stock_repo = StockRepository()
    fund_repo = FundamentalRepository()

    details = await stock_repo.get_stock_details([symbol.upper()])
    if not details:
        raise HTTPException(status_code=404, detail="Stock not found")

    fundamentals = await fund_repo.get_latest(symbol.upper())

    return {
        "stock": details.get(symbol.upper()),
        "fundamentals": fundamentals,
    }


@router.get("/{symbol}/prices")
async def get_stock_prices(
    symbol: str,
    days: int = Query(90, ge=1, le=365 * 5),
):
    """Get daily price history for a stock."""
    price_repo = PriceRepository()
    df = await price_repo.get_daily_df(symbol.upper(), lookback_days=days)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail="No price data found")

    return df.to_dict(orient="records")
