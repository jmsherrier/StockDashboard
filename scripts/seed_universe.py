"""
Seed the stock universe.

Run this once to populate the stocks table, then again weekly via Celery.
This is the first thing to run after setting up the project.

Usage:
    python -m scripts.seed_universe
    python -m scripts.seed_universe --exchange NYSE --min-cap 500000000
    python -m scripts.seed_universe --fundamentals --prices
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import math
import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings
from config.specifications import TRADING_DAYS, FUNDAMENTAL_FILTERS
from providers.registry import get_universe_provider, get_fundamentals_provider, get_price_provider
from storage.database import init_db
from storage.repositories import StockRepository, FundamentalRepository, PriceRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _trading_to_calendar_days(trading_days: int) -> int:
    """Convert trading days to calendar days (accounting for weekends/holidays)."""
    return math.ceil(trading_days * 365 / 252) + 5  # +5 buffer for holidays


async def seed_universe(
    exchange: str | None = None,
    min_market_cap: float = 100_000_000,
    fetch_fundamentals: bool = False,
    fetch_prices: bool = False,
    trading_days: int = TRADING_DAYS,
):
    """Seed the database with stock universe and optionally fundamentals + prices."""

    await init_db()
    logger.info("Database initialized")

    # ── Step 1: Fetch stock universe ─────────────────────────────
    provider = get_universe_provider()
    stock_repo = StockRepository()

    logger.info(
        "Fetching universe (provider=%s, exchange=%s, min_cap=%s)",
        settings.provider_universe, exchange, min_market_cap,
    )
    stocks = await provider.get_stock_list(
        exchange=exchange,
        min_market_cap=min_market_cap,
    )
    logger.info("Provider returned %d stocks", len(stocks))

    if not stocks:
        logger.error("No stocks returned. Check your API key and provider settings.")
        return

    # Store in DB
    rows = [s.model_dump() for s in stocks]
    count = await stock_repo.upsert_stocks(rows)
    logger.info("Upserted %d stocks to database", count)

    # ── Step 2: Fetch fundamentals (optional) ────────────────────
    symbols_for_prices = [s.symbol for s in stocks]

    if fetch_fundamentals:
        logger.info("Fetching fundamentals...")
        fund_provider = get_fundamentals_provider()
        fund_repo = FundamentalRepository()

        symbols = [s.symbol for s in stocks]
        batch_size = 20
        total_stored = 0
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            logger.info(
                "Fundamentals batch %d/%d (%d symbols)",
                i // batch_size + 1,
                (len(symbols) + batch_size - 1) // batch_size,
                len(batch),
            )
            fundamentals = await fund_provider.get_fundamentals_bulk(batch)
            if fundamentals:
                fund_rows = [f.model_dump() for f in fundamentals]
                stored = await fund_repo.store_fundamentals(fund_rows)
                total_stored += stored

            await asyncio.sleep(1)

        logger.info("Stored %d fundamental snapshots", total_stored)

        # If also fetching prices, pre-filter with Tier 1 to skip
        # stocks that will fail fundamental screening anyway.
        if fetch_prices:
            from filters.base import CompositeFilter
            from filters.fundamental import build_fundamental_filters

            logger.info("Pre-filtering with fundamental filters before price fetch...")
            filters = build_fundamental_filters(FUNDAMENTAL_FILTERS)
            composite = CompositeFilter(filters)
            results = await composite.apply(symbols)
            passed = [r.symbol for r in results if r.passed]
            skipped = len(symbols) - len(passed)
            logger.info(
                "Pre-filter: %d passed, %d skipped (saving %d price fetches)",
                len(passed), skipped, skipped,
            )
            symbols_for_prices = passed

    # ── Step 3: Fetch historical prices (optional) ───────────────
    if fetch_prices:
        calendar_days = _trading_to_calendar_days(trading_days)
        logger.info(
            "Fetching prices: %d trading days (%d calendar days) for %d symbols...",
            trading_days, calendar_days, len(symbols_for_prices),
        )
        price_provider = get_price_provider()
        price_repo = PriceRepository()
        start_date = date.today() - timedelta(days=calendar_days)

        batch_size = 10
        total_bars = 0
        for i in range(0, len(symbols_for_prices), batch_size):
            batch = symbols_for_prices[i:i + batch_size]
            logger.info(
                "Prices batch %d/%d (%d symbols)",
                i // batch_size + 1,
                (len(symbols_for_prices) + batch_size - 1) // batch_size,
                len(batch),
            )
            prices = await price_provider.get_daily_prices_bulk(
                batch, start_date=start_date
            )
            for symbol, bars in prices.items():
                # Trim to max trading_days bars (keep most recent)
                trimmed = bars[-trading_days:] if len(bars) > trading_days else bars
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
                    for b in trimmed
                ]
                stored = await price_repo.store_daily_prices(rows)
                total_bars += stored

            await asyncio.sleep(1)

        logger.info("Stored %d price bars", total_bars)

    logger.info("Seed complete!")


def main():
    parser = argparse.ArgumentParser(description="Seed the stock universe")
    parser.add_argument("--exchange", type=str, default=None, help="Filter by exchange (NYSE, NASDAQ, AMEX)")
    parser.add_argument("--min-cap", type=float, default=100_000_000, help="Minimum market cap (default: 100M)")
    parser.add_argument("--fundamentals", action="store_true", help="Also fetch fundamentals")
    parser.add_argument("--prices", action="store_true", help="Also fetch historical prices")
    parser.add_argument("--trading-days", type=int, default=TRADING_DAYS, help=f"Trading days of history (default: {TRADING_DAYS})")
    args = parser.parse_args()

    asyncio.run(seed_universe(
        exchange=args.exchange,
        min_market_cap=args.min_cap,
        fetch_fundamentals=args.fundamentals,
        fetch_prices=args.prices,
        trading_days=args.trading_days,
    ))


if __name__ == "__main__":
    main()
