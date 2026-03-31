"""
Repository layer — abstracts database + cache access.

Filters and pipeline code never touch SQLAlchemy directly;
they go through these repositories. This makes it easy to
swap storage backends or add caching layers.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional, Sequence

import pandas as pd
from sqlalchemy import select, and_, desc

from config.settings import settings
from core.models import DailyPrice, Fundamental, ScreenerResult, Stock
from storage.cache import cache_get, cache_get_many, cache_set, cache_set_many
from storage.database import get_session

logger = logging.getLogger(__name__)


class StockRepository:
    """CRUD for the stock universe table."""

    async def upsert_stocks(self, stocks: list[dict]) -> int:
        """Insert or update stocks. Returns count of upserted rows."""
        count = 0
        async with get_session() as session:
            for s in stocks:
                result = await session.execute(
                    select(Stock).where(Stock.symbol == s["symbol"])
                )
                existing = result.scalar_one_or_none()
                if existing:
                    for k, v in s.items():
                        if v is not None:
                            setattr(existing, k, v)
                else:
                    session.add(Stock(**s))
                count += 1
        return count

    async def get_active_symbols(
        self,
        exchange: Optional[str] = None,
        min_market_cap: Optional[float] = None,
    ) -> list[str]:
        """Get all active symbols, optionally filtered."""
        async with get_session() as session:
            stmt = select(Stock.symbol).where(Stock.is_active == True)
            if exchange:
                stmt = stmt.where(Stock.exchange == exchange)
            if min_market_cap:
                stmt = stmt.where(Stock.market_cap >= min_market_cap)
            result = await session.execute(stmt)
            return [row[0] for row in result.all()]

    async def get_stock_details(self, symbols: Sequence[str]) -> dict[str, dict]:
        """Get stock details as dicts, keyed by symbol."""
        async with get_session() as session:
            stmt = select(Stock).where(Stock.symbol.in_(symbols))
            result = await session.execute(stmt)
            stocks = result.scalars().all()
            return {
                s.symbol: {
                    "name": s.name,
                    "exchange": s.exchange,
                    "sector": s.sector,
                    "industry": s.industry,
                    "market_cap": s.market_cap,
                }
                for s in stocks
            }


class FundamentalRepository:
    """Access fundamental data with cache-first strategy."""

    async def store_fundamentals(self, data: list[dict]) -> int:
        """Store fundamental snapshots."""
        count = 0
        async with get_session() as session:
            for d in data:
                session.add(Fundamental(**d))
                count += 1
        return count

    async def get_latest(self, symbol: str) -> Optional[dict]:
        """Get latest fundamental snapshot for a symbol."""
        cache_key = f"fund:{symbol}"
        cached = await cache_get(cache_key)
        if cached:
            return cached

        async with get_session() as session:
            stmt = (
                select(Fundamental)
                .where(Fundamental.symbol == symbol)
                .order_by(desc(Fundamental.snapshot_date))
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None

            data = {
                c.name: getattr(row, c.name)
                for c in Fundamental.__table__.columns
                if c.name not in ("id", "updated_at")
            }
            await cache_set(cache_key, data, ttl=settings.cache_ttl_fundamentals)
            return data

    async def get_latest_bulk(self, symbols: Sequence[str]) -> dict[str, dict]:
        """Bulk get with cache. Returns {symbol: data_dict}."""
        cache_keys = [f"fund:{s}" for s in symbols]
        cached = await cache_get_many(cache_keys)

        result = {}
        missing = []
        for s, k in zip(symbols, cache_keys):
            if k in cached:
                result[s] = cached[k]
            else:
                missing.append(s)

        if missing:
            async with get_session() as session:
                # Subquery to get latest snapshot_date per symbol
                from sqlalchemy import func
                subq = (
                    select(
                        Fundamental.symbol,
                        func.max(Fundamental.snapshot_date).label("max_date"),
                    )
                    .where(Fundamental.symbol.in_(missing))
                    .group_by(Fundamental.symbol)
                    .subquery()
                )
                stmt = (
                    select(Fundamental)
                    .join(
                        subq,
                        and_(
                            Fundamental.symbol == subq.c.symbol,
                            Fundamental.snapshot_date == subq.c.max_date,
                        ),
                    )
                )
                db_result = await session.execute(stmt)
                rows = db_result.scalars().all()

                to_cache = {}
                for row in rows:
                    data = {
                        c.name: getattr(row, c.name)
                        for c in Fundamental.__table__.columns
                        if c.name not in ("id", "updated_at")
                    }
                    result[row.symbol] = data
                    to_cache[f"fund:{row.symbol}"] = data

                if to_cache:
                    await cache_set_many(to_cache, ttl=settings.cache_ttl_fundamentals)

        return result


class PriceRepository:
    """Access daily price data."""

    async def store_daily_prices(self, bars: list[dict]) -> int:
        """Bulk insert daily prices (ignores duplicates)."""
        count = 0
        async with get_session() as session:
            for b in bars:
                # Check for existing
                stmt = select(DailyPrice).where(
                    and_(
                        DailyPrice.symbol == b["symbol"],
                        DailyPrice.price_date == b["price_date"],
                    )
                )
                existing = await session.execute(stmt)
                if not existing.scalar_one_or_none():
                    session.add(DailyPrice(**b))
                    count += 1
        return count

    async def get_daily_df(
        self, symbol: str, lookback_days: int = 252
    ) -> Optional[pd.DataFrame]:
        """Get daily prices as a pandas DataFrame for TA calculations."""
        cache_key = f"prices_df:{symbol}:{lookback_days}"
        cached = await cache_get(cache_key)
        if cached:
            df = pd.DataFrame(cached)
            if not df.empty:
                return df

        cutoff = date.today() - timedelta(days=lookback_days)
        async with get_session() as session:
            stmt = (
                select(DailyPrice)
                .where(
                    and_(
                        DailyPrice.symbol == symbol,
                        DailyPrice.price_date >= cutoff,
                    )
                )
                .order_by(DailyPrice.price_date)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        if not rows:
            return None

        data = [
            {
                "date": r.price_date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "adj_close": r.adj_close,
            }
            for r in rows
        ]
        df = pd.DataFrame(data)

        await cache_set(cache_key, data, ttl=settings.cache_ttl_eod_prices)
        return df


class ScreenerRepository:
    """Store and retrieve screening results."""

    async def store_results(self, results: list[dict]) -> int:
        count = 0
        async with get_session() as session:
            for r in results:
                session.add(ScreenerResult(**r))
                count += 1
        return count

    async def get_latest_run(self) -> Optional[str]:
        """Get the most recent run_id."""
        async with get_session() as session:
            stmt = (
                select(ScreenerResult.run_id)
                .order_by(desc(ScreenerResult.run_timestamp))
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return row

    async def get_run_results(
        self, run_id: str, min_score: float = 0, limit: int = 100
    ) -> list[dict]:
        """Get results for a specific run."""
        async with get_session() as session:
            stmt = (
                select(ScreenerResult)
                .where(
                    and_(
                        ScreenerResult.run_id == run_id,
                        ScreenerResult.composite_score >= min_score,
                    )
                )
                .order_by(desc(ScreenerResult.composite_score))
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    c.name: getattr(r, c.name)
                    for c in ScreenerResult.__table__.columns
                    if c.name != "id"
                }
                for r in rows
            ]
