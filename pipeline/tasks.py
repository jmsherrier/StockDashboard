"""
Celery task definitions for scheduled pipeline runs.

These are the background tasks that keep the data fresh and
run the screening pipeline on schedule.

To run:
    celery -A pipeline.tasks worker --loglevel=info
    celery -A pipeline.tasks beat --loglevel=info
"""
from __future__ import annotations

import asyncio
import logging

from celery import Celery
from celery.schedules import crontab

from config.settings import settings

logger = logging.getLogger(__name__)

# ── Celery app ───────────────────────────────────────────────────

app = Celery(
    "stock_dashboard",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="US/Eastern",
    enable_utc=True,
)


def _parse_cron(cron_str: str) -> crontab:
    """Parse '0 18 * * 1-5' format to celery crontab."""
    parts = cron_str.split()
    return crontab(
        minute=parts[0],
        hour=parts[1],
        day_of_month=parts[2],
        month_of_year=parts[3],
        day_of_week=parts[4],
    )


app.conf.beat_schedule = {
    "refresh-universe": {
        "task": "pipeline.tasks.refresh_universe",
        "schedule": _parse_cron(settings.universe_refresh_cron),
    },
    "refresh-eod-prices": {
        "task": "pipeline.tasks.refresh_eod_prices",
        "schedule": _parse_cron(settings.eod_refresh_cron),
    },
    "run-screener": {
        "task": "pipeline.tasks.run_screener",
        "schedule": _parse_cron(settings.screener_run_cron),
    },
}


def _run_async(coro):
    """Helper to run async code from sync Celery tasks."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Tasks ────────────────────────────────────────────────────────

@app.task(name="pipeline.tasks.refresh_universe")
def refresh_universe():
    """
    Refresh the stock universe.
    Runs weekly — fetches all tradeable symbols and updates the DB.
    """
    async def _run():
        from storage.database import init_db
        from providers.registry import get_universe_provider
        from storage.repositories import StockRepository

        await init_db()
        provider = get_universe_provider()
        repo = StockRepository()

        stocks = await provider.get_stock_list(min_market_cap=settings.min_market_cap)
        logger.info("Fetched %d stocks from universe provider", len(stocks))

        rows = [s.model_dump() for s in stocks]
        count = await repo.upsert_stocks(rows)
        logger.info("Upserted %d stocks", count)
        return count

    return _run_async(_run())


@app.task(name="pipeline.tasks.refresh_fundamentals")
def refresh_fundamentals(symbols: list[str] | None = None):
    """
    Refresh fundamental data for active stocks.
    If symbols is None, refreshes all active stocks.
    """
    async def _run():
        from storage.database import init_db
        from providers.registry import get_fundamentals_provider
        from storage.repositories import FundamentalRepository, StockRepository

        await init_db()
        if symbols is None:
            repo = StockRepository()
            syms = await repo.get_active_symbols(min_market_cap=settings.min_market_cap)
        else:
            syms = symbols

        provider = get_fundamentals_provider()
        fund_repo = FundamentalRepository()

        fundamentals = await provider.get_fundamentals_bulk(syms)
        logger.info("Fetched fundamentals for %d stocks", len(fundamentals))

        rows = [f.model_dump() for f in fundamentals]
        count = await fund_repo.store_fundamentals(rows)
        logger.info("Stored %d fundamental snapshots", count)
        return count

    return _run_async(_run())


@app.task(name="pipeline.tasks.refresh_eod_prices")
def refresh_eod_prices(symbols: list[str] | None = None):
    """
    Refresh end-of-day prices for active stocks.
    Runs daily after market close.
    """
    async def _run():
        from datetime import date, timedelta
        from storage.database import init_db
        from providers.registry import get_price_provider
        from storage.repositories import PriceRepository, StockRepository

        await init_db()
        if symbols is None:
            repo = StockRepository()
            syms = await repo.get_active_symbols(min_market_cap=settings.min_market_cap)
        else:
            syms = symbols

        provider = get_price_provider()
        price_repo = PriceRepository()

        # Only fetch last 5 days to fill gaps
        start = date.today() - timedelta(days=5)
        prices = await provider.get_daily_prices_bulk(syms, start_date=start)

        total_bars = 0
        for symbol, bars in prices.items():
            rows = [
                {
                    "symbol": b.symbol,
                    "price_date": b.timestamp.date() if hasattr(b.timestamp, 'date') else b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "adj_close": b.adj_close,
                    "volume": b.volume,
                }
                for b in bars
            ]
            count = await price_repo.store_daily_prices(rows)
            total_bars += count

        logger.info("Stored %d price bars for %d symbols", total_bars, len(prices))
        return total_bars

    return _run_async(_run())


@app.task(name="pipeline.tasks.run_screener")
def run_screener(skip_intraday: bool = False):
    """
    Run the full screening pipeline.
    Scheduled after EOD data refresh.
    """
    async def _run():
        from storage.database import init_db
        from pipeline.orchestrator import run_pipeline

        await init_db()
        result = await run_pipeline(skip_intraday=skip_intraday)
        return result.summary()

    return _run_async(_run())
