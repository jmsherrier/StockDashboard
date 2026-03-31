"""
Abstract provider interfaces.

Every data source implements these ABCs. The pipeline never imports a
concrete provider — it gets one from the registry based on config.
This is the single most important file for future development:
swap FMP for Polygon by implementing these interfaces.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional, Sequence

from core.schemas import FundamentalData, OHLCVBar, QuoteSnapshot, StockInfo


class UniverseProvider(ABC):
    """Fetches the list of tradeable symbols."""

    @abstractmethod
    async def get_stock_list(
        self,
        exchange: Optional[str] = None,
        min_market_cap: Optional[float] = None,
    ) -> list[StockInfo]:
        """Return all stocks, optionally filtered by exchange/cap."""
        ...

    @abstractmethod
    async def get_stock_profile(self, symbol: str) -> Optional[StockInfo]:
        """Detailed profile for a single symbol."""
        ...


class FundamentalsProvider(ABC):
    """Fetches fundamental/financial data."""

    @abstractmethod
    async def get_fundamentals(self, symbol: str) -> Optional[FundamentalData]:
        """Latest fundamental snapshot for a symbol."""
        ...

    @abstractmethod
    async def get_fundamentals_bulk(
        self, symbols: Sequence[str]
    ) -> list[FundamentalData]:
        """
        Bulk fetch. Implementations should batch API calls efficiently.
        For providers with a bulk endpoint (FMP /stock-screener), use it.
        For providers without, chunk and parallelize with rate limiting.
        """
        ...


class PriceProvider(ABC):
    """Fetches OHLCV price data — both EOD and historical."""

    @abstractmethod
    async def get_daily_prices(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[OHLCVBar]:
        """EOD OHLCV bars for a symbol."""
        ...

    @abstractmethod
    async def get_daily_prices_bulk(
        self,
        symbols: Sequence[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict[str, list[OHLCVBar]]:
        """Bulk EOD fetch. Returns {symbol: [bars]}."""
        ...


class IntradayProvider(ABC):
    """Fetches real-time or near-real-time quote data."""

    @abstractmethod
    async def get_quote(self, symbol: str) -> Optional[QuoteSnapshot]:
        """Single real-time quote."""
        ...

    @abstractmethod
    async def get_quotes_bulk(
        self, symbols: Sequence[str]
    ) -> list[QuoteSnapshot]:
        """Batch quotes. Most providers support comma-separated symbols."""
        ...

    @abstractmethod
    async def get_intraday_bars(
        self,
        symbol: str,
        interval: str = "5min",
        start_date: Optional[date] = None,
    ) -> list[OHLCVBar]:
        """Intraday OHLCV bars."""
        ...
